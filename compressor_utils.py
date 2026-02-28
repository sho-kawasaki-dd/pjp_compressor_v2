#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_utils.py

PDF と画像（JPG/PNG）の圧縮、およびフォルダ操作（列挙・クリーンアップ・CSV ログ）を
提供するモジュール。GUI から独立しており、スクリプトやテストから再利用可能。

設計方針:
- 外部ツールの検出（Ghostscript, pngquant）は実行時に都度チェックし、
    未導入でも例外を致命化しない（可能な範囲でフォールバック）。
- リサイズは Pillow ベースで、長辺指定と手動（幅/高さ）をサポート。
- 並列処理（ThreadPoolExecutor）で大量ファイルを高速化。
- 進捗更新・ログ出力・統計更新はコールバック関数を受け取り、
    呼び出し側（GUI）に委譲する。

主な提供関数:
- extract_zip_archives(): 指定フォルダ配下の ZIP を再帰展開。
- compress_pdf_ghostscript(): Ghostscript を用いて PDF を圧縮。
- compress_pdf_pypdf(): pypdf/PyPDF2 を用いて簡易圧縮（代替）。
- compress_image_pillow(): JPEG/PNG を Pillow で品質調整＆リサイズ保存。
- compress_png_pngquant(): pngquant があればパレット量子化、なければ Pillow。
- process_single_file(): 1 ファイル単位の圧縮処理（拡張子に応じて分岐）。
- compress_folder(): フォルダ内の対象ファイルを並列で処理し、CSV ログも出力。
- count_target_files(): 指定拡張子の件数を数える（クリーンアップ事前確認用）。
- cleanup_folder(): 指定拡張子のファイルと空フォルダを削除。
"""
import os
import subprocess
import shutil
import csv
import zipfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
from PIL import Image
from configs import GS_COMMAND, GS_OPTIONS
try:
    from pypdf import PdfReader, PdfWriter
    PYPDF_AVAILABLE = True
except Exception:
    try:
        from PyPDF2 import PdfReader, PdfWriter
        PYPDF_AVAILABLE = True
    except Exception:
        PYPDF_AVAILABLE = False

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


def compress_pdf_ghostscript(input_path, output_path, quality_preset, pdf_quality=None):
    """Ghostscript を用いて PDF を圧縮する。

    引数:
    - input_path: 入力 PDF パス
    - output_path: 出力 PDF パス
    - quality_preset: GS の `-dPDFSETTINGS` に渡すプリセット文字列
    - pdf_quality: 任意の DPI 相当スライダー値（0-100）。指定時は画像解像度を調整。

    戻り値:
    - (bool, str): 成否とメッセージ
    """
    try:
        qpreset = quality_preset if quality_preset in GS_OPTIONS else '/default'

        cmd = [
            GS_COMMAND,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={qpreset}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={output_path}",
            input_path
        ]
        if isinstance(pdf_quality, int):
            dpi = int(72 + (max(0, min(100, pdf_quality)) / 100.0) * 228)
            cmd.insert(6, f"-dColorImageResolution={dpi}")
            cmd.insert(7, f"-dGrayImageResolution={dpi}")
            cmd.insert(8, f"-dMonoImageResolution={dpi}")

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='replace')
        if result.returncode == 0 and os.path.exists(output_path):
            return True, f"PDF圧縮(GS): {os.path.basename(input_path)} → OK（プリセット:{qpreset}）"
        else:
            return False, f"PDF失敗(GS): {os.path.basename(input_path)}（{result.stderr[:300]}）"
    except Exception as e:
        return False, f"PDF失敗(GS): {os.path.basename(input_path)}（{e}）"


def compress_pdf_pypdf(input_path, output_path):
    """pypdf/PyPDF2 を用いた PDF の簡易圧縮。

    注意: 画像再サンプリング等は行わず、`compress_content_streams()` による軽減のみ。
    Ghostscript に比べて圧縮率は低いが、依存性の少ない代替手段。
    """
    if not PYPDF_AVAILABLE:
        return False, f"PDF失敗(pypdf): {os.path.basename(input_path)}（pypdf 未インストール）"
    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for page in reader.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass
            writer.add_page(page)
        writer.add_metadata({})
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        if os.path.exists(output_path):
            return True, f"PDF圧縮(pypdf): {os.path.basename(input_path)} → OK"
        else:
            return False, f"PDF失敗(pypdf): {os.path.basename(input_path)}（出力ファイル作成失敗）"
    except Exception as e:
        return False, f"PDF失敗(pypdf): {os.path.basename(input_path)} ({e})"


def compress_pdf(input_path, output_path, quality_preset, engine, pdf_quality=None):
    """PDF 圧縮の統合関数。選択エンジンに応じて適切な処理を呼び分ける。"""
    gs_available = shutil.which(GS_COMMAND) is not None
    if engine == 'ghostscript':
        if gs_available:
            return compress_pdf_ghostscript(input_path, output_path, quality_preset, pdf_quality)
        else:
            return False, f"PDF失敗(GS未検出): {os.path.basename(input_path)}"
    elif engine == 'pypdf':
        if PYPDF_AVAILABLE:
            return compress_pdf_pypdf(input_path, output_path)
        else:
            return False, f"PDF失敗(pypdf未インストール): {os.path.basename(input_path)}"
    else:
        if gs_available:
            return compress_pdf_ghostscript(input_path, output_path, quality_preset, pdf_quality)
        elif PYPDF_AVAILABLE:
            return compress_pdf_pypdf(input_path, output_path)
        else:
            return False, f"PDF失敗: 利用可能なPDF圧縮ツールがありません ({os.path.basename(input_path)})"


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
                    img = img.resize((new_w, new_h), Image.LANCZOS)
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
                    img = img.resize((new_w, new_h), Image.LANCZOS)
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
        return compress_image_pillow(input_path, output_path, quality_max)
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
                        img = img.resize((new_w, new_h), Image.LANCZOS)
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
                        img = img.resize((new_w, new_h), Image.LANCZOS)
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
    """1 ファイル処理のユーティリティ。拡張子で処理系を自動選択。"""
    inpath, outpath, ext, gs_quality, jpg_quality, png_quality, use_pngquant, pdf_engine, pdf_quality, resize_cfg = args
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
        _, base_msg = compress_pdf(inpath, outpath, gs_quality, pdf_engine, pdf_quality)
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


def compress_folder(input_dir, output_dir, gs_quality, jpg_quality, png_quality, use_pngquant, pdf_engine,
                    log_func, progress_func, stats_func, pdf_quality=None, pdf_quality_enabled=False,
                    resize_enabled=False, resize_width=0, resize_height=0, csv_enable=True, csv_path=None,
                    extract_zip=False):
    """フォルダ全体を並列処理で圧縮。必要なら ZIP 展開と併用可。"""
    if extract_zip:
        log_func("ZIPファイルを展開してから圧縮を行います…")
        extracted_cnt, failed_cnt = extract_zip_archives(input_dir, log_func)
        if extracted_cnt == 0 and failed_cnt == 0:
            log_func("ZIPファイルは検出されませんでした。")
        elif failed_cnt > 0:
            log_func(f"ZIP展開結果: 成功 {extracted_cnt} 件 / 失敗 {failed_cnt} 件")
        else:
            log_func(f"ZIP展開結果: {extracted_cnt} 件の ZIP を展開しました。")
    total_files = []
    for root, _, files in os.walk(input_dir):
        for fname in files:
            total_files.append((root, fname))
    total_len = len(total_files)
    if total_len == 0:
        log_func("入力フォルダにファイルが見つかりませんでした。")
        log_func("完了！")
        progress_func(1, 1)
        stats_func(0, 0, 0, 0.0)
        return
    tasks = []
    for root, fname in total_files:
        inpath = os.path.join(root, fname)
        ext = fname.lower().split('.')[-1]
        rel_dir = os.path.relpath(root, input_dir)
        outdir = os.path.join(output_dir, rel_dir)
        outpath = os.path.join(outdir, fname)
        qval = pdf_quality if pdf_quality_enabled else None
        rcfg = None
        if isinstance(resize_enabled, dict):
            rcfg = resize_enabled
        else:
            if resize_enabled and (resize_width > 0 or resize_height > 0):
                rcfg = { 'enabled': True, 'mode': 'manual', 'width': int(resize_width), 'height': int(resize_height), 'keep_aspect': True }
        tasks.append((inpath, outpath, ext, gs_quality, jpg_quality, png_quality, use_pngquant, pdf_engine, qval, rcfg))
    max_workers = max(4, multiprocessing.cpu_count())
    log_func(f"並列処理開始（ワーカー数: {max_workers}、ファイル数: {total_len}）")
    csv_file = None
    csv_writer = None
    if csv_enable:
        try:
            if not csv_path:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                csv_path = os.path.join(output_dir, f"compression_log_{ts}.csv")
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            csv_file = open(csv_path, 'w', newline='', encoding='utf-8')
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(['timestamp','input_path','output_path','ext','action','orig_size','out_size','saved_bytes','saved_pct','notes'])
            log_func(f"CSVログ出力: {csv_path}")
        except Exception as e:
            log_func(f"CSVログの作成に失敗しました: {e}")
            csv_file = None
            csv_writer = None
    cnt = 0
    orig_total = 0
    out_total = 0
    processed_files = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_file, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                msg, orig_size, out_size, processed_flag = future.result()
                if processed_flag:
                    orig_total += orig_size
                    out_total += out_size
                    processed_files += 1
                cnt += 1
                log_func(msg)
                try:
                    if csv_writer:
                        action = msg.split(' | ')[0]
                        saved = orig_size - out_size
                        saved_pct = (saved / orig_size * 100) if orig_size > 0 else 0.0
                        timestamp = datetime.now().isoformat()
                        task = futures[future]
                        inpath_task = task[0]
                        outpath_task = task[1]
                        ext_task = task[2]
                        csv_writer.writerow([timestamp, os.path.relpath(inpath_task, input_dir), os.path.relpath(outpath_task, output_dir), ext_task, action, orig_size, out_size, saved, f"{saved_pct:.1f}", ''])
                except Exception:
                    pass
                progress_func(cnt, total_len)
            except Exception as e:
                log_func(f"処理中にエラー発生: {e}")
                cnt += 1
                progress_func(cnt, total_len)
    try:
        if csv_file:
            csv_file.close()
    except Exception:
        pass
    saved = orig_total - out_total
    saved_pct = (saved / orig_total * 100) if orig_total > 0 else 0.0
    log_func("完了！")
    log_func(f"統計（圧縮対象 {processed_files} 件）: 元合計={human_readable(orig_total)}, 出力合計={human_readable(out_total)}, 削減={human_readable(saved)} ({saved_pct:.1f}%)")
    stats_func(orig_total, out_total, saved, saved_pct)


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