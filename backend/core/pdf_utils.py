from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from shared.configs import (
    GS_DEFAULT_PRESET,
    PDF_COMPRESS_MODES,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
)


def _import_fitz():
    try:
        import fitz as fitz_module

        return fitz_module, None
    except Exception as e:
        return None, e


def _import_pikepdf():
    try:
        import pikepdf as pikepdf_module

        return pikepdf_module, None
    except Exception as e:
        return None, e


def compress_pdf_lossy(
    input_path,
    output_path,
    target_dpi=PDF_LOSSY_DPI_DEFAULT,
    jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
):
    """PyMuPDF で PDF 内の全埋め込み画像を走査し、リサンプル＆再圧縮する（非可逆）。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    fitz_module, fitz_error = _import_fitz()
    if fitz_module is None:
        return False, f"PDF非可逆圧縮失敗: {input_file.name} (PyMuPDF(fitz)が利用できません: {fitz_error})"

    try:
        doc = fitz_module.open(str(input_file))
        replaced_count = 0
        skipped_count = 0
        compressed_cache: dict[int, bytes | None] = {}

        for page_index in range(len(doc)):
            page = doc[page_index]
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]

                if xref in compressed_cache:
                    cached = compressed_cache[xref]
                    if cached is not None:
                        page.replace_image(xref, stream=cached)
                    continue

                rects = page.get_image_rects(xref)
                if not rects:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                rect = rects[0]
                rect_w_pts = rect.width
                rect_h_pts = rect.height

                if rect_w_pts == 0 or rect_h_pts == 0:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                base_image = doc.extract_image(xref)
                if not base_image:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                img_bytes = base_image['image']
                img_ext = base_image.get('ext', '').lower()
                orig_size = len(img_bytes)

                if img_ext in ('jbig2', 'tiff', 'tif', 'jpx'):
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                try:
                    pil_img = Image.open(io.BytesIO(img_bytes))
                except Exception:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                orig_w, orig_h = pil_img.size
                effective_dpi_x = orig_w / (rect_w_pts / 72.0)
                effective_dpi_y = orig_h / (rect_h_pts / 72.0)
                effective_dpi = max(effective_dpi_x, effective_dpi_y)

                if effective_dpi > target_dpi:
                    scale = target_dpi / effective_dpi
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
                    pil_img = pil_img.resize((new_w, new_h), resample_filter)

                is_lossless = img_ext in ('png', 'bmp', 'tiff', 'tif', 'gif')
                buf = io.BytesIO()

                if is_lossless and not png_to_jpeg:
                    if pil_img.mode not in ('RGB', 'RGBA', 'L', 'LA'):
                        pil_img = pil_img.convert('RGBA' if ('A' in pil_img.mode or pil_img.mode == 'P') else 'RGB')
                    pil_img.save(buf, format='PNG', optimize=True)
                else:
                    if pil_img.mode in ('RGBA', 'PA', 'LA', 'P'):
                        if pil_img.mode == 'P':
                            pil_img = pil_img.convert('RGBA')
                        if 'A' in pil_img.mode:
                            background = Image.new('RGB', pil_img.size, (255, 255, 255))
                            background.paste(pil_img, mask=pil_img.split()[-1])
                            pil_img = background
                    if pil_img.mode != 'RGB':
                        pil_img = pil_img.convert('RGB')
                    pil_img.save(buf, format='JPEG', quality=jpeg_quality, optimize=True)

                new_bytes = buf.getvalue()

                if len(new_bytes) < orig_size:
                    page.replace_image(xref, stream=new_bytes)
                    compressed_cache[xref] = new_bytes
                    replaced_count += 1
                else:
                    compressed_cache[xref] = None
                    skipped_count += 1

        doc.save(str(output_file), garbage=4, deflate=True)
        doc.close()

        total_images = replaced_count + skipped_count
        detail = f"一意の画像{total_images}個中{replaced_count}個を再圧縮"
        if png_to_jpeg:
            detail += ', PNG→JPEG変換あり'
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
    png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
    lossless_options=None,
):
    """ネイティブ（PyMuPDF + pikepdf）PDF 圧縮の統合関数。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    if mode not in PDF_COMPRESS_MODES:
        mode = 'both'

    if mode == 'lossy':
        return compress_pdf_lossy(str(input_file), str(output_file), target_dpi, jpeg_quality, png_to_jpeg)
    if mode == 'lossless':
        return compress_pdf_lossless(str(input_file), str(output_file), lossless_options)

    tmp_path = output_file.with_suffix(output_file.suffix + '.tmp_lossy.pdf')
    try:
        ok_lossy, msg_lossy = compress_pdf_lossy(str(input_file), str(tmp_path), target_dpi, jpeg_quality, png_to_jpeg)
        if not ok_lossy:
            ok_ll, msg_ll = compress_pdf_lossless(str(input_file), str(output_file), lossless_options)
            return ok_ll, f"{msg_lossy} / {msg_ll}"

        ok_ll, msg_ll = compress_pdf_lossless(str(tmp_path), str(output_file), lossless_options)
        if not ok_ll:
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
