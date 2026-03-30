from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.core import pdf_utils


pytestmark = pytest.mark.unit


def _make_jpeg_bytes(*, size: tuple[int, int], quality: int) -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', size, color=(32, 96, 192)).save(buffer, 'JPEG', quality=quality)
    return buffer.getvalue()


def _make_png_bytes(*, size: tuple[int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new('RGBA', size, color=(32, 160, 96, 180)).save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def _make_mask_png_bytes(*, size: tuple[int, int]) -> bytes:
    buffer = io.BytesIO()
    mask = Image.linear_gradient('L').resize(size)
    mask.save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def _assert_image_has_nontrivial_alpha(image_bytes: bytes) -> None:
    image = Image.open(io.BytesIO(image_bytes))
    assert image.format == 'PNG'
    rgba = image.convert('RGBA')
    alpha_min, alpha_max = rgba.getchannel('A').getextrema()
    assert alpha_min < 255
    assert alpha_max > alpha_min


class _FakeRect:
    def __init__(self, bbox: tuple[float, float, float, float]):
        self.width = float(bbox[2] - bbox[0])
        self.height = float(bbox[3] - bbox[1])


class _FakePage:
    def __init__(self, image_infos: list[dict[str, object]]):
        self._image_infos = image_infos
        self.replace_calls: list[tuple[int, bytes]] = []

    def get_image_info(self, *, xrefs: bool) -> list[dict[str, object]]:
        assert xrefs is True
        return list(self._image_infos)

    def get_images(self, *args, **kwargs):
        raise AssertionError('get_images() should not be used by compress_pdf_lossy')

    def replace_image(self, xref: int, *, stream: bytes) -> None:
        self.replace_calls.append((xref, stream))


class _FakeDoc:
    def __init__(self, pages: list[_FakePage], extracted_images: dict[int, dict[str, object] | None]):
        self._pages = pages
        self._extracted_images = extracted_images
        self.extract_calls: list[int] = []
        self.save_calls: list[tuple[str, int, bool]] = []
        self.closed = False

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int) -> _FakePage:
        return self._pages[index]

    def extract_image(self, xref: int):
        self.extract_calls.append(xref)
        return self._extracted_images.get(xref)

    def save(self, path: str, *, garbage: int, deflate: bool) -> None:
        self.save_calls.append((path, garbage, deflate))

    def close(self) -> None:
        self.closed = True


class _FakeFitzModule:
    def __init__(self, doc: _FakeDoc):
        self._doc = doc

    def open(self, path: str) -> _FakeDoc:
        return self._doc

    def Rect(self, bbox: tuple[float, float, float, float]) -> _FakeRect:
        return _FakeRect(bbox)


def test_compress_pdf_lossy_uses_image_info_and_processes_each_xref_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / 'input.pdf'
    output_path = tmp_path / 'output.pdf'
    input_path.write_bytes(b'%PDF-1.4 test')

    original_bytes = _make_jpeg_bytes(size=(2400, 1200), quality=100)
    page1 = _FakePage([{'xref': 10, 'bbox': (0.0, 0.0, 144.0, 72.0)}])
    page2 = _FakePage([{'xref': 10, 'bbox': (0.0, 0.0, 144.0, 72.0)}])
    fake_doc = _FakeDoc(
        [page1, page2],
        extracted_images={10: {'image': original_bytes, 'ext': 'jpeg'}},
    )
    monkeypatch.setattr(pdf_utils, '_import_fitz', lambda: (_FakeFitzModule(fake_doc), None))

    ok, message = pdf_utils.compress_pdf_lossy(
        input_path,
        output_path,
        target_dpi=72,
        jpeg_quality=40,
    )

    assert ok is True
    assert '一意の画像2個中1個を再圧縮' in message
    assert fake_doc.extract_calls == [10]
    assert len(page1.replace_calls) == 1
    assert page2.replace_calls == []
    assert fake_doc.save_calls == [(str(output_path), 4, True)]
    assert fake_doc.closed is True


def test_compress_pdf_lossy_skips_missing_xref_without_extracting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / 'input.pdf'
    output_path = tmp_path / 'output.pdf'
    input_path.write_bytes(b'%PDF-1.4 test')

    page = _FakePage([
        {'xref': 0, 'bbox': (0.0, 0.0, 100.0, 100.0)},
        {'xref': 11, 'bbox': (0.0, 0.0, 0.0, 0.0)},
    ])
    fake_doc = _FakeDoc([page], extracted_images={})
    monkeypatch.setattr(pdf_utils, '_import_fitz', lambda: (_FakeFitzModule(fake_doc), None))

    ok, message = pdf_utils.compress_pdf_lossy(input_path, output_path, debug=True)

    assert ok is True
    assert '一意の画像2個中0個を再圧縮' in message
    assert fake_doc.extract_calls == []
    assert page.replace_calls == []
    captured = capsys.readouterr().out
    assert 'skip_xref_missing: 1' in captured
    assert 'skip_zero_rect: 1' in captured


def test_compress_pdf_lossy_png_uses_pngquant_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / 'input.pdf'
    output_path = tmp_path / 'output.pdf'
    input_path.write_bytes(b'%PDF-1.4 test')

    original_bytes = _make_png_bytes(size=(120, 120))
    page = _FakePage([{'xref': 15, 'bbox': (0.0, 0.0, 140.0, 140.0)}])
    fake_doc = _FakeDoc([page], extracted_images={15: {'image': original_bytes, 'ext': 'png'}})
    monkeypatch.setattr(pdf_utils, '_import_fitz', lambda: (_FakeFitzModule(fake_doc), None))
    monkeypatch.setattr(pdf_utils.shutil, 'which', lambda name: 'C:/tools/pngquant.exe' if name == 'pngquant' else None)

    seen_cmds: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen_cmds.append(cmd)
        out_index = cmd.index('--output') + 1
        out_path = Path(cmd[out_index])
        out_path.write_bytes(_make_png_bytes(size=(16, 16)))
        return SimpleNamespace(returncode=0, stderr='')

    monkeypatch.setattr(pdf_utils.subprocess, 'run', fake_run)

    ok, message = pdf_utils.compress_pdf_lossy(
        input_path,
        output_path,
        png_quality=62,
    )

    assert ok is True
    assert '--quality=42-62' in seen_cmds[0]
    assert len(page.replace_calls) == 1
    assert 'PNG量子化=pngquant' in message


def test_compress_pdf_png_image_falls_back_to_fixed_palette_without_pngquant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_utils.shutil, 'which', lambda _name: None)
    source = Image.new('RGBA', (64, 64), color=(48, 144, 220, 180))

    bytes_low, meta_low = pdf_utils._compress_pdf_png_image(source, 15)
    bytes_high, meta_high = pdf_utils._compress_pdf_png_image(source, 95)

    assert meta_low['quantizer'] == 'Pillow 256-color fallback'
    assert meta_high['quantizer'] == 'Pillow 256-color fallback'
    assert bytes_low == bytes_high

    quantized = Image.open(io.BytesIO(bytes_low))
    colors = quantized.getcolors(maxcolors=257)
    assert colors is not None
    assert len(colors) <= 256


def test_compress_pdf_lossy_reconstructs_soft_mask_and_preserves_transparency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / 'input.pdf'
    output_path = tmp_path / 'output.pdf'
    input_path.write_bytes(b'%PDF-1.4 test')

    original_bytes = _make_jpeg_bytes(size=(1600, 1600), quality=100)
    mask_bytes = _make_mask_png_bytes(size=(1600, 1600))
    page = _FakePage([{'xref': 20, 'bbox': (0.0, 0.0, 144.0, 144.0)}])
    fake_doc = _FakeDoc(
        [page],
        extracted_images={
            20: {'image': original_bytes, 'ext': 'jpeg', 'smask': 21},
            21: {'image': mask_bytes, 'ext': 'png'},
        },
    )
    monkeypatch.setattr(pdf_utils, '_import_fitz', lambda: (_FakeFitzModule(fake_doc), None))
    monkeypatch.setattr(pdf_utils.shutil, 'which', lambda _name: None)

    ok, _message = pdf_utils.compress_pdf_lossy(
        input_path,
        output_path,
        target_dpi=72,
        jpeg_quality=40,
        debug=False,
    )

    assert ok is True
    assert fake_doc.extract_calls == [20, 21]
    assert len(page.replace_calls) == 1
    replaced_xref, replaced_bytes = page.replace_calls[0]
    assert replaced_xref == 20
    _assert_image_has_nontrivial_alpha(replaced_bytes)


def test_compress_pdf_lossy_soft_mask_extract_failure_falls_back_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / 'input.pdf'
    output_path = tmp_path / 'output.pdf'
    input_path.write_bytes(b'%PDF-1.4 test')

    original_bytes = _make_jpeg_bytes(size=(1600, 1600), quality=100)
    page = _FakePage([{'xref': 30, 'bbox': (0.0, 0.0, 144.0, 144.0)}])
    fake_doc = _FakeDoc(
        [page],
        extracted_images={30: {'image': original_bytes, 'ext': 'jpeg', 'smask': 31}},
    )
    monkeypatch.setattr(pdf_utils, '_import_fitz', lambda: (_FakeFitzModule(fake_doc), None))
    monkeypatch.setattr(pdf_utils.shutil, 'which', lambda _name: None)

    ok, _message = pdf_utils.compress_pdf_lossy(
        input_path,
        output_path,
        target_dpi=72,
        jpeg_quality=40,
        debug=True,
    )

    assert ok is True
    assert fake_doc.extract_calls == [30, 31]
    assert len(page.replace_calls) == 1
    replaced_xref, replaced_bytes = page.replace_calls[0]
    assert replaced_xref == 30
    assert Image.open(io.BytesIO(replaced_bytes)).format == 'JPEG'
    captured = capsys.readouterr().out
    assert 'soft_mask_seen: 1' in captured
    assert 'soft_mask_failed: 1' in captured