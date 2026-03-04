from __future__ import annotations

import os


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
