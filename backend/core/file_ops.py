from __future__ import annotations

from pathlib import Path


def count_target_files(target_dir, target_extensions):
    """指定拡張子に一致するファイル数を数える。フォルダが無い場合は 0。"""
    count = 0
    if not target_dir:
        return 0
    base_dir = Path(target_dir)
    if not base_dir.exists():
        return 0
    try:
        for file_path in base_dir.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in target_extensions:
                count += 1
    except Exception:
        pass
    return count


def cleanup_folder(target_dir, log_func, folder_type="フォルダ", target_extensions=None):
    """指定フォルダ配下の対象拡張子ファイルを削除し、空フォルダも除去する。"""
    if not target_dir:
        log_func(f"{folder_type}が未指定、または存在しません")
        return

    base_dir = Path(target_dir)
    if not base_dir.exists():
        log_func(f"{folder_type}が未指定、または存在しません")
        return
    if target_extensions is None:
        target_extensions = set()

    def _rel(path_obj: Path) -> str:
        try:
            return str(path_obj.relative_to(base_dir))
        except Exception:
            return path_obj.name

    try:
        deleted_count = 0
        skipped_count = 0
        for file_path in base_dir.rglob('*'):
            if not file_path.is_file():
                continue

            ext_lower = file_path.suffix.lower()
            if not target_extensions or ext_lower in target_extensions:
                try:
                    file_path.unlink()
                    deleted_count += 1
                    log_func(f"削除: {_rel(file_path)}")
                except Exception as e:
                    log_func(f"削除失敗: {_rel(file_path)} - {e}")
            else:
                skipped_count += 1

        dirs = [p for p in base_dir.rglob('*') if p.is_dir()]
        dirs.sort(key=lambda p: len(p.parts), reverse=True)
        for dir_path in dirs:
            try:
                if not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    log_func(f"空フォルダ削除: {_rel(dir_path)}")
            except Exception:
                pass

        if target_extensions:
            exts_str = ', '.join(sorted(target_extensions))
            log_func(f"{folder_type}のクリーンアップが完了しました（削除: {deleted_count}ファイル、スキップ: {skipped_count}ファイル、対象拡張子: {exts_str}）")
        else:
            log_func(f"{folder_type}のクリーンアップが完了しました（削除: {deleted_count}ファイル）")
    except Exception as e:
        log_func(f"{folder_type}クリーンアップ失敗: {e}")
