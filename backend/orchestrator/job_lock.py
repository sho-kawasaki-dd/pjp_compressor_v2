from __future__ import annotations

"""出力フォルダのOS排他ロックと、アプリ専用作業フォルダ（`.pjp_work/`）の管理。

全圧縮ジョブと出力クリーンアップが `.pjp_work/job.lock` を共有し、同じ出力フォルダを
同時に操作しないようにする。PID の記録ではなく OS のファイルロックで排他するため、
プロセスが異常終了してもロックは OS が解放する。ロックファイルは解放後も削除しない
（削除・再作成で排他が分断されるのを避ける）。
"""

import os
import sys
from pathlib import Path
from types import TracebackType

from backend.settings import APP_WORK_DIR_NAME, JOB_LOCK_FILENAME

_FILE_ATTRIBUTE_HIDDEN = 0x2

if sys.platform == 'win32':
    import msvcrt
else:  # pragma: no cover - 本アプリは Windows 前提だが、開発環境向けに fcntl へ退避する
    import fcntl


class OutputLockError(RuntimeError):
    """出力フォルダが別のジョブ・クリーンアップで使用中のときに送出する。"""


def _hide_path(path: Path) -> None:
    """Windows では隠し属性を付与する。失敗は無視してよい。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(path), _FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def ensure_app_work_dir(output_root: str | Path) -> Path:
    """出力ルート直下に `.pjp_work/` を作成（隠し属性付与）して返す。"""
    work_dir = Path(output_root) / APP_WORK_DIR_NAME
    if work_dir.is_symlink() or os.path.isjunction(work_dir):
        raise OSError(f'work directory is a link: {work_dir}')
    created = not work_dir.exists()
    work_dir.mkdir(parents=True, exist_ok=True)
    if work_dir.is_symlink() or os.path.isjunction(work_dir):
        raise OSError(f'work directory is a link: {work_dir}')
    if created:
        _hide_path(work_dir)
    return work_dir


class OutputLock:
    """取得済みの出力排他ロック。`release()` またはコンテキスト終了で解放する。"""

    def __init__(self, path: Path, handle) -> None:
        self.path = path
        self._handle = handle

    @property
    def held(self) -> bool:
        return self._handle is not None

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == 'win32':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    def __enter__(self) -> 'OutputLock':
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def acquire_output_lock(output_root: str | Path) -> OutputLock:
    """出力ルートの `.pjp_work/job.lock` を非ブロッキングで取得する。

    取得できない場合（別ジョブ・別アプリインスタンスが使用中）は `OutputLockError`。
    """
    work_dir = ensure_app_work_dir(output_root)
    lock_path = work_dir / JOB_LOCK_FILENAME
    handle = open(lock_path, 'a+b')
    try:
        if sys.platform == 'win32':
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise OutputLockError(f'output folder is in use: {os.fspath(output_root)}') from exc
    return OutputLock(lock_path, handle)
