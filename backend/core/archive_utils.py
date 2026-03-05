from __future__ import annotations

import zipfile
from pathlib import Path


def extract_zip_archives(target_dir, log_func=None, max_cycles=25):
    """入力フォルダ配下の ZIP を再帰的に展開する。無限ループ防止のため複数対策を実施。"""
    if not target_dir:
        return 0, 0
    base_dir = Path(target_dir)
    if not base_dir.is_dir():
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
            for zip_path in base_dir.rglob('*.zip'):
                if not zip_path.is_file():
                    continue
                abs_path = str(zip_path.resolve())
                if abs_path in processed:
                    continue
                processed.add(abs_path)
                try:
                    rel_zip = str(zip_path.relative_to(base_dir))
                except Exception:
                    rel_zip = zip_path.name
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        member_count = len(zip_ref.infolist())
                        zip_ref.extractall(zip_path.parent)
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
