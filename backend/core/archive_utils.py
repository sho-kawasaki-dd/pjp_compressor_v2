from __future__ import annotations

import os
import zipfile


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
