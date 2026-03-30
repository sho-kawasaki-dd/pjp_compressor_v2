from __future__ import annotations

"""画像圧縮 helper の resize・pngquant・フォールバック境界を確認する unit test。"""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from backend.core import image_utils


pytestmark = pytest.mark.unit


def test_compress_image_pillow_resizes_long_edge(sample_paths, image_factory) -> None:
    input_path = image_factory(sample_paths.input_dir / 'large.jpg', size=(2000, 1000), fmt='JPEG')
    output_path = sample_paths.output_dir / 'large.jpg'

    ok, message = image_utils.compress_image_pillow(
        input_path,
        output_path,
        quality=70,
        resize_cfg={'enabled': True, 'mode': 'long_edge', 'long_edge': 500},
    )

    assert ok is True
    assert 'resize=500x250' in message
    with Image.open(output_path) as compressed:
        assert compressed.size == (500, 250)


def test_compress_png_pngquant_falls_back_to_pillow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    expected = (True, 'fallback called')
    calls: list[tuple[str, str, int, object]] = []

    monkeypatch.setattr(image_utils.shutil, 'which', lambda _: None)
    monkeypatch.setattr(
        image_utils,
        'compress_image_pillow',
        lambda inpath, outpath, quality, resize_cfg=None: calls.append((inpath, outpath, quality, resize_cfg)) or expected,
    )

    result = image_utils.compress_png_pngquant(tmp_path / 'in.png', tmp_path / 'out.png', 30, 60, resize_cfg={'enabled': True})

    assert result == expected
    assert calls == [(str(tmp_path / 'in.png'), str(tmp_path / 'out.png'), 60, {'enabled': True})]


def test_compress_png_pngquant_reports_resize_when_external_tool_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    sample_paths,
    image_factory,
) -> None:
    input_path = image_factory(sample_paths.input_dir / 'sample.png', size=(1200, 600), fmt='PNG')
    output_path = sample_paths.output_dir / 'sample.png'

    def fake_run(cmd, **kwargs):
        Path(cmd[5]).write_bytes(b'pngquant-output')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(image_utils.shutil, 'which', lambda _: 'C:/tools/pngquant.exe')
    monkeypatch.setattr(image_utils.subprocess, 'run', fake_run)

    ok, message = image_utils.compress_png_pngquant(
        input_path,
        output_path,
        40,
        60,
        resize_cfg={'enabled': True, 'mode': 'long_edge', 'long_edge': 300},
    )

    assert ok is True
    assert output_path.read_bytes() == b'pngquant-output'
    assert 'resize=300x150' in message
    assert not output_path.with_suffix('.png.tmp_resize.png').exists()


def test_compress_png_pngquant_clamps_quality_and_uses_timeout(
    monkeypatch: pytest.MonkeyPatch,
    sample_paths,
    image_factory,
) -> None:
    input_path = image_factory(sample_paths.input_dir / 'sample.png', size=(320, 240), fmt='PNG')
    output_path = sample_paths.output_dir / 'sample.png'
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen['cmd'] = cmd
        seen['timeout'] = kwargs.get('timeout')
        Path(cmd[5]).write_bytes(b'pngquant-output')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(image_utils.shutil, 'which', lambda _: 'C:/tools/pngquant.exe')
    monkeypatch.setattr(image_utils.subprocess, 'run', fake_run)

    ok, message = image_utils.compress_png_pngquant(input_path, output_path, -15, 180, speed=99)

    assert ok is True
    assert '--quality=0-100' in seen['cmd']
    assert '--speed=11' in seen['cmd']
    assert '--' in seen['cmd']
    assert seen['timeout'] == image_utils.PNGQUANT_TIMEOUT_SECONDS
    assert 'quality=0-100' in message
