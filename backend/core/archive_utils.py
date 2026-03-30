from __future__ import annotations

"""ZIP 展開まわりの補助処理をまとめる。

圧縮ジョブ本体は「ZIP を入力としてどう扱うか」だけを判断し、実際の再帰展開と
循環防止はこのモジュールに閉じ込める。
"""

import zipfile
from pathlib import Path, PurePosixPath


MAX_ZIP_MEMBER_COUNT = 10000
MAX_ZIP_TOTAL_UNCOMPRESSED_SIZE = 1_000_000_000


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    """UNIX mode を持つ ZIP member が symlink かを判定する。"""
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def _validate_zip_member_name(member_name: str) -> tuple[bool, str | None]:
    """ZIP member 名が展開先ディレクトリを脱出しないか検査する。"""
    normalized = member_name.replace('\\', '/')
    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute():
        return False, 'absolute_path'
    parts = [part for part in pure_path.parts if part not in ('', '.')]
    if not parts:
        return True, None
    if any(part == '..' for part in parts):
        return False, 'path_traversal'
    if ':' in parts[0]:
        return False, 'drive_path'
    return True, None


def _collect_safe_zip_members(zip_ref: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """展開可能な ZIP member のみを返し、危険な内容は例外化する。"""
    infos = zip_ref.infolist()
    if len(infos) > MAX_ZIP_MEMBER_COUNT:
        raise ValueError(f'ZIP member 数が上限({MAX_ZIP_MEMBER_COUNT})を超えています')

    total_uncompressed = 0
    safe_members: list[zipfile.ZipInfo] = []
    for info in infos:
        total_uncompressed += max(0, info.file_size)
        if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_SIZE:
            raise ValueError(f'ZIP 展開サイズが上限({MAX_ZIP_TOTAL_UNCOMPRESSED_SIZE})を超えています')
        if _is_zip_symlink(info):
            raise ValueError(f'危険な ZIP member を検出しました: {info.filename} (symlink)')
        is_safe, reason = _validate_zip_member_name(info.filename)
        if not is_safe:
            raise ValueError(f'危険な ZIP member を検出しました: {info.filename} ({reason})')
        safe_members.append(info)
    return safe_members


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
            # 前サイクルで展開された ZIP が新たに現れる可能性があるため、毎回 rglob し直す。
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
                        safe_members = _collect_safe_zip_members(zip_ref)
                        member_count = len(safe_members)
                        # 元 ZIP の隣へ展開することで、後段の相対パス計算を単純に保つ。
                        zip_ref.extractall(zip_path.parent, members=safe_members)
                    extracted_total += 1
                    new_zip_handled = True
                    log(f"ZIP展開: {rel_zip}（展開ファイル数: {member_count}、サイクル: {cycle}）")
                except Exception as exc:
                    failed_total += 1
                    log(f"ZIP展開失敗: {rel_zip} ({exc})")
            if not new_zip_handled:
                # 新規 ZIP が無くなった時点で完了とみなし、不要な探索を打ち切る。
                break
        else:
            log(f"ZIP展開サイクルが上限({max_cycles})に到達しました。循環参照の可能性があります。")
    except Exception as exc:
        log(f"ZIP展開処理全体でエラー: {exc}")
    return extracted_total, failed_total
