from __future__ import annotations

"""cleanup_folder と count_target_files の削除対象を固定する unit test。"""

import zipfile
from pathlib import Path

import pytest

from backend.core.file_ops import cleanup_folder, count_target_files
from frontend.settings import OUTPUT_DIR_CLEANUP_EXTENSIONS


pytestmark = pytest.mark.unit


def test_cleanup_folder_removes_zip_and_known_output_files(tmp_path: Path) -> None:
    output_dir = tmp_path / 'output'
    nested_dir = output_dir / 'packs'
    nested_dir.mkdir(parents=True, exist_ok=True)

    zip_path = nested_dir / 'bundle.zip'
    csv_path = output_dir / 'log.csv'
    txt_path = output_dir / 'keep.txt'

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('img/photo.jpg', b'jpg-bytes')
    csv_path.write_text('timestamp,input_path', encoding='utf-8')
    txt_path.write_text('keep me', encoding='utf-8')

    assert count_target_files(output_dir, OUTPUT_DIR_CLEANUP_EXTENSIONS) == 2

    logs: list[str] = []
    cleanup_folder(output_dir, logs.append, '出力フォルダ', OUTPUT_DIR_CLEANUP_EXTENSIONS)

    assert not zip_path.exists()
    assert not csv_path.exists()
    assert txt_path.exists()
    assert any('bundle.zip' in message for message in logs)
    assert any('log.csv' in message for message in logs)