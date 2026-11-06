from __future__ import annotations

"""出力排他下の作業領域と、停止安全な一時ファイル配置。"""

import os
import shutil
import uuid
from contextlib import ExitStack
from pathlib import Path

from backend.contracts import JobControl
from backend.core.subprocess_utils import sanitize_subprocess_error
from backend.settings import (
    APP_WORK_DIR_NAME,
    VIDEO_COPY_CHUNK_BYTES,
    VIDEO_TEMP_PREFIX,
    VIDEO_WORK_OWNER_MARKER,
)
from shared.locale_catalog import translate


class JobCancelled(Exception):
    """ファイルの配置前に停止要求を受けた。"""


def temp_path(temp_dir: Path, suffix: str) -> Path:
    return temp_dir / f'{VIDEO_TEMP_PREFIX}{uuid.uuid4().hex}{suffix}'


def publish(temp_file: Path, dest: Path, job_control: JobControl) -> None:
    """停止の受理と正式配置を同じロックで直列化する。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with job_control.launch_lock:
        if job_control.is_cancelled:
            raise JobCancelled()
        temp_file.replace(dest)


def copy_with_cancel(
    src: Path,
    dest: Path,
    job_control: JobControl,
    *,
    chunk_size: int = VIDEO_COPY_CHUNK_BYTES,
) -> None:
    with ExitStack() as handles:
        with job_control.launch_lock:
            if job_control.is_cancelled:
                raise JobCancelled()
            fin = handles.enter_context(open(src, 'rb'))
            fout = handles.enter_context(open(dest, 'wb'))
        while True:
            if job_control.is_cancelled:
                raise JobCancelled()
            chunk = fin.read(chunk_size)
            if not chunk:
                break
            fout.write(chunk)
    shutil.copystat(src, dest)


def remove_temps(paths: list[Path], log_language: str, *, message_key: str) -> list[str]:
    failures: list[str] = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            detail = sanitize_subprocess_error(str(exc), path)
            failures.append(translate(log_language, message_key, detail=f'{path.name}: {detail}'))
    return failures


def place_original_copy(
    inpath: str | Path,
    dest: str | Path,
    temp_dir: str | Path,
    job_control: JobControl,
    *,
    log_language: str = 'ja',
    temp_delete_message_key: str = 'video_temp_delete_failed',
) -> bool:
    """元ファイルを一時領域経由で配置する。停止時は False、失敗時は例外を返す。"""
    temps: list[Path] = []
    try:
        if job_control.is_cancelled:
            return False
        work_dir = Path(temp_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        staged = temp_path(work_dir, '.orig')
        temps.append(staged)
        copy_with_cancel(Path(inpath), staged, job_control)
        publish(staged, Path(dest), job_control)
        temps.remove(staged)
        return True
    except JobCancelled:
        return False
    finally:
        failures = remove_temps(temps, log_language, message_key=temp_delete_message_key)
        if failures:
            raise OSError(' / '.join(failures))


def _is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def _check_component(name: str) -> None:
    if not name or name in {'.', '..'} or Path(name).name != name:
        raise ValueError(f'invalid work directory component: {name!r}')


def create_owned_job_dir(
    output_dir: str | Path,
    subdir: str,
    owner_token: str,
    job_id: str | None = None,
) -> Path:
    """同じファイルシステム上に、新規の所有マーカー付き作業領域を作る。"""
    _check_component(subdir)
    name = job_id or uuid.uuid4().hex
    _check_component(name)
    output_root = Path(output_dir)
    work_dir = output_root / APP_WORK_DIR_NAME
    work_root = work_dir / subdir
    for path in (work_dir, work_root):
        if _is_link(path):
            raise OSError(f'work directory is a link: {path}')
        path.mkdir(parents=True, exist_ok=True)
        if _is_link(path):
            raise OSError(f'work directory is a link: {path}')

    if work_dir.resolve().parent != output_root.resolve() or work_root.resolve().parent != work_dir.resolve():
        raise OSError(f'work directory is outside the output folder: {work_root}')
    if work_root.stat().st_dev != output_root.stat().st_dev:
        raise OSError(f'work directory is on a different filesystem: {work_root}')

    job_dir = work_root / name
    job_dir.mkdir()
    with (job_dir / VIDEO_WORK_OWNER_MARKER).open('x', encoding='utf-8') as marker:
        marker.write(owner_token)
    return job_dir


def _is_owned_job_dir(job_dir: Path, work_root: Path, owner_token: str) -> bool:
    if _is_link(job_dir) or not job_dir.is_dir() or job_dir.resolve().parent != work_root.resolve():
        return False
    if job_dir.stat().st_dev != work_root.stat().st_dev:
        return False
    marker = job_dir / VIDEO_WORK_OWNER_MARKER
    if _is_link(marker) or not marker.is_file():
        return False
    try:
        return marker.read_text(encoding='utf-8').strip() == owner_token
    except UnicodeError:
        return False


def verify_owned_job_dir(output_dir: str | Path, subdir: str, job_dir: Path, owner_token: str) -> None:
    """所有マーカー、位置、ファイルシステムを確認する。"""
    _check_component(subdir)
    output_root = Path(output_dir)
    work_dir = output_root / APP_WORK_DIR_NAME
    work_root = work_dir / subdir
    if (
        _is_link(work_dir)
        or _is_link(work_root)
        or work_dir.resolve().parent != output_root.resolve()
        or work_root.resolve().parent != work_dir.resolve()
        or work_root.stat().st_dev != output_root.stat().st_dev
        or not _is_owned_job_dir(job_dir, work_root, owner_token)
    ):
        raise OSError(f'work directory ownership could not be verified: {job_dir}')


def remove_owned_job_dir(output_dir: str | Path, subdir: str, job_dir: Path, owner_token: str) -> None:
    """所有と場所を再確認した作業領域だけを削除する。"""
    if not job_dir.exists() and not _is_link(job_dir):
        return
    verify_owned_job_dir(output_dir, subdir, job_dir, owner_token)
    shutil.rmtree(job_dir)


def cleanup_owned_job_dirs(output_dir: str | Path, subdir: str, owner_token: str) -> int:
    """出力排他の取得中に、所有を確認できた過去のジョブ領域だけを削除する。"""
    work_dir = Path(output_dir) / APP_WORK_DIR_NAME
    work_root = work_dir / subdir
    if _is_link(work_dir) or _is_link(work_root) or not work_root.is_dir():
        return 0
    removed = 0
    if work_root.stat().st_dev != Path(output_dir).stat().st_dev:
        return 0
    with os.scandir(work_root) as entries:
        for entry in entries:
            path = Path(entry.path)
            if not entry.is_dir(follow_symlinks=False) or not _is_owned_job_dir(path, work_root, owner_token):
                continue
            shutil.rmtree(path)
            removed += 1
    return removed
