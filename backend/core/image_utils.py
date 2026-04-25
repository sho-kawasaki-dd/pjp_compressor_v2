from __future__ import annotations

"""JPEG/PNG 圧縮と画像リサイズ処理を担当する。

画像系は UI から受け取る設定が比較的柔らかく、品質値やリサイズ指定が複数形式で
流入する。このモジュールではそれらを安全側へ正規化し、pngquant が無い環境でも
処理全体を止めずに同等の出力責務を維持する。
"""

import io
import subprocess
from pathlib import Path

from PIL import Image, ImageCms
from shared.runtime_paths import describe_tool_source, resolve_pngquant_executable


MAX_IMAGE_QUALITY = 100
PNGQUANT_TIMEOUT_SECONDS = 300


def _append_pngquant_fallback_details(message: str, *, source: str, reason: str) -> str:
    """Pillow フォールバック時の pngquant 状態をログ文言へ補足する。"""
    return f'{message} [pngquant={describe_tool_source(source)}, fallback={reason}]'


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
            converted.load()
            return converted, True
        except Exception:
            pass

    # ICC が扱えなくても RGB 化だけは実施し、圧縮処理全体を止めない。
    converted = img.convert('RGB')
    converted.load()
    return converted, True


def compress_image_pillow(input_path, output_path, quality, resize_cfg=None):
    """Pillow を用いて JPEG/PNG を品質指定で保存。必要に応じてリサイズも行う。

    ここは pngquant の有無に関係なく常に使える基準経路であり、リサイズ戦略も
    `manual` と `long_edge` を同じ辞書形式で受け取って吸収する。フォールバック先と
    しても利用されるため、例外を出しにくい保守的な振る舞いを優先する。
    """
    input_file = Path(input_path)
    output_file = Path(output_path)
    safe_quality = _clamp_quality(quality)

    try:
        img = Image.open(str(input_file))
        img.load()
        # 保存形式や resize ロジックは RGB 系モードの方が安定するため、最上流で吸収する。
        img, _cmyk_converted = _convert_cmyk_to_rgb(img)
        if resize_cfg and resize_cfg.get('enabled'):
            # UI 側では複数の入力形式を許容しているため、ここで mode を見て
            # 実際のリサイズ戦略へ落とし込む。
            mode = resize_cfg.get('mode', 'manual')
            orig_w, orig_h = img.size
            if mode == 'long_edge':
                target = int(resize_cfg.get('long_edge', 0) or 0)
                if target > 0:
                    # 長辺基準は縦横の向きを問わず同じ UI 設定で扱える点が利点。
                    long = max(orig_w, orig_h)
                    scale = target / long
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            else:
                w = int(resize_cfg.get('width', 0) or 0)
                h = int(resize_cfg.get('height', 0) or 0)
                keep = bool(resize_cfg.get('keep_aspect', True))
                if w > 0 or h > 0:
                    if keep:
                        # 枠内に収めるモードなので、両方指定時は小さい方の倍率を使う。
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
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        img.save(str(output_file), optimize=True, quality=safe_quality)
        msg_extra = ""
        if resize_cfg and resize_cfg.get('enabled'):
            msg_extra = f", resize={img.size[0]}x{img.size[1]}"
        return True, f"画像圧縮(Pillow): {input_file.name} → OK (quality={safe_quality}{msg_extra})"
    except Exception as e:
        return False, f"画像失敗: {input_file.name} ({e})"


def compress_png_pngquant(input_path, output_path, quality_min, quality_max, speed=3, resize_cfg=None):
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

    resolution = resolve_pngquant_executable()
    if not resolution.available:
        # pngquant は任意依存のため、未導入でも PNG 圧縮処理自体は継続させる。
        ok, message = compress_image_pillow(str(input_file), str(output_file), safe_quality_max, resize_cfg=resize_cfg)
        return ok, _append_pngquant_fallback_details(message, source=resolution.source, reason='pngquant_unavailable')
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
                img, _cmyk_converted = _convert_cmyk_to_rgb(img)
                mode = resize_cfg.get('mode', 'manual')
                orig_w, orig_h = img.size
                if mode == 'long_edge':
                    target = int(resize_cfg.get('long_edge', 0) or 0)
                    if target > 0:
                        long = max(orig_w, orig_h)
                        scale = target / long
                        new_w = max(1, int(orig_w * scale))
                        new_h = max(1, int(orig_h * scale))
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        resized_wh = (new_w, new_h)
                else:
                    w = int(resize_cfg.get('width', 0) or 0)
                    h = int(resize_cfg.get('height', 0) or 0)
                    keep = bool(resize_cfg.get('keep_aspect', True))
                    if w > 0 or h > 0:
                        if keep:
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
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        resized_wh = (new_w, new_h)
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
            msg = f"PNG圧縮(pngquant:{describe_tool_source(resolution.source)}): {input_file.name} → OK (quality={qarg})"
            if resized_wh and resize_cfg and resize_cfg.get('enabled'):
                msg += f", resize={resized_wh[0]}x{resized_wh[1]}"
            return True, msg
        # CLI が失敗した場合でも呼び出し側の制御を増やさないため、そのまま Pillow へ退避する。
        ok, message = compress_image_pillow(str(input_file), str(output_file), safe_quality_max, resize_cfg=resize_cfg)
        fallback_reason = (result.stderr or '').strip() or f'pngquant_exit_{result.returncode}'
        return ok, _append_pngquant_fallback_details(message, source=resolution.source, reason=fallback_reason)
    except Exception as exc:
        ok, message = compress_image_pillow(str(input_file), str(output_file), safe_quality_max, resize_cfg=resize_cfg)
        return ok, _append_pngquant_fallback_details(message, source=resolution.source, reason=f'pngquant_exception:{exc}')
    finally:
        try:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
