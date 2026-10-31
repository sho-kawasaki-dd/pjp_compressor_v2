from __future__ import annotations

"""クリーンアップがアプリ専用作業フォルダを対象外にすることを確認する unit test。"""

from pathlib import Path

import pytest

from backend.core.file_ops import cleanup_folder, count_target_files
from backend.settings import APP_WORK_DIR_NAME, JOB_LOCK_FILENAME, VIDEO_WORK_SUBDIR
from frontend.settings import OUTPUT_DIR_CLEANUP_EXTENSIONS


pytestmark = pytest.mark.unit


def test_cleanup_and_count_skip_app_work_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / 'output'
    work_dir = output_dir / APP_WORK_DIR_NAME / VIDEO_WORK_SUBDIR / 'job-1'
    work_dir.mkdir(parents=True)
    lock_path = output_dir / APP_WORK_DIR_NAME / JOB_LOCK_FILENAME
    lock_path.write_text('lock', encoding='utf-8')
    temp_video = work_dir / 'clip.mp4'
    temp_video.write_bytes(b'video')
    empty_work_subdir = work_dir / 'empty'
    empty_work_subdir.mkdir()
    result_video = output_dir / 'clip.mp4'
    result_video.write_bytes(b'video')

    assert count_target_files(output_dir, OUTPUT_DIR_CLEANUP_EXTENSIONS) == 1

    cleanup_folder(output_dir, lambda _message: None, 'cleanup_target_output', OUTPUT_DIR_CLEANUP_EXTENSIONS)

    assert not result_video.exists()
    assert lock_path.exists()
    assert temp_video.exists()
    assert empty_work_subdir.is_dir()


def test_video_extensions_are_cleanup_targets() -> None:
    from frontend.settings import INPUT_DIR_CLEANUP_EXTENSIONS

    for ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.m4v'):
        assert ext in INPUT_DIR_CLEANUP_EXTENSIONS
        assert ext in OUTPUT_DIR_CLEANUP_EXTENSIONS
