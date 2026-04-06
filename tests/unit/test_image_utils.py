from __future__ import annotations

"""画像圧縮 helper の resize・pngquant・フォールバック境界を確認する unit test。"""

import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from backend.core import image_utils


pytestmark = pytest.mark.unit


def _make_cmyk_jpeg(path: Path, *, size: tuple[int, int]) -> Path:
    """CMYK JPEG を生成して RGB 変換テストに使う。"""

    buffer = io.BytesIO()
    Image.new('CMYK', size, color=(255, 0, 0, 0)).save(buffer, 'JPEG', quality=95)
    path.write_bytes(buffer.getvalue())
    return path


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


def test_compress_image_pillow_converts_cmyk_to_rgb(sample_paths) -> None:
    input_path = _make_cmyk_jpeg(sample_paths.input_dir / 'cmyk.jpg', size=(640, 480))
    output_path = sample_paths.output_dir / 'cmyk.jpg'

    ok, message = image_utils.compress_image_pillow(input_path, output_path, quality=70)

    assert ok is True
    assert 'quality=70' in message
    with Image.open(output_path) as compressed:
        assert compressed.mode == 'RGB'


def test_compress_png_pngquant_resizes_cmyk_input_before_cli(
    monkeypatch: pytest.MonkeyPatch,
    sample_paths,
) -> None:
    input_path = _make_cmyk_jpeg(sample_paths.input_dir / 'cmyk.jpg', size=(1200, 600))
    output_path = sample_paths.output_dir / 'cmyk.png'
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen['cmd'] = cmd
        seen['timeout'] = kwargs.get('timeout')
        Path(cmd[5]).write_bytes(b'pngquant-output')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(image_utils.shutil, 'which', lambda _: 'C:/tools/pngquant.exe')
    monkeypatch.setattr(image_utils.subprocess, 'run', fake_run)

    ok, message = image_utils.compress_png_pngquant(
        input_path,
        output_path,
        30,
        60,
        resize_cfg={'enabled': True, 'mode': 'long_edge', 'long_edge': 300},
    )

    assert ok is True
    assert output_path.read_bytes() == b'pngquant-output'
    assert 'resize=300x150' in message
    assert seen['timeout'] == image_utils.PNGQUANT_TIMEOUT_SECONDS
    assert not output_path.with_suffix('.png.tmp_resize.png').exists()
