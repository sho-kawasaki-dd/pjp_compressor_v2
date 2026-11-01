from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_ffmpeg_distribution import verify_ffmpeg_vendor


pytestmark = pytest.mark.unit


def _write_test_distribution(root: Path) -> dict[str, bytes]:
    vendor_bin_dir = root / 'vendor' / 'ffmpeg-windows' / 'bin'
    vendor_bin_dir.mkdir(parents=True)
    license_dir = vendor_bin_dir.parent / 'licenses'
    license_dir.mkdir()
    binaries = {
        'ffmpeg.exe': b'approved ffmpeg',
        'ffprobe.exe': b'approved ffprobe',
    }
    for name, content in binaries.items():
        (vendor_bin_dir / name).write_bytes(content)
    license_notices = {
        'FFmpeg-COPYING.GPLv3': b'GPL license',
        'FFmpeg-CREDITS': b'FFmpeg credits',
        'FFmpeg-LICENSE.md': b'FFmpeg license information',
        'NOTICE.txt': b'IJG notice',
        'x264-COPYING': b'x264 license',
    }
    for name, content in license_notices.items():
        (license_dir / name).write_bytes(content)

    manifest_path = root / 'Documentation' / 'ffmpeg-x264-only-manifest.json'
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({
            'status': 'approved_for_redistribution',
            'artifact': {
                'binaries': [
                    {'name': name, 'sha256': hashlib.sha256(content).hexdigest()}
                    for name, content in binaries.items()
                ],
            },
            'license_notices': [
                {'name': name, 'sha256': hashlib.sha256(content).hexdigest()}
                for name, content in license_notices.items()
            ],
        }),
        encoding='utf-8',
    )
    return binaries


def test_verify_ffmpeg_vendor_accepts_manifest_hashes(tmp_path: Path) -> None:
    binaries = _write_test_distribution(tmp_path)

    verified = verify_ffmpeg_vendor(tmp_path)

    assert {path.name for path in verified} == set(binaries)


def test_verify_ffmpeg_vendor_rejects_hash_mismatch(tmp_path: Path) -> None:
    _write_test_distribution(tmp_path)
    ffmpeg_path = tmp_path / 'vendor' / 'ffmpeg-windows' / 'bin' / 'ffmpeg.exe'
    ffmpeg_path.write_bytes(b'changed binary')

    with pytest.raises(ValueError, match='hash mismatch'):
        verify_ffmpeg_vendor(tmp_path)
