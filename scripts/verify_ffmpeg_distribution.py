#!/usr/bin/env python3
"""Verify that bundled FFmpeg binaries match the approved x264-only build."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / 'Documentation' / 'ffmpeg-x264-only-manifest.json'
VENDOR_BIN_DIR = Path('vendor') / 'ffmpeg-windows' / 'bin'
EXPECTED_BINARIES = {'ffmpeg.exe', 'ffprobe.exe'}
EXPECTED_LICENSES = {
    'FFmpeg-COPYING.GPLv3',
    'FFmpeg-CREDITS',
    'FFmpeg-LICENSE.md',
    'NOTICE.txt',
    'x264-COPYING',
}


def verify_ffmpeg_vendor(root: Path = PROJECT_ROOT) -> tuple[Path, ...]:
    """Reject missing, unapproved, or hash-mismatched bundled FFmpeg binaries."""
    manifest_path = root / MANIFEST_PATH.relative_to(PROJECT_ROOT)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != 'approved_for_redistribution':
        raise ValueError(f'FFmpeg manifest is not approved: {manifest_path}')

    binary_records = manifest.get('artifact', {}).get('binaries', [])
    records_by_name = {record.get('name'): record for record in binary_records}
    if set(records_by_name) != EXPECTED_BINARIES:
        raise ValueError(f'Unexpected FFmpeg binary set in manifest: {sorted(records_by_name)}')

    vendor_bin_dir = root / VENDOR_BIN_DIR
    actual_binaries = {path.name for path in vendor_bin_dir.glob('*.exe') if path.is_file()}
    if actual_binaries != EXPECTED_BINARIES:
        raise ValueError(
            f'Expected only {sorted(EXPECTED_BINARIES)} in {vendor_bin_dir}, '
            f'found {sorted(actual_binaries)}'
        )

    verified_paths: list[Path] = []
    for name in sorted(EXPECTED_BINARIES):
        binary_path = vendor_bin_dir / name
        if not binary_path.is_file():
            raise FileNotFoundError(f'Approved FFmpeg binary is missing: {binary_path}')
        actual_hash = hashlib.sha256(binary_path.read_bytes()).hexdigest()
        expected_hash = records_by_name[name].get('sha256')
        if actual_hash != expected_hash:
            raise ValueError(
                f'FFmpeg binary hash mismatch for {binary_path}: '
                f'expected {expected_hash}, got {actual_hash}'
            )
        verified_paths.append(binary_path)

    license_records = manifest.get('license_notices', [])
    records_by_name = {record.get('name'): record for record in license_records}
    if set(records_by_name) != EXPECTED_LICENSES:
        raise ValueError(f'Unexpected FFmpeg license notice set in manifest: {sorted(records_by_name)}')

    license_dir = root / 'vendor' / 'ffmpeg-windows' / 'licenses'
    for name in sorted(EXPECTED_LICENSES):
        license_path = license_dir / name
        if not license_path.is_file():
            raise FileNotFoundError(f'Approved FFmpeg license notice is missing: {license_path}')
        actual_hash = hashlib.sha256(license_path.read_bytes()).hexdigest()
        expected_hash = records_by_name[name].get('sha256')
        if actual_hash != expected_hash:
            raise ValueError(
                f'FFmpeg license notice hash mismatch for {license_path}: '
                f'expected {expected_hash}, got {actual_hash}'
            )

    return tuple(verified_paths)


if __name__ == '__main__':
    try:
        verified = verify_ffmpeg_vendor()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'FFmpeg distribution verification failed: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
    for path in verified:
        print(f'Verified approved FFmpeg binary: {path}')
