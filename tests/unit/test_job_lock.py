from __future__ import annotations

"""出力フォルダ排他ロック（job_lock）の unit test。"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from backend.orchestrator import job_lock
from backend.orchestrator.job_lock import OutputLockError, acquire_output_lock
from backend.settings import APP_WORK_DIR_NAME, JOB_LOCK_FILENAME

pytestmark = pytest.mark.unit


def test_second_acquire_is_rejected_until_released(tmp_path: Path) -> None:
    first = acquire_output_lock(tmp_path)

    with pytest.raises(OutputLockError):
        acquire_output_lock(tmp_path)

    first.release()
    with acquire_output_lock(tmp_path) as again:
        assert again.held


def test_lock_file_is_kept_after_release(tmp_path: Path) -> None:
    lock = acquire_output_lock(tmp_path)
    lock.release()
    lock.release()  # 二重解放は無害

    assert (tmp_path / APP_WORK_DIR_NAME / JOB_LOCK_FILENAME).exists()
    assert not lock.held


def test_different_output_roots_do_not_conflict(tmp_path: Path) -> None:
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()

    with acquire_output_lock(a), acquire_output_lock(b):
        pass


def test_lock_is_released_when_owner_process_dies(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        import sys, time
        from backend.orchestrator.job_lock import acquire_output_lock
        lock = acquire_output_lock(sys.argv[1])
        print('ready', flush=True)
        time.sleep(60)
        """
    )
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.Popen(
        [sys.executable, '-c', script, str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=repo_root,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == 'ready'
        with pytest.raises(OutputLockError):
            acquire_output_lock(tmp_path)
    finally:
        proc.kill()
        proc.wait()

    with acquire_output_lock(tmp_path):
        pass


@pytest.mark.skipif(sys.platform != 'win32', reason='hidden attribute is Windows-only')
def test_work_dir_is_hidden_on_windows(tmp_path: Path) -> None:
    import ctypes

    work_dir = job_lock.ensure_app_work_dir(tmp_path)

    assert ctypes.windll.kernel32.GetFileAttributesW(str(work_dir)) & 0x2


@pytest.mark.skipif(sys.platform != 'win32', reason='hidden attribute is Windows-only')
def test_work_dir_creation_continues_when_hiding_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    def broken(*_args: object) -> None:
        raise OSError('no attributes')

    monkeypatch.setattr(ctypes.windll.kernel32, 'SetFileAttributesW', broken)

    assert job_lock.ensure_app_work_dir(tmp_path).is_dir()
