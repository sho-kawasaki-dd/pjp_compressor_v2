from __future__ import annotations

"""JPEG/PNG 圧縮と画像リサイズ処理を担当する。

画像系は UI から受け取る設定が比較的柔らかく、品質値やリサイズ指定が複数形式で
流入する。このモジュールではそれらを安全側へ正規化し、pngquant が無い環境でも
処理全体を止めずに同等の出力責務を維持する。
"""

import io
import dataclasses
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from PIL import Image, ImageCms, ImageOps

from backend.contracts import ImageCompressionConfig, JobControl
from backend.core import job_files
from backend.core.subprocess_utils import sanitize_subprocess_error
from backend.settings import APP_WORK_DIR_NAME, IMAGE_WORK_OWNER_TOKEN, IMAGE_WORK_SUBDIR
from shared.locale_catalog import translate
from shared.runtime_paths import resolve_pngquant_executable


MAX_IMAGE_QUALITY = 100
PNGQUANT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ImageCompressResult:
    ok: bool
    message: str
    final_outpath: str | None
    kept_original: bool = False
    kept_original_reason: Literal['no_gain', 'retention'] | None = None
    cancelled: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImageEncodeOutcome:
    """画像エンコーダーが一時出力または元画像の保持を選んだ結果。"""

    message: str
    retention: bool = False
    notes: tuple[str, ...] = ()


def _append_pngquant_fallback_details(message: str, *, source: str, reason: str, log_language: str) -> str:
    """Pillow フォールバック時の pngquant 状態をログ文言へ補足する。"""
    return f"{message} [pngquant={translate(log_language, f'tool_source.{source}')}, fallback={reason}]"


def _clamp_quality(value, default=MAX_IMAGE_QUALITY):
    """品質値を pngquant/Pillow が扱える 0-100 に正規化する。

    UI やテストは極端値を渡せるため、ここで一度丸めておくことで Pillow 保存時と
    pngquant 呼び出し時の両方に同じ安全基準を適用する。
    """
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(0, min(MAX_IMAGE_QUALITY, parsed))


def _convert_cmyk_to_rgb(img: Image.Image) -> tuple[Image.Image, bool]:
    """CMYK 画像を ICC プロファイル優先で RGB へ変換する。

    単体画像圧縮では JPEG 保存、PNG 量子化前の一時 PNG 生成、リサイズ処理の
    すべてが RGB 系を前提に進むため、読み込み直後に吸収して downstream の責務を
    単純化する。返り値の bool は変換実施有無の観測用である。
    """
    if img.mode != 'CMYK':
        return img, False

    icc_profile = img.info.get('icc_profile')
    if isinstance(icc_profile, bytes) and icc_profile:
        try:
            # 埋め込み ICC を優先して sRGB へ寄せることで、CMYK JPEG の色転びを抑える。
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
            dst_profile = ImageCms.createProfile('sRGB')
            converted = ImageCms.profileToProfile(img, src_profile, dst_profile, outputMode='RGB')
            if converted is not None:
                converted.load()
                return converted, True
        except Exception:
            pass

    # ICC が扱えなくても RGB 化だけは実施し、圧縮処理全体を止めない。
    converted = img.convert('RGB')
    converted.load()
    return converted, True


def _apply_resize(img: Image.Image, resize_cfg: Mapping[str, Any] | None) -> Image.Image:
    if not resize_cfg or not resize_cfg.get('enabled'):
        return img
    orig_w, orig_h = img.size
    if resize_cfg.get('mode', 'manual') == 'long_edge':
        target = int(resize_cfg.get('long_edge', 0) or 0)
        if target <= 0:
            return img
        scale = target / max(orig_w, orig_h)
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))
    else:
        w = int(resize_cfg.get('width', 0) or 0)
        h = int(resize_cfg.get('height', 0) or 0)
        if w <= 0 and h <= 0:
            return img
        if bool(resize_cfg.get('keep_aspect', True)):
            if w > 0 and h > 0:
                scale = min(w / orig_w, h / orig_h)
                new_w = max(1, int(orig_w * scale))
                new_h = max(1, int(orig_h * scale))
            elif w > 0:
                scale = w / orig_w
                new_w = w
                new_h = max(1, int(orig_h * scale))
            else:
                scale = h / orig_h
                new_h = h
                new_w = max(1, int(orig_w * scale))
        else:
            new_w = w if w > 0 else orig_w
            new_h = h if h > 0 else orig_h
    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


def _prepare_image_for_conversion(
    img: Image.Image,
    resize_cfg: Mapping[str, Any] | None = None,
) -> tuple[Image.Image, dict[str, bytes]]:
    """新しい画像経路用に向きと色空間を整え、保存可能なメタデータを返す。"""
    oriented = ImageOps.exif_transpose(img)
    exif = oriented.getexif()
    metadata: dict[str, bytes] = {}
    if exif:
        metadata['exif'] = exif.tobytes()
    icc_profile = oriented.info.get('icc_profile')
    rgb_source = oriented.mode in {'RGB', 'RGBA', 'RGBX', 'RGBa', 'P', 'PA'}
    converted, cmyk_converted = _convert_cmyk_to_rgb(oriented)
    if rgb_source and not cmyk_converted and isinstance(icc_profile, bytes) and icc_profile:
        metadata['icc_profile'] = icc_profile
    else:
        converted.info.pop('icc_profile', None)
    return _apply_resize(converted, resize_cfg), metadata


def converted_image_extension(ext: str, config: ImageCompressionConfig) -> str | None:
    """設定により画像の拡張子が変わる場合だけ、変換先の拡張子を返す。"""
    ext = ext.lower().lstrip('.')
    if config.avif_to_jpeg_compat:
        return '.jpg' if ext == 'avif' else None
    if config.output_format == 'avif' and (
        ext in {'jpg', 'jpeg'} or (ext == 'png' and config.avif_include_png)
    ):
        return '.avif'
    return None


def create_image_job_dir(output_dir: str | Path, job_id: str | None = None) -> Path:
    return job_files.create_owned_job_dir(output_dir, IMAGE_WORK_SUBDIR, IMAGE_WORK_OWNER_TOKEN, job_id)


def cleanup_stale_image_temps(output_dir: str | Path) -> int:
    return job_files.cleanup_owned_job_dirs(output_dir, IMAGE_WORK_SUBDIR, IMAGE_WORK_OWNER_TOKEN)


def _validate_image_work_and_destination(temp_dir: Path, dest: Path) -> None:
    work_root = temp_dir.parent
    work_dir = work_root.parent
    if work_root.name != IMAGE_WORK_SUBDIR or work_dir.name != APP_WORK_DIR_NAME:
        raise OSError(f'not an image job work directory: {temp_dir}')
    output_root = work_dir.parent
    job_files.verify_owned_job_dir(output_root, IMAGE_WORK_SUBDIR, temp_dir, IMAGE_WORK_OWNER_TOKEN)
    resolved_root = output_root.resolve()
    resolved_parent = dest.parent.resolve()
    if resolved_parent != resolved_root and resolved_root not in resolved_parent.parents:
        raise OSError(f'image output is outside the output folder: {dest}')
    existing_parent = dest.parent
    while not existing_parent.exists():
        if existing_parent == existing_parent.parent:
            raise OSError(f'image output parent does not exist: {dest}')
        existing_parent = existing_parent.parent
    if existing_parent.stat().st_dev != temp_dir.stat().st_dev:
        raise OSError(f'image output is on a different filesystem: {dest}')


def place_image_original_copy(
    inpath: str | Path,
    dest: str | Path,
    temp_dir: str | Path,
    job_control: JobControl,
    *,
    log_language: str = 'ja',
) -> bool:
    src, target, work = Path(inpath), Path(dest), Path(temp_dir)
    if job_control.is_cancelled:
        return False
    if src.suffix.lower() != target.suffix.lower() or src.resolve() == target.resolve():
        raise ValueError('original image destination must be distinct and retain the input extension')
    _validate_image_work_and_destination(work, target)
    return job_files.place_original_copy(
        src, target, work, job_control,
        log_language=log_language, temp_delete_message_key='image_temp_delete_failed',
    )


def save_converted_image(
    inpath: str | Path,
    outpath: str | Path,
    original_outpath: str | Path,
    *,
    encode: Callable[[Path], ImageEncodeOutcome],
    keep_if_not_smaller: bool,
    job_control: JobControl,
    temp_dir: Path,
    log_language: str = 'ja',
) -> ImageCompressResult:
    """所有済み一時領域で変換・保持を判定し、停止確認後に正式配置する。"""
    src, dest, original_dest = Path(inpath), Path(outpath), Path(original_outpath)
    temps: list[Path] = []
    notes: tuple[str, ...] = ()

    def t(key: str, **kwargs: Any) -> str:
        return translate(log_language, key, **kwargs)

    try:
        if job_control.is_cancelled:
            raise job_files.JobCancelled()
        if src.suffix.lower() != original_dest.suffix.lower() or dest.suffix.lower() == src.suffix.lower():
            raise ValueError('converted and original image destinations must use the correct extensions')
        if src.resolve() in {dest.resolve(), original_dest.resolve()}:
            raise ValueError('image output must not overwrite the input')
        _validate_image_work_and_destination(temp_dir, dest)
        _validate_image_work_and_destination(temp_dir, original_dest)
        staged = job_files.temp_path(temp_dir, dest.suffix)
        temps.append(staged)
        outcome = encode(staged)
        notes = outcome.notes
        if job_control.is_cancelled:
            raise job_files.JobCancelled()

        reason: Literal['no_gain', 'retention'] | None = 'retention' if outcome.retention else None
        if reason is None:
            if not staged.is_file() or staged.stat().st_size == 0:
                raise OSError('image encoder did not produce an output file')
            output_size = staged.stat().st_size
            input_size = src.stat().st_size
            if keep_if_not_smaller and output_size >= input_size:
                reason = 'no_gain'
            elif not keep_if_not_smaller and output_size > input_size and 'size_increased' not in notes:
                notes = (*notes, 'size_increased')

        if reason is not None:
            staged_original = job_files.temp_path(temp_dir, '.orig')
            temps.append(staged_original)
            try:
                job_files.copy_with_cancel(src, staged_original, job_control)
                job_files.publish(staged_original, original_dest, job_control)
                temps.remove(staged_original)
            except OSError as exc:
                detail = sanitize_subprocess_error(str(exc), src, original_dest, staged_original)
                result = ImageCompressResult(False, t('image_copy_failed', name=src.name, detail=detail), None, notes=notes)
            else:
                key = 'image_kept_original_no_gain' if reason == 'no_gain' else 'image_kept_original_retention'
                result = ImageCompressResult(
                    True,
                    t(key, name=src.name),
                    str(original_dest),
                    kept_original=True,
                    kept_original_reason=reason,
                    notes=notes,
                )
        else:
            try:
                job_files.publish(staged, dest, job_control)
                temps.remove(staged)
            except OSError as exc:
                detail = sanitize_subprocess_error(str(exc), dest, staged)
                result = ImageCompressResult(False, t('image_place_failed', name=src.name, detail=detail), None, notes=notes)
            else:
                result = ImageCompressResult(True, outcome.message, str(dest), notes=notes)
    except job_files.JobCancelled:
        result = ImageCompressResult(False, t('image_cancelled', name=src.name), None, cancelled=True, notes=notes)
    except Exception as exc:
        detail = sanitize_subprocess_error(f'{type(exc).__name__}: {exc}', src, dest, original_dest)
        result = ImageCompressResult(False, t('image_conversion_failed', name=src.name, detail=detail), None, notes=notes)

    failures = job_files.remove_temps(temps, log_language, message_key='image_temp_delete_failed')
    if failures:
        result = dataclasses.replace(
            result,
            message=' / '.join([result.message, *failures]),
            notes=(*result.notes, 'temp_delete_failed'),
        )
    return result


def compress_image_pillow(input_path, output_path, quality, resize_cfg=None, log_language: str = 'ja'):
    """Pillow を用いて JPEG/PNG を品質指定で保存。必要に応じてリサイズも行う。

    ここは pngquant の有無に関係なく常に使える基準経路であり、リサイズ戦略も
    `manual` と `long_edge` を同じ辞書形式で受け取って吸収する。フォールバック先と
    しても利用されるため、例外を出しにくい保守的な振る舞いを優先する。
    """
    input_file = Path(input_path)
    output_file = Path(output_path)
    safe_quality = _clamp_quality(quality)

    def t(key: str, **kwargs):
        return translate(log_language, key, **kwargs)

    try:
        img = Image.open(str(input_file))
        img.load()
        # 保存形式や resize ロジックは RGB 系モードの方が安定するため、最上流で吸収する。
        img, _ = _convert_cmyk_to_rgb(img)
        img = _apply_resize(img, resize_cfg)
        img.save(str(output_file), optimize=True, quality=safe_quality)
        msg_extra = ""
        if resize_cfg and resize_cfg.get('enabled'):
            msg_extra = f", resize={img.size[0]}x{img.size[1]}"
        return True, t('image_pillow_success', name=input_file.name, quality=safe_quality, msg_extra=msg_extra)
    except Exception as e:
        return False, t('image_pillow_failure', name=input_file.name, exc=e)


def compress_png_pngquant(input_path, output_path, quality_min, quality_max, speed=3, resize_cfg=None, log_language: str = 'ja'):
    """pngquant が利用可能ならパレット量子化で高圧縮、無ければ Pillow にフォールバック。

    pngquant は PNG 専用の高圧縮経路だが、任意依存かつ CLI 実行のため失敗要因が多い。
    そのため、この関数の価値は「pngquant を使うこと」よりも「失敗しても同じ API で
    Pillow 経路へ戻せること」にある。
    """
    input_file = Path(input_path)
    output_file = Path(output_path)
    safe_quality_max = _clamp_quality(quality_max)
    # quality range は上限中心で UI から渡されるため、下限は上限を超えないように揃える。
    safe_quality_min = min(_clamp_quality(quality_min, default=safe_quality_max), safe_quality_max)
    safe_speed = max(1, min(11, int(speed)))

    def t(key: str, **kwargs):
        return translate(log_language, key, **kwargs)

    resolution = resolve_pngquant_executable()
    if not resolution.available:
        # pngquant は任意依存のため、未導入でも PNG 圧縮処理自体は継続させる。
        ok, message = compress_image_pillow(str(input_file), str(output_file), safe_quality_max, resize_cfg=resize_cfg, log_language=log_language)
        return ok, _append_pngquant_fallback_details(message, source=resolution.source, reason='pngquant_unavailable', log_language=log_language)

    pngquant_exe = resolution.path
    tmp_path = None
    try:
        qarg = f"{safe_quality_min}-{safe_quality_max}"
        src_path = input_file
        resized_wh = None
        if resize_cfg and resize_cfg.get('enabled'):
            try:
                # pngquant 自身はリサイズをしないため、一時 PNG を作ってから量子化する。
                tmp_path = output_file.with_suffix(output_file.suffix + ".tmp_resize.png")
                img = Image.open(str(input_file))
                img.load()
                # 量子化用の一時 PNG も RGB 前提で作ることで、CMYK 入力をここで閉じ込める。
                img, _ = _convert_cmyk_to_rgb(img)
                resized = _apply_resize(img, resize_cfg)
                if resized is not img:
                    resized_wh = resized.size
                img = resized
                img.save(str(tmp_path), optimize=True)
                src_path = tmp_path
            except Exception:
                # リサイズ前処理に失敗しても、圧縮だけは継続できるよう元画像へ戻す。
                src_path = input_file

        cmd = [
            pngquant_exe,
            f"--quality={qarg}",
            f"--speed={safe_speed}",
            "--force",
            "--output", str(output_file),
            "--",
            str(src_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=PNGQUANT_TIMEOUT_SECONDS,
        )
        if result.returncode == 0 and output_file.exists():
            msg = t('image_pngquant_success', source=translate(log_language, f'tool_source.{resolution.source}'), name=input_file.name, qarg=qarg)
            if resized_wh and resize_cfg and resize_cfg.get('enabled'):
                msg += f", resize={resized_wh[0]}x{resized_wh[1]}"
            return True, msg

        # CLI が失敗した場合でも呼び出し側の制御を増やさないため、そのまま Pillow へ退避する。
        ok, message = compress_image_pillow(str(input_file), str(output_file), safe_quality_max, resize_cfg=resize_cfg, log_language=log_language)
        fallback_reason = (result.stderr or '').strip() or f'pngquant_exit_{result.returncode}'
        return ok, _append_pngquant_fallback_details(message, source=resolution.source, reason=fallback_reason, log_language=log_language)
    except Exception as exc:
        ok, message = compress_image_pillow(str(input_file), str(output_file), safe_quality_max, resize_cfg=resize_cfg, log_language=log_language)
        return ok, _append_pngquant_fallback_details(message, source=resolution.source, reason=f'pngquant_exception:{exc}', log_language=log_language)
    finally:
        try:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
