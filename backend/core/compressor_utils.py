#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_utils.py

PDF と画像（JPG/PNG）の圧縮、およびフォルダ操作（列挙・クリーンアップ・CSV ログ）を
提供するモジュール。GUI から独立しており、スクリプトやテストから再利用可能。

設計方針:
- 外部ツールの検出（pngquant）は実行時に都度チェックし、
    未導入でも例外を致命化しない（可能な範囲でフォールバック）。
- PDF 圧縮は PyMuPDF（埋め込み画像の再圧縮）と pikepdf（構造最適化）の
    2 段構成で行い、非可逆 / 可逆 / 両方を選択可能。
- リサイズは Pillow ベースで、長辺指定と手動（幅/高さ）をサポート。
- 並列処理（ThreadPoolExecutor）で大量ファイルを高速化。
- 進捗更新・ログ出力・統計更新はコールバック関数を受け取り、
    呼び出し側（GUI）に委譲する。

主な提供関数:
- extract_zip_archives(): 指定フォルダ配下の ZIP を再帰展開。
- compress_pdf_lossy(): PyMuPDF による埋め込み画像の再圧縮（非可逆）。
- compress_pdf_lossless(): pikepdf による PDF 構造最適化（可逆）。
- compress_pdf(): 非可逆 / 可逆 / 両方を統合的にディスパッチ。
- compress_image_pillow(): JPEG/PNG を Pillow で品質調整＆リサイズ保存。
- compress_png_pngquant(): pngquant があればパレット量子化、なければ Pillow。
- process_single_file(): 1 ファイル単位の圧縮処理（拡張子に応じて分岐）。
- compress_folder(): フォルダ内の対象ファイルを並列で処理し、CSV ログも出力。
- count_target_files(): 指定拡張子の件数を数える（クリーンアップ事前確認用）。
- cleanup_folder(): 指定拡張子のファイルと空フォルダを削除。
"""
import io
import os
import subprocess
import shutil
import csv
import zipfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
from PIL import Image
import fitz          # PyMuPDF
import pikepdf
from shared.configs import (
    PDF_COMPRESS_MODES,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    GS_PRESETS,
    GS_DEFAULT_PRESET,
)

PUBLIC_BACKEND_API = (
    'compress_folder',
    'cleanup_folder',
    'count_target_files',
    'human_readable',
    'get_ghostscript_path',
)

__all__ = list(PUBLIC_BACKEND_API)


def get_public_api_symbols():
    """互換維持対象の公開APIシンボル一覧を返す。"""
    return PUBLIC_BACKEND_API

def human_readable(n):
    """バイト数を人間可読な単位へ変換する補助関数。"""
    if n < 0:
        return f"-{human_readable(-n)}"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def extract_zip_archives(target_dir, log_func=None, max_cycles=25):
    """入力フォルダ配下の ZIP を再帰的に展開する。無限ループ防止のため複数対策を実施。"""
    if not target_dir or not os.path.isdir(target_dir):
        return 0, 0
    log = log_func if callable(log_func) else (lambda *_: None)
    processed = set()
    extracted_total = 0
    failed_total = 0
    cycle = 0
    try:
        while cycle < max_cycles:
            cycle += 1
            new_zip_handled = False
            for root, _, files in os.walk(target_dir):
                for fname in files:
                    if not fname.lower().endswith('.zip'):
                        continue
                    zip_path = os.path.join(root, fname)
                    if not os.path.isfile(zip_path):
                        continue
                    abs_path = os.path.abspath(zip_path)
                    if abs_path in processed:
                        continue
                    processed.add(abs_path)
                    rel_zip = os.path.relpath(zip_path, target_dir)
                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            member_count = len(zip_ref.infolist())
                            zip_ref.extractall(root)
                        extracted_total += 1
                        new_zip_handled = True
                        log(f"ZIP展開: {rel_zip}（展開ファイル数: {member_count}、サイクル: {cycle}）")
                    except Exception as exc:
                        failed_total += 1
                        log(f"ZIP展開失敗: {rel_zip} ({exc})")
            if not new_zip_handled:
                break
        else:
            log(f"ZIP展開サイクルが上限({max_cycles})に到達しました。循環参照の可能性があります。")
    except Exception as exc:
        log(f"ZIP展開処理全体でエラー: {exc}")
    return extracted_total, failed_total


def compress_pdf_lossy(input_path, output_path, target_dpi=PDF_LOSSY_DPI_DEFAULT,
                       jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
                       png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT):
    """PyMuPDF で PDF 内の全埋め込み画像を走査し、リサンプル＆再圧縮する（非可逆）。

    page.replace_image() を使用して画像を安全に置換する。
    update_stream() はバイナリのみ書き換え、メタデータ（Width/Height/Filter 等）を
    更新しないため PDF 破損の原因となる。replace_image() はメタデータも自動で整合させる。

    実効 DPI は page.get_image_rects() で取得した PDF 上の表示領域サイズ（ポイント単位）
    と画像のピクセル数から逆算する。extract_image() の xres/yres はほとんどの PDF で
    0 を返すため信頼できない。

    引数:
    - input_path: 入力 PDF パス
    - output_path: 出力 PDF パス
    - target_dpi: リサンプル先の DPI（36–600）
    - jpeg_quality: JPEG 再圧縮時の品質（1–100）
    - png_to_jpeg: True の場合、PNG 画像も JPEG に変換して圧縮する。
                   False の場合、PNG 画像はリサイズのみ行いフォーマットを維持する。

    戻り値:
    - (bool, str): 成否とメッセージ
    """
    try:
        doc = fitz.open(input_path)
        replaced_count = 0
        skipped_count = 0

        # 同じ xref を何度も再圧縮しないためのキャッシュ。
        # replace_image() はページ単位の操作なので、同一 xref が複数ページで
        # 参照されている場合は各ページで置換を実行する必要がある。
        # キャッシュにより再圧縮処理自体は 1 回で済ませ、2 ページ目以降は
        # キャッシュ済みバイト列を使って置換のみ行う。
        # 値が None の場合は「圧縮不要 or 失敗」を示し、置換をスキップする。
        compressed_cache: dict[int, bytes | None] = {}

        for page_index in range(len(doc)):
            page = doc[page_index]
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]

                # --- キャッシュ済み xref の処理 ---
                # 別ページで既に圧縮処理を済ませた画像はキャッシュから取得し、
                # このページ上の同一 xref を置換するだけで済ませる。
                if xref in compressed_cache:
                    cached = compressed_cache[xref]
                    if cached is not None:
                        page.replace_image(xref, stream=cached)
                    continue

                # --- 実効 DPI の正確な計算 ---
                # PDF 上の表示領域（BBox）を取得して実際の表示 DPI を逆算する。
                # 計算式: 実効DPI = ピクセル数 / (ポイント数 / 72.0)
                # （PDF の 1 ポイント = 1/72 インチ）
                rects = page.get_image_rects(xref)
                if not rects:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                # 代表として最初の表示領域を使用
                rect = rects[0]
                rect_w_pts = rect.width    # 表示幅（ポイント）
                rect_h_pts = rect.height   # 表示高さ（ポイント）

                # 非表示画像（サイズ 0）はスキップ
                if rect_w_pts == 0 or rect_h_pts == 0:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                # --- 画像データの抽出 ---
                base_image = doc.extract_image(xref)
                if not base_image:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                img_bytes = base_image["image"]
                img_ext = base_image.get("ext", "").lower()
                orig_size = len(img_bytes)

                # ▼▼▼ 追加: 既に高効率な特殊フォーマットは触らない ▼▼▼
                if img_ext in ("jbig2", "tiff", "tif", "jpx"):
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue
                # ▲▲▲ 追加ここまで ▲▲▲

                try:
                    pil_img = Image.open(io.BytesIO(img_bytes))
                except Exception:
                    # Pillow で開けない特殊フォーマット等はスキップ
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                orig_w, orig_h = pil_img.size

                # --- 実効 DPI からリサイズ比率を算出 ---
                effective_dpi_x = orig_w / (rect_w_pts / 72.0)
                effective_dpi_y = orig_h / (rect_h_pts / 72.0)
                effective_dpi = max(effective_dpi_x, effective_dpi_y)

                if effective_dpi > target_dpi:
                    scale = target_dpi / effective_dpi
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                    pil_img = pil_img.resize((new_w, new_h), resample_filter)
                # 既に target_dpi 以下ならリサイズしない

                # --- フォーマット判定 & 再圧縮 ---
                is_lossless = img_ext in ("png", "bmp", "tiff", "tif", "gif")
                buf = io.BytesIO()

                if is_lossless and not png_to_jpeg:
                    # PNG 維持: リサイズ済み画像を PNG (Deflate) で再保存
                    if pil_img.mode not in ("RGB", "RGBA", "L", "LA"):
                        # パレットモード(P) 等を一般的なモードに変換
                        pil_img = pil_img.convert(
                            "RGBA" if ("A" in pil_img.mode or pil_img.mode == "P") else "RGB"
                        )
                    pil_img.save(buf, format="PNG", optimize=True)
                else:
                    # JPEG 系 or (PNG → JPEG 変換): JPEG で再圧縮
                    if pil_img.mode in ("RGBA", "PA", "LA", "P"):
                        if pil_img.mode == "P":
                            pil_img = pil_img.convert("RGBA")
                        # 透過（アルファ）を持つ場合は白背景で合成
                        if "A" in pil_img.mode:
                            background = Image.new("RGB", pil_img.size, (255, 255, 255))
                            background.paste(pil_img, mask=pil_img.split()[-1])
                            pil_img = background
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    pil_img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)

                new_bytes = buf.getvalue()

                # --- サイズ比較と PDF への反映 ---
                # replace_image() は Width/Height/Filter 等のメタデータも
                # 整合性を保ったまま更新するため、PDF 破損を防げる。
                if len(new_bytes) < orig_size:
                    page.replace_image(xref, stream=new_bytes)
                    compressed_cache[xref] = new_bytes
                    replaced_count += 1
                else:
                    # 圧縮効果がなかった場合は元の画像を維持
                    compressed_cache[xref] = None
                    skipped_count += 1

        # ガベージコレクション（不要オブジェクト除去）＋ Deflate 圧縮で保存
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()

        total_images = replaced_count + skipped_count
        detail = f"一意の画像{total_images}個中{replaced_count}個を再圧縮"
        if png_to_jpeg:
            detail += ", PNG→JPEG変換あり"
        return True, f"PDF非可逆圧縮(PyMuPDF): {os.path.basename(input_path)} → OK ({detail}, DPI={target_dpi}, JPEG品質={jpeg_quality})"
    except Exception as e:
        return False, f"PDF非可逆圧縮失敗: {os.path.basename(input_path)} ({e})"


def compress_pdf_lossless(input_path, output_path, options=None):
    """pikepdf を用いた PDF の構造最適化（可逆）。

    with 文でファイルを開き、例外発生時も確実にハンドルを解放する。

    引数:
    - input_path: 入力 PDF パス
    - output_path: 出力 PDF パス
    - options: dict — 最適化オプション。キーは以下:
        - 'linearize': bool — Web 最適化（Linearize）
        - 'object_streams': bool — オブジェクトストリーム圧縮
        - 'clean_metadata': bool — メタデータ除去（XMP + DocInfo）
        - 'recompress_streams': bool — 既存 Flate ストリームを最高圧縮率で再圧縮
        - 'remove_unreferenced': bool — 孤立リソース（未参照オブジェクト）の削除

    戻り値:
    - (bool, str): 成否とメッセージ
    """
    if options is None:
        options = dict(PDF_LOSSLESS_OPTIONS_DEFAULT)
    try:
        # with 文で開くことで、例外発生時も確実にファイルをクローズする
        with pikepdf.open(input_path) as pdf:

            # 1. 孤立リソースのパージ（未参照オブジェクトの削除）
            if options.get('remove_unreferenced', True):
                pdf.remove_unreferenced_resources()

            # 2. メタデータ除去（PDF ツリーからの直接削除が最も確実）
            if options.get('clean_metadata', False):
                # XMP メタデータの削除
                if '/Metadata' in pdf.Root:
                    del pdf.Root.Metadata
                # 従来の DocInfo の削除
                if '/Info' in pdf.trailer:
                    try:
                        del pdf.trailer['/Info']
                    except Exception:
                        pass

            # 3. オブジェクトストリームモードの判定
            if options.get('object_streams', True):
                osm = pikepdf.ObjectStreamMode.generate
            else:
                osm = pikepdf.ObjectStreamMode.preserve

            # 4. ストリーム再圧縮（CPU を消費するためオプション化）
            do_recompress = options.get('recompress_streams', True)

            # 保存
            pdf.save(
                output_path,
                linearize=options.get('linearize', True),
                object_stream_mode=osm,
                compress_streams=True,              # 非圧縮ストリームの圧縮は常に ON
                recompress_flate=do_recompress,      # 既存 Flate を最高圧縮率で再計算
            )

        # 適用した処理のロギング
        applied = []
        if options.get('linearize'):
            applied.append("Linearize")
        if options.get('object_streams'):
            applied.append("ObjStream圧縮")
        if options.get('clean_metadata'):
            applied.append("メタデータ除去")
        if options.get('recompress_streams'):
            applied.append("Flate再圧縮")
        if options.get('remove_unreferenced'):
            applied.append("孤立リソース削除")
        opts_str = ", ".join(applied) if applied else "なし"
        return True, f"PDF可逆圧縮(pikepdf): {os.path.basename(input_path)} → OK ({opts_str})"
    except Exception as e:
        return False, f"PDF可逆圧縮失敗: {os.path.basename(input_path)} ({e})"

def get_ghostscript_path():
    """OSに応じてGhostscriptの実行パスを取得する。"""
    candidates = ['gswin64c', 'gswin32c', 'gs']
    for cmd in candidates:
        path = shutil.which(cmd)
        if path:
            return path
    return None

def compress_pdf_ghostscript(input_path, output_path, preset="ebook", custom_dpi=None):
    """Ghostscriptを利用してPDFを再蒸留・圧縮する。"""
    gs_exe = get_ghostscript_path()
    if not gs_exe:
        return False, "Ghostscriptが見つかりません。インストールされているか確認してください。"

    cmd = [
        gs_exe,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
    ]

    if preset == "custom" and custom_dpi:
        # カスタム解像度設定（モノクロは文字の可読性を守るため高めに設定）
        cmd.extend([
            "-dColorImageDownsampleType=/Bicubic",
            f"-dColorImageResolution={custom_dpi}",
            "-dGrayImageDownsampleType=/Bicubic",
            f"-dGrayImageResolution={custom_dpi}",
            "-dMonoImageDownsampleType=/Bicubic",
            f"-dMonoImageResolution={custom_dpi * 2}", 
        ])
    else:
        # プリセット設定
        valid_presets = ["screen", "ebook", "printer", "prepress", "default"]
        safe_preset = preset if preset in valid_presets else "ebook"
        cmd.append(f"-dPDFSETTINGS=/{safe_preset}")

    cmd.extend([
        f"-sOutputFile={output_path}",
        input_path
    ])

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        
        if result.returncode == 0 and os.path.exists(output_path):
            orig_size = os.path.getsize(input_path)
            out_size = os.path.getsize(output_path)
            
            # GSの仕様上、元のファイルより大きくなる現象（圧縮太り）を防止
            if out_size >= orig_size:
                shutil.copy2(input_path, output_path)
                return True, f"PDF圧縮(GS): {os.path.basename(input_path)} → 圧縮効果なし（元ファイルを維持）"
                
            mode_str = f"custom_dpi={custom_dpi}" if preset == "custom" else f"preset={preset}"
            return True, f"PDF圧縮(GS): {os.path.basename(input_path)} → OK ({mode_str})"
        else:
            return False, f"PDF圧縮(GS) エラー: {result.stderr.strip()}"
            
    except Exception as e:
        return False, f"PDF圧縮(GS) 実行失敗: {e}"


def compress_pdf_native(input_path, output_path, mode='both',
                 target_dpi=PDF_LOSSY_DPI_DEFAULT,
                 jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
                 png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
                 lossless_options=None):
    """ネイティブ（PyMuPDF + pikepdf）PDF 圧縮の統合関数。

    モードに応じて非可逆 / 可逆 / 両方を実行する。

    引数:
    - mode: 'lossy' | 'lossless' | 'both'
    - target_dpi: 非可逆時の DPI
    - jpeg_quality: 非可逆時の JPEG 品質
    - png_to_jpeg: PNG→JPEG 変換するか
    - lossless_options: 可逆オプション dict

    戻り値:
    - (bool, str): 成否とメッセージ
    """
    if mode not in PDF_COMPRESS_MODES:
        mode = 'both'

    if mode == 'lossy':
        return compress_pdf_lossy(input_path, output_path, target_dpi, jpeg_quality, png_to_jpeg)
    elif mode == 'lossless':
        return compress_pdf_lossless(input_path, output_path, lossless_options)
    else:
        # both: lossy → lossless の 2 段パイプライン
        # まず lossy で中間ファイルを作成
        tmp_path = output_path + ".tmp_lossy.pdf"
        try:
            ok_lossy, msg_lossy = compress_pdf_lossy(input_path, tmp_path, target_dpi, jpeg_quality, png_to_jpeg)
            if not ok_lossy:
                # lossy 失敗時は入力をそのまま lossless に通す
                ok_ll, msg_ll = compress_pdf_lossless(input_path, output_path, lossless_options)
                return ok_ll, f"{msg_lossy} / {msg_ll}"

            ok_ll, msg_ll = compress_pdf_lossless(tmp_path, output_path, lossless_options)
            if not ok_ll:
                # lossless 失敗時は lossy 結果をそのまま使う
                shutil.copy2(tmp_path, output_path)
                return True, f"{msg_lossy} / {msg_ll}（可逆段失敗、非可逆結果を採用）"

            return True, f"{msg_lossy} / {msg_ll}"
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass


def compress_pdf_gs(input_path, output_path, preset=GS_DEFAULT_PRESET,
                    custom_dpi=None, lossless_options=None):
    """GhostScript による PDF 再蒸留 + オプションで pikepdf 構造最適化。

    GhostScript が未インストールの場合はエラーを返す。
    lossless_options が指定されている場合は GS 出力に対して compress_pdf_lossless() を
    直列適用する（GS → pikepdf の 2 段パイプライン）。

    引数:
    - input_path: 入力 PDF パス
    - output_path: 出力 PDF パス
    - preset: GS プリセット名（'screen'/'ebook'/'printer'/'prepress'/'default'/'custom'）
    - custom_dpi: preset='custom' 時のカスタム DPI（int or None）
    - lossless_options: pikepdf 可逆オプション dict。None の場合は GS のみ実行

    戻り値:
    - (bool, str): 成否とメッセージ
    """
    if lossless_options:
        # GS → lossless の 2 段パイプライン
        tmp_path = output_path + ".tmp_gs.pdf"
        try:
            ok_gs, msg_gs = compress_pdf_ghostscript(input_path, tmp_path, preset, custom_dpi)
            if not ok_gs:
                return False, msg_gs

            ok_ll, msg_ll = compress_pdf_lossless(tmp_path, output_path, lossless_options)
            if not ok_ll:
                # 可逆段失敗時は GS 結果をそのまま使う
                shutil.copy2(tmp_path, output_path)
                return True, f"{msg_gs} / {msg_ll}（可逆段失敗、GS結果を採用）"

            return True, f"{msg_gs} / {msg_ll}"
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
    else:
        return compress_pdf_ghostscript(input_path, output_path, preset, custom_dpi)


def compress_image_pillow(input_path, output_path, quality, resize_cfg=None):
    """Pillow を用いて JPEG/PNG を品質指定で保存。必要に応じてリサイズも行う。

    resize_cfg:
    - { 'enabled': True, 'mode': 'manual', 'width': w, 'height': h, 'keep_aspect': bool }
    - { 'enabled': True, 'mode': 'long_edge', 'long_edge': px, 'keep_aspect': True }
    """
    try:
        img = Image.open(input_path)
        if resize_cfg and resize_cfg.get('enabled'):
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
            else:
                w = int(resize_cfg.get('width', 0) or 0)
                h = int(resize_cfg.get('height', 0) or 0)
                keep = bool(resize_cfg.get('keep_aspect', True))
                if w > 0 or h > 0:
                    if keep:
                        if w > 0 and h > 0:
                            # 幅と高さの両方指定時は小さい方に合わせる
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
        img.save(output_path, optimize=True, quality=quality)
        msg_extra = ""
        if resize_cfg and resize_cfg.get('enabled'):
            msg_extra = f", resize={img.size[0]}x{img.size[1]}"
        return True, f"画像圧縮(Pillow): {os.path.basename(input_path)} → OK (quality={quality}{msg_extra})"
    except Exception as e:
        return False, f"画像失敗: {os.path.basename(input_path)} ({e})"


def compress_png_pngquant(input_path, output_path, quality_min, quality_max, speed=3, resize_cfg=None):
    """pngquant が利用可能ならパレット量子化で高圧縮、無ければ Pillow にフォールバック。"""
    pngquant_exe = shutil.which("pngquant")
    if not pngquant_exe:
        return compress_image_pillow(input_path, output_path, quality_max,resize_cfg=resize_cfg)
    try:
        qarg = f"{quality_min}-{quality_max}"
        src_path = input_path
        tmp_path = None
        resized_wh = None
        if resize_cfg and resize_cfg.get('enabled'):
            try:
                tmp_path = output_path + ".tmp_resize.png"
                img = Image.open(input_path)
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
                img.save(tmp_path, optimize=True)
                src_path = tmp_path
            except Exception:
                src_path = input_path

        cmd = [
            pngquant_exe,
            f"--quality={qarg}",
            f"--speed={speed}",
            "--force",
            "--output", output_path,
            src_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0 and os.path.exists(output_path):
            msg = f"PNG圧縮(pngquant): {os.path.basename(input_path)} → OK (quality={qarg})"
            if resized_wh and resize_cfg and resize_cfg.get('enabled'):
                msg += f", resize={resized_wh[0]}x{resized_wh[1]}"
            return True, msg
        else:
            return compress_image_pillow(input_path, output_path, quality_max, resize_cfg=resize_cfg)
    except Exception:
        return compress_image_pillow(input_path, output_path, quality_max, resize_cfg=resize_cfg)
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def process_single_file(args):
    """1 ファイル処理のユーティリティ。拡張子で処理系を自動選択。

    args タプル構造:
    (inpath, outpath, ext,
     pdf_engine, pdf_mode, pdf_dpi, pdf_jpeg_quality, pdf_png_to_jpeg, pdf_lossless_options,
     gs_preset, gs_custom_dpi,
     jpg_quality, png_quality, use_pngquant, resize_cfg)

    pdf_engine: 'native' (PyMuPDF+pikepdf) or 'gs' (GhostScript)
    """
    (inpath, outpath, ext,
     pdf_engine, pdf_mode, pdf_dpi, pdf_jpeg_quality, pdf_png_to_jpeg, pdf_lossless_options,
     gs_preset, gs_custom_dpi,
     jpg_quality, png_quality, use_pngquant, resize_cfg) = args
    try:
        orig_size = os.path.getsize(inpath)
    except Exception:
        orig_size = 0
    outdir = os.path.dirname(outpath)
    if not os.path.exists(outdir):
        os.makedirs(outdir, exist_ok=True)
    processed = False
    if ext == "pdf":
        processed = True
        if pdf_engine == 'gs':
            _, base_msg = compress_pdf_gs(inpath, outpath,
                                          preset=gs_preset, custom_dpi=gs_custom_dpi,
                                          lossless_options=pdf_lossless_options)
        else:
            _, base_msg = compress_pdf_native(inpath, outpath, mode=pdf_mode,
                                              target_dpi=pdf_dpi, jpeg_quality=pdf_jpeg_quality,
                                              png_to_jpeg=pdf_png_to_jpeg,
                                              lossless_options=pdf_lossless_options)
    elif ext in ["jpg", "jpeg"]:
        processed = True
        _, base_msg = compress_image_pillow(inpath, outpath, jpg_quality, resize_cfg=resize_cfg)
    elif ext == "png":
        processed = True
        if use_pngquant:
            qmin = max(0, png_quality - 20)
            qmax = png_quality
            _, base_msg = compress_png_pngquant(inpath, outpath, qmin, qmax, speed=3, resize_cfg=resize_cfg)
        else:
            _, base_msg = compress_image_pillow(inpath, outpath, png_quality, resize_cfg=resize_cfg)
    else:
        try:
            # shutil.copy2(inpath, outpath) # コピーしない仕様に変更
            # 未対応拡張子を持つファイルは入力フォルダにそのまま残す
            base_msg = f"未対応: {os.path.basename(inpath)}（Left in the input folder）"
        except Exception as e:
            base_msg = f"未対応ファイル失敗: {os.path.basename(inpath)} ({e})"
    try:
        out_size = os.path.getsize(outpath) if os.path.exists(outpath) else orig_size
    except Exception:
        out_size = orig_size
    saved_size = orig_size - out_size
    saved_pct = (saved_size / orig_size * 100) if orig_size > 0 else 0.0
    size_info = f" | Before: {human_readable(orig_size)} → After: {human_readable(out_size)}"
    if saved_size > 0:
        size_info += f" (削減: {human_readable(saved_size)}, -{saved_pct:.1f}%)"
    elif saved_size < 0:
        size_info += f" (増加: {human_readable(-saved_size)}, +{-saved_pct:.1f}%)"
    else:
        size_info += " (変化なし)"
    msg = base_msg + size_info
    return msg, orig_size, out_size, processed


def compress_folder(input_dir, output_dir, jpg_quality, png_quality, use_pngquant,
                    log_func, progress_func, stats_func,
                    pdf_engine='native',
                    pdf_mode='both', pdf_dpi=PDF_LOSSY_DPI_DEFAULT,
                    pdf_jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
                    pdf_png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
                    pdf_lossless_options=None,
                    gs_preset=GS_DEFAULT_PRESET, gs_custom_dpi=None,
                    resize_enabled=False, resize_width=0, resize_height=0,
                    csv_enable=True, csv_path=None, extract_zip=False):
    """フォルダ全体を並列処理で圧縮。必要なら ZIP 展開と併用可。

    pdf_engine: 'native' (PyMuPDF+pikepdf) or 'gs' (GhostScript+pikepdf)
    """
    from backend.orchestrator.job_runner import run_compression_job

    return run_compression_job(
        input_dir=input_dir,
        output_dir=output_dir,
        jpg_quality=jpg_quality,
        png_quality=png_quality,
        use_pngquant=use_pngquant,
        log_func=log_func,
        progress_func=progress_func,
        stats_func=stats_func,
        pdf_engine=pdf_engine,
        pdf_mode=pdf_mode,
        pdf_dpi=pdf_dpi,
        pdf_jpeg_quality=pdf_jpeg_quality,
        pdf_png_to_jpeg=pdf_png_to_jpeg,
        pdf_lossless_options=pdf_lossless_options,
        gs_preset=gs_preset,
        gs_custom_dpi=gs_custom_dpi,
        resize_enabled=resize_enabled,
        resize_width=resize_width,
        resize_height=resize_height,
        csv_enable=csv_enable,
        csv_path=csv_path,
        extract_zip=extract_zip,
    )


def count_target_files(target_dir, target_extensions):
    """指定拡張子に一致するファイル数を数える。フォルダが無い場合は 0。"""
    count = 0
    if not target_dir or not os.path.exists(target_dir):
        return 0
    try:
        for root, _, files in os.walk(target_dir):
            for name in files:
                _, ext = os.path.splitext(name)
                if ext.lower() in target_extensions:
                    count += 1
    except Exception:
        pass
    return count


def cleanup_folder(target_dir, log_func, folder_type="フォルダ", target_extensions=None):
    """指定フォルダ配下の対象拡張子ファイルを削除し、空フォルダも除去する。"""
    if not target_dir or not os.path.exists(target_dir):
        log_func(f"{folder_type}が未指定、または存在しません")
        return
    if target_extensions is None:
        target_extensions = set()
    try:
        deleted_count = 0
        skipped_count = 0
        for root, dirs, files in os.walk(target_dir, topdown=False):
            for name in files:
                file_path = os.path.join(root, name)
                _, ext = os.path.splitext(name)
                ext_lower = ext.lower()
                if not target_extensions or ext_lower in target_extensions:
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        log_func(f"削除: {os.path.relpath(file_path, target_dir)}")
                    except Exception as e:
                        log_func(f"削除失敗: {os.path.relpath(file_path, target_dir)} - {e}")
                else:
                    skipped_count += 1
            for name in dirs:
                dir_path = os.path.join(root, name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        log_func(f"空フォルダ削除: {os.path.relpath(dir_path, target_dir)}")
                except Exception:
                    pass
        if target_extensions:
            exts_str = ', '.join(sorted(target_extensions))
            log_func(f"{folder_type}のクリーンアップが完了しました（削除: {deleted_count}ファイル、スキップ: {skipped_count}ファイル、対象拡張子: {exts_str}）")
        else:
            log_func(f"{folder_type}のクリーンアップが完了しました（削除: {deleted_count}ファイル）")
    except Exception as e:
        log_func(f"{folder_type}クリーンアップ失敗: {e}")

# ------------- 補助関数群 -------------

# 使用しないことにしたのでコメントアウト
# def can_be_converted_to_float(_str: str) -> bool:
#     """文字列が float に変換可能か判定する補助関数。"""
#     try:
#         float(_str)
#         return True
#     except ValueError:
#         return False