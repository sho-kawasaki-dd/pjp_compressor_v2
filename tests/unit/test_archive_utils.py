from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from backend.core.archive_utils import extract_zip_archives


pytestmark = pytest.mark.unit


def test_extract_zip_archives_recurses_nested_zips(tmp_path: Path, jpeg_bytes: bytes, zip_factory) -> None:
    target_dir = tmp_path / 'archives'
    target_dir.mkdir()

    inner_zip = tmp_path / 'inner.zip'
    zip_factory(inner_zip, {'nested/photo.jpg': jpeg_bytes})
    outer_zip = target_dir / 'outer.zip'
    zip_factory(outer_zip, {'inner.zip': inner_zip.read_bytes()})

    logs: list[str] = []
    extracted_total, failed_total = extract_zip_archives(target_dir, logs.append)

    assert extracted_total == 2
    assert failed_total == 0
    assert (target_dir / 'inner.zip').exists()
    assert (target_dir / 'nested' / 'photo.jpg').exists()
    assert any('outer.zip' in message for message in logs)
    assert any('inner.zip' in message for message in logs)


def test_extract_zip_archives_returns_zero_for_invalid_target(tmp_path: Path) -> None:
    missing_dir = tmp_path / 'missing'

    assert extract_zip_archives(missing_dir) == (0, 0)


def test_extract_zip_archives_logs_failures_for_corrupt_zip(tmp_path: Path) -> None:
    target_dir = tmp_path / 'archives'
    target_dir.mkdir()
    bad_zip = target_dir / 'broken.zip'
    bad_zip.write_bytes(b'not-a-zip')

    logs: list[str] = []
    extracted_total, failed_total = extract_zip_archives(target_dir, logs.append)

    assert extracted_total == 0
    assert failed_total == 1
    assert any('ZIP展開失敗' in message for message in logs)


def test_extract_zip_archives_rejects_path_traversal_member(tmp_path: Path, jpeg_bytes: bytes, zip_factory) -> None:
    target_dir = tmp_path / 'archives'
    target_dir.mkdir()
    bad_zip = target_dir / 'traversal.zip'
    zip_factory(bad_zip, {'../../escape.jpg': jpeg_bytes})

    logs: list[str] = []
    extracted_total, failed_total = extract_zip_archives(target_dir, logs.append)

    assert extracted_total == 0
    assert failed_total == 1
    assert not (tmp_path / 'escape.jpg').exists()
    assert any('path_traversal' in message for message in logs)


def test_extract_zip_archives_rejects_symlink_member(tmp_path: Path) -> None:
    target_dir = tmp_path / 'archives'
    target_dir.mkdir()
    bad_zip = target_dir / 'symlink.zip'
    link_info = zipfile.ZipInfo('danger-link')
    link_info.create_system = 3
    link_info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(bad_zip, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(link_info, 'ignored-target')

    logs: list[str] = []
    extracted_total, failed_total = extract_zip_archives(target_dir, logs.append)

    assert extracted_total == 0
    assert failed_total == 1
    assert any('symlink' in message for message in logs)
