from __future__ import annotations

"""PDF 圧縮の実装をエンジン別にまとめる。

ネイティブ系は PyMuPDF と pikepdf を組み合わせ、Ghostscript 系は再蒸留後に
必要なら pikepdf で可逆最適化を重ねる。
"""

import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

from PIL import Image

from backend.settings import (
    GS_DEFAULT_PRESET,
    PDF_ALLOWED_MODES,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_QUALITY_DEFAULT,
)


PDF_PNG_LIKE_EXTENSIONS = frozenset({'png', 'bmp', 'tiff', 'tif', 'gif'})
PDF_UNSUPPORTED_RASTER_EXTENSIONS = frozenset({'jbig2', 'jpx'})


def _import_fitz():
    """PyMuPDF を遅延 import し、未導入時も呼び出し側で扱える形にする。"""
    try:
        import fitz as fitz_module

        return fitz_module, None
    except Exception as e:
        return None, e


def _import_pikepdf():
    """pikepdf を遅延 import し、依存未導入時のメッセージ生成に使う。"""
    try:
        import pikepdf as pikepdf_module

        return pikepdf_module, None
    except Exception as e:
        return None, e


def _normalize_pdf_png_source_image(pil_img: Image.Image) -> Image.Image:
    """PNG 系量子化へ渡す前に Pillow 画像モードを正規化する。

    PDF から抽出される画像は palette/CMYK/LA など多様なモードを取りうる。
    pngquant と Pillow quantize の双方が安定して扱える形へ寄せておくと、
    フォールバック条件と出力差を読み解きやすくなる。
    """
    has_alpha = 'A' in pil_img.getbands() or 'transparency' in pil_img.info

    if pil_img.mode in ('RGB', 'RGBA', 'L'):
        return pil_img
    if pil_img.mode == 'LA':
        return pil_img.convert('RGBA')
    if pil_img.mode == 'P':
        return pil_img.convert('RGBA' if has_alpha else 'RGB')
    return pil_img.convert('RGBA' if has_alpha else 'RGB')


def _pdf_image_has_transparency(pil_img: Image.Image) -> bool:
    """Pillow 画像に実効的な透過画素が含まれるかを返す。"""
    if 'A' in pil_img.getbands():
        try:
            alpha_min, _alpha_max = pil_img.getchannel('A').getextrema()
            return alpha_min < 255
        except Exception:
            return True

    transparency = pil_img.info.get('transparency')
    if transparency is None:
        return False
    if isinstance(transparency, bytes):
        return any(value < 255 for value in transparency)
    return True


def _get_pdf_resize_resample_filter():
    """PDF 画像の縮小で使う Pillow リサンプラを返す。"""
    if hasattr(Image, 'Resampling'):
        return Image.Resampling.LANCZOS
    return getattr(cast(Any, Image), 'LANCZOS')


def _open_pdf_raster_image(img_bytes: bytes) -> Image.Image:
    """PDF から抽出したラスター画像 bytes を Pillow 画像へ読む。"""
    pil_img = Image.open(io.BytesIO(img_bytes))
    pil_img.load()
    return pil_img


def _normalize_pdf_soft_mask(mask_img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """PDF soft mask を base image と同じサイズの L 画像へ整える。"""
    if mask_img.size != size:
        mask_img = mask_img.resize(size, _get_pdf_resize_resample_filter())
    if mask_img.mode != 'L':
        mask_img = mask_img.convert('L')
    return mask_img


def _load_pdf_raster_image_with_soft_mask(doc, base_image: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    """PDF 画像本体と任意の soft mask を 1 枚の Pillow 画像へ再構成する。"""
    pil_img = _open_pdf_raster_image(cast(bytes, base_image['image']))
    smask_xref = base_image.get('smask', 0)
    if not isinstance(smask_xref, int) or smask_xref <= 0:
        return pil_img, {
            'smask_xref': 0,
            'soft_mask_applied': False,
            'soft_mask_error': None,
            'has_transparency': _pdf_image_has_transparency(pil_img),
        }

    soft_mask = doc.extract_image(smask_xref)
    if not soft_mask:
        return pil_img, {
            'smask_xref': smask_xref,
            'soft_mask_applied': False,
            'soft_mask_error': 'smask_extract_failed',
            'has_transparency': _pdf_image_has_transparency(pil_img),
        }

    try:
        mask_img = _open_pdf_raster_image(cast(bytes, soft_mask['image']))
        alpha_mask = _normalize_pdf_soft_mask(mask_img, pil_img.size)
        transparency_present = alpha_mask.getextrema()[0] < 255
        if pil_img.mode != 'RGBA':
            pil_img = pil_img.convert('RGBA')
        pil_img.putalpha(alpha_mask)
        return pil_img, {
            'smask_xref': smask_xref,
            'soft_mask_applied': True,
            'soft_mask_error': None,
            'has_transparency': transparency_present,
        }
    except Exception as exc:
        return pil_img, {
            'smask_xref': smask_xref,
            'soft_mask_applied': False,
            'soft_mask_error': f'smask_open_failed:{exc}',
            'has_transparency': _pdf_image_has_transparency(pil_img),
        }


def _get_pillow_quantize_method(pil_img: Image.Image) -> int:
    """256 色固定フォールバックで使う量子化アルゴリズムを返す。"""
    quantize_enum = getattr(Image, 'Quantize', None)
    if pil_img.mode == 'RGBA':
        return getattr(quantize_enum, 'FASTOCTREE', 2) if quantize_enum else 2
    return getattr(quantize_enum, 'MEDIANCUT', 0) if quantize_enum else 0


def _compress_pdf_png_with_pillow(pil_img: Image.Image) -> bytes:
    """pngquant が使えない場合の 256 色固定フォールバックを生成する。

    GUI から渡る PNG 品質値は pngquant 専用の調整ノブとして扱うため、
    Pillow フォールバック時は値を参照せず、常に 256 色固定へ減色する。
    """
    normalized = _normalize_pdf_png_source_image(pil_img)
    quantized = normalized.quantize(colors=256, method=_get_pillow_quantize_method(normalized))
    buffer = io.BytesIO()
    quantized.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def _compress_pdf_png_with_pngquant(pil_img: Image.Image, png_quality: int) -> tuple[bytes | None, dict[str, Any]]:
    """pngquant を使って PDF 内 PNG 系画像を量子化する。

    pngquant はファイルベースの CLI なので、一時 PNG を経由して実行する。
    ここで失敗しても PDF 圧縮全体を止めず、呼び出し側が Pillow 256 色固定へ
    退避できるように詳細だけ返す。
    """
    pngquant_exe = shutil.which('pngquant')
    if not pngquant_exe:
        return None, {'fallback_reason': 'pngquant_unavailable'}

    safe_quality = max(0, min(100, int(png_quality)))
    quality_min = max(0, safe_quality - 20)
    quality_max = safe_quality
    normalized = _normalize_pdf_png_source_image(pil_img)

    with tempfile.TemporaryDirectory(prefix='pjp_pdf_png_') as temp_dir:
        temp_root = Path(temp_dir)
        src_path = temp_root / 'source.png'
        out_path = temp_root / 'quantized.png'
        normalized.save(src_path, format='PNG', optimize=True)

        cmd = [
            pngquant_exe,
            f'--quality={quality_min}-{quality_max}',
            '--speed=3',
            '--force',
            '--output', str(out_path),
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
        )
        if result.returncode == 0 and out_path.exists():
            return out_path.read_bytes(), {
                'quality_range': (quality_min, quality_max),
                'fallback_reason': None,
            }

        return None, {
            'quality_range': (quality_min, quality_max),
            'fallback_reason': result.stderr.strip() or f'pngquant_exit_{result.returncode}',
        }


def _compress_pdf_png_image(pil_img: Image.Image, png_quality: int) -> tuple[bytes, dict[str, Any]]:
    """PDF 内 PNG 系画像を pngquant 優先、Pillow 256 色固定フォールバックで再圧縮する。"""
    quantized_bytes, pngquant_meta = _compress_pdf_png_with_pngquant(pil_img, png_quality)
    if quantized_bytes is not None:
        return quantized_bytes, {
            'quantizer': 'pngquant',
            'quality_range': pngquant_meta.get('quality_range'),
            'fallback_reason': None,
        }

    return _compress_pdf_png_with_pillow(pil_img), {
        'quantizer': 'Pillow 256-color fallback',
        'quality_range': None,
        'fallback_reason': pngquant_meta.get('fallback_reason'),
    }


def compress_pdf_lossy(
    input_path,
    output_path,
    target_dpi=PDF_LOSSY_DPI_DEFAULT,
    jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    png_quality=PDF_LOSSY_PNG_QUALITY_DEFAULT,
    debug=False,
):
    """PyMuPDF で PDF 内の実描画画像を走査し、リサンプル＆再圧縮する（非可逆）。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    fitz_module, fitz_error = _import_fitz()
    if fitz_module is None:
        return False, f"PDF非可逆圧縮失敗: {input_file.name} (PyMuPDF(fitz)が利用できません: {fitz_error})"

    try:
        doc = fitz_module.open(str(input_file))
        replaced_count = 0
        skipped_count = 0

        # xref 単位で一度だけ判定する。
        # replace_image() は画像オブジェクト自体を差し替えるため、
        # 同じ xref が別ページに再登場しても再処理は不要。
        processed_xrefs: dict[int, str] = {}

        debug_stats = {
            'pages': len(doc),
            'image_infos_seen': 0,
            'unique_xrefs_seen': 0,
            'skip_xref_missing': 0,
            'skip_already_processed': 0,
            'skip_zero_rect': 0,
            'skip_no_extract': 0,
            'skip_unsupported_ext': 0,
            'skip_pil_open_failed': 0,
            'skip_not_smaller': 0,
            'soft_mask_seen': 0,
            'soft_mask_applied': 0,
            'soft_mask_failed': 0,
            'pngquant_used': 0,
            'pillow_png_fallback_used': 0,
            'replaced': 0,
        }
        debug_seen_xrefs = set()
        debug_rows = []
        png_quantizers_used: set[str] = set()

        def _rect_from_bbox(bbox):
            if bbox is None:
                return None
            try:
                return fitz_module.Rect(bbox)
            except Exception:
                return None

        for page_index in range(len(doc)):
            page = doc[page_index]
            image_infos = page.get_image_info(xrefs=True)

            for info in image_infos:
                debug_stats['image_infos_seen'] += 1

                xref = info.get('xref', 0)
                if not isinstance(xref, int) or xref <= 0:
                    skipped_count += 1
                    debug_stats['skip_xref_missing'] += 1
                    if debug:
                        debug_rows.append({
                            'page': page_index + 1,
                            'xref': xref,
                            'status': 'skip_xref_missing',
                        })
                    continue

                if xref not in debug_seen_xrefs:
                    debug_seen_xrefs.add(xref)
                    debug_stats['unique_xrefs_seen'] += 1

                if xref in processed_xrefs:
                    skipped_count += 1
                    debug_stats['skip_already_processed'] += 1
                    if debug:
                        debug_rows.append({
                            'page': page_index + 1,
                            'xref': xref,
                            'status': f"skip_already_processed:{processed_xrefs[xref]}",
                        })
                    continue

                rect = _rect_from_bbox(info.get('bbox'))
                if rect is None or rect.width == 0 or rect.height == 0:
                    processed_xrefs[xref] = 'zero_rect'
                    skipped_count += 1
                    debug_stats['skip_zero_rect'] += 1
                    if debug:
                        debug_rows.append({
                            'page': page_index + 1,
                            'xref': xref,
                            'status': 'skip_zero_rect',
                            'bbox': info.get('bbox'),
                        })
                    continue

                rect_w_pts = rect.width
                rect_h_pts = rect.height

                base_image = doc.extract_image(xref)
                if not base_image:
                    processed_xrefs[xref] = 'no_extract'
                    skipped_count += 1
                    debug_stats['skip_no_extract'] += 1
                    if debug:
                        debug_rows.append({
                            'page': page_index + 1,
                            'xref': xref,
                            'status': 'skip_no_extract',
                        })
                    continue

                img_bytes = base_image['image']
                img_ext = str(base_image.get('ext', '')).lower()
                orig_size = len(img_bytes)

                if img_ext in PDF_UNSUPPORTED_RASTER_EXTENSIONS:
                    processed_xrefs[xref] = 'unsupported_ext'
                    skipped_count += 1
                    debug_stats['skip_unsupported_ext'] += 1
                    if debug:
                        debug_rows.append({
                            'page': page_index + 1,
                            'xref': xref,
                            'status': 'skip_unsupported_ext',
                            'ext': img_ext,
                            'orig_size': orig_size,
                        })
                    continue

                try:
                    pil_img, transparency_meta = _load_pdf_raster_image_with_soft_mask(doc, base_image)
                except Exception as exc:
                    processed_xrefs[xref] = 'pil_open_failed'
                    skipped_count += 1
                    debug_stats['skip_pil_open_failed'] += 1
                    if debug:
                        debug_rows.append({
                            'page': page_index + 1,
                            'xref': xref,
                            'status': 'skip_pil_open_failed',
                            'ext': img_ext,
                            'orig_size': orig_size,
                            'error': str(exc),
                        })
                    continue

                soft_mask_xref = cast(int, transparency_meta['smask_xref'])
                soft_mask_error = cast(str | None, transparency_meta['soft_mask_error'])
                soft_mask_applied = cast(bool, transparency_meta['soft_mask_applied'])
                has_transparency = cast(bool, transparency_meta['has_transparency'])
                if soft_mask_xref > 0:
                    debug_stats['soft_mask_seen'] += 1
                    if soft_mask_applied:
                        debug_stats['soft_mask_applied'] += 1
                    else:
                        debug_stats['soft_mask_failed'] += 1

                orig_w, orig_h = pil_img.size
                effective_dpi_x = orig_w / (rect_w_pts / 72.0)
                effective_dpi_y = orig_h / (rect_h_pts / 72.0)
                effective_dpi = max(effective_dpi_x, effective_dpi_y)

                resized = False
                resized_to = (orig_w, orig_h)
                if effective_dpi > target_dpi:
                    scale = target_dpi / effective_dpi
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    resample_filter = _get_pdf_resize_resample_filter()
                    pil_img = pil_img.resize((new_w, new_h), resample_filter)
                    resized = True
                    resized_to = (new_w, new_h)

                is_png_like = img_ext in PDF_PNG_LIKE_EXTENSIONS
                preserve_as_png = is_png_like or has_transparency
                png_metadata: dict[str, Any] | None = None

                if preserve_as_png:
                    # PNG 系画像は JPEG へ逃がさず、常に量子化済み PNG として再保存する。
                    # soft mask で表現された透過もここで保ったまま再保存する。
                    new_bytes, png_metadata = _compress_pdf_png_image(pil_img, png_quality)
                    output_format = 'PNG'
                    png_quantizers_used.add(str(png_metadata['quantizer']))
                    if png_metadata['quantizer'] == 'pngquant':
                        debug_stats['pngquant_used'] += 1
                    else:
                        debug_stats['pillow_png_fallback_used'] += 1
                else:
                    buf = io.BytesIO()
                    if pil_img.mode in ('RGBA', 'PA', 'LA', 'P'):
                        if pil_img.mode == 'P':
                            pil_img = pil_img.convert('RGBA')
                        if 'A' in pil_img.mode:
                            background = Image.new('RGB', pil_img.size, (255, 255, 255))
                            background.paste(pil_img, mask=pil_img.split()[-1])
                            pil_img = background
                    if pil_img.mode != 'RGB':
                        pil_img = pil_img.convert('RGB')
                    output_format = 'JPEG'
                    pil_img.save(buf, format='JPEG', quality=jpeg_quality, optimize=True)
                    new_bytes = buf.getvalue()

                new_size = len(new_bytes)

                row = {
                    'page': page_index + 1,
                    'xref': xref,
                    'status': None,
                    'ext': img_ext,
                    'orig_px': (orig_w, orig_h),
                    'rect_pts': (round(rect_w_pts, 2), round(rect_h_pts, 2)),
                    'effective_dpi': round(effective_dpi, 2),
                    'resized': resized,
                    'resized_to': resized_to,
                    'has_transparency': has_transparency,
                    'soft_mask_xref': soft_mask_xref,
                    'soft_mask_applied': soft_mask_applied,
                    'soft_mask_error': soft_mask_error,
                    'orig_size': orig_size,
                    'new_size': new_size,
                    'output_format': output_format,
                    'png_quantizer': png_metadata.get('quantizer') if png_metadata else None,
                    'png_quality_range': png_metadata.get('quality_range') if png_metadata else None,
                    'png_fallback_reason': png_metadata.get('fallback_reason') if png_metadata else None,
                }

                if new_size < orig_size:
                    page.replace_image(xref, stream=new_bytes)
                    processed_xrefs[xref] = 'replaced'
                    replaced_count += 1
                    debug_stats['replaced'] += 1
                    row['status'] = 'replaced'
                else:
                    processed_xrefs[xref] = 'not_smaller'
                    skipped_count += 1
                    debug_stats['skip_not_smaller'] += 1
                    row['status'] = 'skip_not_smaller'

                if debug:
                    debug_rows.append(row)

        if debug:
            print('=== compress_pdf_lossy debug summary ===')
            for key, value in debug_stats.items():
                print(f'{key}: {value}')

            print('=== compress_pdf_lossy debug details (first 50 unique xrefs) ===')
            shown = 0
            shown_xrefs = set()
            for row in debug_rows:
                xref = row['xref']
                if xref in shown_xrefs:
                    continue
                shown_xrefs.add(xref)
                print(row)
                shown += 1
                if shown >= 50:
                    break

        doc.save(str(output_file), garbage=4, deflate=True)
        doc.close()

        total_images = replaced_count + skipped_count
        detail = f"一意の画像{total_images}個中{replaced_count}個を再圧縮"
        if png_quantizers_used:
            detail += f", PNG量子化={', '.join(sorted(png_quantizers_used))}"
        return True, f"PDF非可逆圧縮(PyMuPDF): {input_file.name} → OK ({detail}, DPI={target_dpi}, JPEG品質={jpeg_quality})"
    except Exception as e:
        return False, f"PDF非可逆圧縮失敗: {input_file.name} ({e})"


def compress_pdf_lossless(input_path, output_path, options=None):
    """pikepdf を用いた PDF の構造最適化（可逆）。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    if options is None:
        options = dict(PDF_LOSSLESS_OPTIONS_DEFAULT)

    pikepdf_module, pikepdf_error = _import_pikepdf()
    if pikepdf_module is None:
        return False, f"PDF可逆圧縮失敗: {input_file.name} (pikepdfが利用できません: {pikepdf_error})"

    try:
        with pikepdf_module.open(str(input_file)) as pdf:
            if options.get('remove_unreferenced', True):
                pdf.remove_unreferenced_resources()

            if options.get('clean_metadata', False):
                # 配布用途では作成ソフト情報を消したいケースがあるため任意化している。
                if '/Metadata' in pdf.Root:
                    del pdf.Root.Metadata
                if '/Info' in pdf.trailer:
                    try:
                        del pdf.trailer['/Info']
                    except Exception:
                        pass

            if options.get('object_streams', True):
                osm = pikepdf_module.ObjectStreamMode.generate
            else:
                osm = pikepdf_module.ObjectStreamMode.preserve

            do_recompress = options.get('recompress_streams', True)

            pdf.save(
                str(output_file),
                linearize=options.get('linearize', True),
                object_stream_mode=osm,
                compress_streams=True,
                recompress_flate=do_recompress,
            )

        applied = []
        if options.get('linearize'):
            applied.append('Linearize')
        if options.get('object_streams'):
            applied.append('ObjStream圧縮')
        if options.get('clean_metadata'):
            applied.append('メタデータ除去')
        if options.get('recompress_streams'):
            applied.append('Flate再圧縮')
        if options.get('remove_unreferenced'):
            applied.append('孤立リソース削除')
        opts_str = ', '.join(applied) if applied else 'なし'
        return True, f"PDF可逆圧縮(pikepdf): {input_file.name} → OK ({opts_str})"
    except Exception as e:
        return False, f"PDF可逆圧縮失敗: {input_file.name} ({e})"


def get_ghostscript_path():
    """OSに応じてGhostscriptの実行パスを取得する。"""
    candidates = ['gswin64c', 'gswin32c', 'gs']
    for cmd in candidates:
        path = shutil.which(cmd)
        if path:
            return path
    return None


def compress_pdf_ghostscript(input_path, output_path, preset='ebook', custom_dpi=None):
    """Ghostscriptを利用してPDFを再蒸留・圧縮する。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    gs_exe = get_ghostscript_path()
    if not gs_exe:
        return False, 'Ghostscriptが見つかりません。インストールされているか確認してください。'

    cmd = [
        gs_exe,
        '-sDEVICE=pdfwrite',
        '-dCompatibilityLevel=1.4',
        '-dNOPAUSE',
        '-dQUIET',
        '-dBATCH',
    ]

    if preset == 'custom' and custom_dpi:
        # カスタム DPI は各画像種別を明示指定し、プリセットより優先して解像度を固定する。
        cmd.extend([
            '-dColorImageDownsampleType=/Bicubic',
            f'-dColorImageResolution={custom_dpi}',
            '-dGrayImageDownsampleType=/Bicubic',
            f'-dGrayImageResolution={custom_dpi}',
            '-dMonoImageDownsampleType=/Bicubic',
            f'-dMonoImageResolution={custom_dpi * 2}',
        ])
    else:
        valid_presets = ['screen', 'ebook', 'printer', 'prepress', 'default']
        safe_preset = preset if preset in valid_presets else 'ebook'
        cmd.append(f'-dPDFSETTINGS=/{safe_preset}')

    cmd.extend([
        f'-sOutputFile={str(output_file)}',
        str(input_file),
    ])

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)

        if result.returncode == 0 and output_file.exists():
            orig_size = input_file.stat().st_size
            out_size = output_file.stat().st_size

            if out_size >= orig_size:
                # Ghostscript は内容次第で逆に肥大化するため、悪化時は元ファイルを維持する。
                shutil.copy2(str(input_file), str(output_file))
                return True, f"PDF圧縮(GS): {input_file.name} → 圧縮効果なし（元ファイルを維持）"

            mode_str = f'custom_dpi={custom_dpi}' if preset == 'custom' else f'preset={preset}'
            return True, f"PDF圧縮(GS): {input_file.name} → OK ({mode_str})"
        return False, f"PDF圧縮(GS) エラー: {result.stderr.strip()}"

    except Exception as e:
        return False, f"PDF圧縮(GS) 実行失敗: {e}"


def compress_pdf_native(
    input_path,
    output_path,
    mode='both',
    target_dpi=PDF_LOSSY_DPI_DEFAULT,
    jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    png_quality=PDF_LOSSY_PNG_QUALITY_DEFAULT,
    lossless_options=None,
    debug=False,
):
    """ネイティブ（PyMuPDF + pikepdf）PDF 圧縮の統合関数。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    if mode not in PDF_ALLOWED_MODES:
        mode = 'both'

    if mode == 'lossy':
        return compress_pdf_lossy(str(input_file), str(output_file), target_dpi, jpeg_quality, png_quality, debug)
    if mode == 'lossless':
        return compress_pdf_lossless(str(input_file), str(output_file), lossless_options)

    # `both` は一旦非可逆で画像を落としてから、最終 PDF 全体を可逆最適化する。
    tmp_path = output_file.with_suffix(output_file.suffix + '.tmp_lossy.pdf')
    try:
        ok_lossy, msg_lossy = compress_pdf_lossy(str(input_file), str(tmp_path), target_dpi, jpeg_quality, png_quality, debug)
        if not ok_lossy:
            ok_ll, msg_ll = compress_pdf_lossless(str(input_file), str(output_file), lossless_options)
            return ok_ll, f"{msg_lossy} / {msg_ll}"

        ok_ll, msg_ll = compress_pdf_lossless(str(tmp_path), str(output_file), lossless_options)
        if not ok_ll:
            # 段階後半だけ失敗しても、前段の成果物を捨てるよりは結果を残す方を優先する。
            shutil.copy2(str(tmp_path), str(output_file))
            return True, f"{msg_lossy} / {msg_ll}（可逆段失敗、非可逆結果を採用）"

        return True, f"{msg_lossy} / {msg_ll}"
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def compress_pdf_gs(input_path, output_path, preset=GS_DEFAULT_PRESET, custom_dpi=None, lossless_options=None):
    """GhostScript による PDF 再蒸留 + オプションで pikepdf 構造最適化。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    if lossless_options:
        tmp_path = output_file.with_suffix(output_file.suffix + '.tmp_gs.pdf')
        try:
            ok_gs, msg_gs = compress_pdf_ghostscript(str(input_file), str(tmp_path), preset, custom_dpi)
            if not ok_gs:
                return False, msg_gs

            ok_ll, msg_ll = compress_pdf_lossless(str(tmp_path), str(output_file), lossless_options)
            if not ok_ll:
                # GS 結果が得られている場合は、可逆段の失敗だけで全体を失敗扱いにしない。
                shutil.copy2(str(tmp_path), str(output_file))
                return True, f"{msg_gs} / {msg_ll}（可逆段失敗、GS結果を採用）"

            return True, f"{msg_gs} / {msg_ll}"
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
    return compress_pdf_ghostscript(str(input_file), str(output_file), preset, custom_dpi)
