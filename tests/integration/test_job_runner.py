from __future__ import annotations

"""job_runner の結合面を説明可能に保つ integration test 群。

worker 実処理の詳細よりも、request 受け渡し、ZIP 展開、CSV、入力不変、失敗時の
フォールバックコピーといった orchestration 上の約束を守れているかを確認する。
"""

import csv
import zipfile
from pathlib import Path

import pytest

from backend.contracts import CompressionRequest, ProgressEvent
from backend.core import compressor_utils
from backend.orchestrator import job_runner
from frontend.settings import PDF_LOSSY_DPI_RANGE
import frontend.ui_tkinter_mapper as mapper_module
from frontend.ui_tkinter_mapper import build_compression_request
from shared.locale_catalog import translate as tlog


pytestmark = pytest.mark.integration


class DummyVar:
    """Tk Variable の `get` / `set` だけを模した最小ダミー。"""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class DummyMapperApp:
    """mapper が参照する UI 状態を固定値で再現するテスト用 App。"""

    def __init__(self) -> None:
        self.input_dir = DummyVar('input')
        self.output_dir = DummyVar('output')
        self.jpg_quality = DummyVar(70)
        self.png_quality = DummyVar(60)
        self.use_pngquant = DummyVar(True)
        self.pdf_engine = DummyVar('gs')
        self.pdf_mode = DummyVar('both')
        self.pdf_dpi = DummyVar(144)
        self.pdf_jpeg_quality = DummyVar(65)
        self.pdf_png_quality = DummyVar(62)
        self.pdf_ll_linearize = DummyVar(True)
        self.pdf_ll_object_streams = DummyVar(True)
        self.pdf_ll_clean_metadata = DummyVar(True)
        self.pdf_ll_recompress_streams = DummyVar(False)
        self.pdf_ll_remove_unreferenced = DummyVar(True)
        self.gs_preset = DummyVar('custom')
        self.gs_custom_dpi = DummyVar(999999)
        self.gs_use_lossless = DummyVar(True)
        self.resize_enabled = DummyVar(True)
        self.resize_mode = DummyVar('manual')
        self.resize_width = DummyVar('999999')
        self.resize_height = DummyVar('70000')
        self.resize_keep_aspect = DummyVar(True)
        self.long_edge_value_str = DummyVar('999999')
        self.csv_enable = DummyVar(True)
        self.csv_path = DummyVar('')
        self.extract_zip = DummyVar(True)
        self.zip_output_enabled = DummyVar(False)
        self.debug_mode = DummyVar(True)
        self.copy_non_target_files = DummyVar(False)
        self.ui_language = DummyVar('ja')


def snapshot_tree(root: Path) -> dict[str, int]:
    """入力ツリーが変化していないことを比較しやすい形で記録する。"""

    snapshot: dict[str, int] = {}
    for file_path in root.rglob('*'):
        if file_path.is_file():
            snapshot[str(file_path.relative_to(root)).replace('\\', '/')] = file_path.stat().st_size
    return snapshot


def test_run_compression_request_forwards_debug_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_compression_job(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(job_runner, 'run_compression_job', fake_run_compression_job)
    events: list[ProgressEvent] = []
    request = CompressionRequest(
        input_dir='input',
        output_dir='output',
        jpg_quality=70,
        png_quality=70,
        use_pngquant=True,
        pdf_engine='native',
        pdf_mode='both',
        pdf_dpi=144,
        pdf_jpeg_quality=65,
        pdf_png_quality=55,
        pdf_lossless_options={'linearize': True},
        gs_preset='/screen',
        gs_custom_dpi=None,
        resize_config=False,
        resize_width=0,
        resize_height=0,
        csv_enable=False,
        csv_path=None,
        extract_zip=True,
        zip_output_enabled=False,
        debug_mode=True,
        copy_non_target_files=False,
        log_language='ja',
    )

    job_runner.run_compression_request(request=request, event_callback=events.append)

    assert captured['debug_mode'] is True
    assert captured['log_language'] == 'ja'
    assert captured['pdf_png_quality'] == 55
    assert events == []


def test_run_compression_request_forwards_clamped_ui_values(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_compression_job(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(job_runner, 'run_compression_job', fake_run_compression_job)
    monkeypatch.setattr(mapper_module, 'get_current_language', lambda: 'ja')

    request = build_compression_request(DummyMapperApp()).request
    events: list[ProgressEvent] = []

    job_runner.run_compression_request(request=request, event_callback=events.append)

    assert captured['gs_custom_dpi'] == PDF_LOSSY_DPI_RANGE[1]
    assert captured['resize_enabled'] == {
        'enabled': True,
        'mode': 'manual',
        'width': 65535,
        'height': 65535,
        'keep_aspect': True,
    }
    assert captured['resize_width'] == 65535
    assert captured['resize_height'] == 65535
    assert captured['zip_output_enabled'] is False
    assert captured['log_language'] == 'ja'
    assert events == []


def test_build_compression_request_uses_current_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mapper_module, 'get_current_language', lambda: 'en')

    request = build_compression_request(DummyMapperApp()).request

    assert request.log_language == 'en'


def test_compat_compress_folder_forwards_zip_output_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_compression_job(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(job_runner, 'run_compression_job', fake_run_compression_job)

    compressor_utils.compress_folder(
        input_dir='input',
        output_dir='output',
        jpg_quality=70,
        png_quality=60,
        use_pngquant=True,
        log_func=lambda _message: None,
        progress_func=lambda _current, _total: None,
        stats_func=lambda _orig, _out, _saved, _pct: None,
        zip_output_enabled=True,
    )

    assert captured['zip_output_enabled'] is True


def test_run_compression_job_handles_empty_input(sample_paths) -> None:
    logs: list[str] = []
    progress: list[tuple[int, int]] = []
    stats: list[tuple[int, int, int, float]] = []

    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir),
        output_dir=str(sample_paths.output_dir),
        jpg_quality=70,
        png_quality=70,
        use_pngquant=False,
        log_func=logs.append,
        progress_func=lambda current, total: progress.append((current, total)),
        stats_func=lambda orig, out, saved, pct: stats.append((orig, out, saved, pct)),
        csv_enable=False,
        log_language='ja',
    )

    assert logs[-1] == tlog('ja', 'log_complete')
    assert progress == [(1, 1)]
    assert stats == [(0, 0, 0, 0.0)]


def test_run_compression_job_processes_images_and_writes_csv(sample_paths, image_factory) -> None:
    image_factory(sample_paths.input_dir / 'photo.jpg', size=(1600, 1200), fmt='JPEG')
    image_factory(sample_paths.input_dir / 'diagram.png', size=(800, 600), fmt='PNG')
    logs: list[str] = []
    progress: list[tuple[int, int]] = []
    stats: list[tuple[int, int, int, float]] = []

    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir),
        output_dir=str(sample_paths.output_dir),
        jpg_quality=55,
        png_quality=60,
        use_pngquant=False,
        log_func=logs.append,
        progress_func=lambda current, total: progress.append((current, total)),
        stats_func=lambda orig, out, saved, pct: stats.append((orig, out, saved, pct)),
        csv_enable=True,
        csv_path=str(sample_paths.csv_path),
        resize_enabled={'enabled': True, 'mode': 'long_edge', 'long_edge': 400},
        log_language='ja',
    )

    assert (sample_paths.output_dir / 'photo.jpg').exists()
    assert (sample_paths.output_dir / 'diagram.png').exists()
    assert sample_paths.csv_path.exists()
    with sample_paths.csv_path.open('r', encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert {row[tlog('ja', 'csv_header_input_path')] for row in rows} == {'photo.jpg', 'diagram.png'}
    assert any(message.startswith(tlog('ja', 'log_csv_output', path='')) for message in logs)
    assert progress[-1] == (2, 2)
    assert stats[-1][0] > 0


def test_run_compression_job_uses_english_csv_headers_and_logs(sample_paths, image_factory) -> None:
    image_factory(sample_paths.input_dir / 'photo.jpg', size=(1600, 1200), fmt='JPEG')
    logs: list[str] = []

    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir),
        output_dir=str(sample_paths.output_dir),
        jpg_quality=55,
        png_quality=60,
        use_pngquant=False,
        log_func=logs.append,
        progress_func=lambda _current, _total: None,
        stats_func=lambda _orig, _out, _saved, _pct: None,
        csv_enable=True,
        csv_path=str(sample_paths.csv_path),
        log_language='en',
    )

    with sample_paths.csv_path.open('r', encoding='utf-8', newline='') as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == [
        tlog('en', 'csv_header_timestamp'),
        tlog('en', 'csv_header_input_path'),
        tlog('en', 'csv_header_output_path'),
        tlog('en', 'csv_header_ext'),
        tlog('en', 'csv_header_action'),
        tlog('en', 'csv_header_orig_size'),
        tlog('en', 'csv_header_out_size'),
        tlog('en', 'csv_header_saved_bytes'),
        tlog('en', 'csv_header_saved_pct'),
        tlog('en', 'csv_header_notes'),
    ]
    assert any(message.startswith(tlog('en', 'log_csv_output', path='')) for message in logs)
    assert any(tlog('en', 'log_complete') in message for message in logs)


def test_run_compression_job_tolerates_out_of_range_quality_values(sample_paths, image_factory) -> None:
    image_factory(sample_paths.input_dir / 'photo.jpg', size=(1600, 1200), fmt='JPEG')
    image_factory(sample_paths.input_dir / 'diagram.png', size=(800, 600), fmt='PNG')

    logs: list[str] = []
    stats: list[tuple[int, int, int, float]] = []

    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir),
        output_dir=str(sample_paths.output_dir),
        jpg_quality=180,
        png_quality=180,
        use_pngquant=False,
        log_func=logs.append,
        progress_func=lambda _current, _total: None,
        stats_func=lambda orig, out, saved, pct: stats.append((orig, out, saved, pct)),
        csv_enable=False,
        log_language='ja',
    )

    assert (sample_paths.output_dir / 'photo.jpg').exists()
    assert (sample_paths.output_dir / 'diagram.png').exists()
    assert any('quality=100' in message for message in logs)
    assert stats[-1][0] > 0


def test_run_compression_job_extracts_zip_without_mutating_input(sample_paths, jpeg_bytes: bytes) -> None:
    normal_file = sample_paths.input_dir / 'normal.txt'
    normal_file.write_text('keep-input', encoding='utf-8')
    archive_path = sample_paths.input_dir / 'packs' / 'bundle.zip'
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('img/photo.jpg', jpeg_bytes)
        archive.writestr('docs/readme.txt', 'zip-text')
    # ZIP 展開が input を直接書き換えないことを、ファイルツリーの前後比較で固定する。
    before = snapshot_tree(sample_paths.input_dir)

    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir),
        output_dir=str(sample_paths.output_dir),
        jpg_quality=60,
        png_quality=60,
        use_pngquant=False,
        log_func=lambda _message: None,
        progress_func=lambda _current, _total: None,
        stats_func=lambda _orig, _out, _saved, _pct: None,
        csv_enable=False,
        extract_zip=True,
        copy_non_target_files=False,
        log_language='ja',
    )

    assert (sample_paths.output_dir / 'packs' / 'bundle' / 'img' / 'photo.jpg').exists()
    assert not (sample_paths.output_dir / 'packs' / 'bundle' / 'docs' / 'readme.txt').exists()
    assert snapshot_tree(sample_paths.input_dir) == before


def test_run_compression_job_rearchives_zip_outputs_when_enabled(sample_paths, jpeg_bytes: bytes) -> None:
    archive_path = sample_paths.input_dir / 'packs' / 'bundle.zip'
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('img/photo.jpg', jpeg_bytes)
        archive.writestr('docs/readme.txt', 'zip-text')

    before = snapshot_tree(sample_paths.input_dir)

    logs: list[str] = []
    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir),
        output_dir=str(sample_paths.output_dir),
        jpg_quality=60,
        png_quality=60,
        use_pngquant=False,
        log_func=logs.append,
        progress_func=lambda _current, _total: None,
        stats_func=lambda _orig, _out, _saved, _pct: None,
        csv_enable=True,
        csv_path=str(sample_paths.csv_path),
        extract_zip=True,
        zip_output_enabled=True,
        copy_non_target_files=True,
        log_language='ja',
    )

    zipped_output = sample_paths.output_dir / 'packs' / 'bundle.zip'
    folder_output = sample_paths.output_dir / 'packs' / 'bundle'
    assert zipped_output.exists()
    assert not folder_output.exists()
    with zipfile.ZipFile(zipped_output, 'r') as archive:
        assert 'img/photo.jpg' in archive.namelist()
        assert 'docs/readme.txt' in archive.namelist()
    assert any(tlog('ja', 'log_zip_output_mode_enabled') in message for message in logs)
    assert sample_paths.csv_path.exists()
    with sample_paths.csv_path.open('r', encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert all(row[tlog('ja', 'csv_header_output_path')].startswith('packs/bundle/') for row in rows)
    assert {row[tlog('ja', 'csv_header_notes')] for row in rows} == {'zip_archive=packs/bundle.zip'}
    regenerated_prefix = tlog('ja', 'log_zip_regenerated', input_path='', output_path='', archived_file_count=0).split(' -> ')[0]
    assert any(message.startswith(regenerated_prefix) for message in logs)
    assert snapshot_tree(sample_paths.input_dir) == before


def test_run_compression_job_copies_failed_compressible_file_in_mirror_mode(
    monkeypatch: pytest.MonkeyPatch,
    sample_paths,
    image_factory,
) -> None:
    source = image_factory(sample_paths.input_dir / 'broken.jpg', fmt='JPEG')
    import backend.core.worker_ops as worker_ops

    monkeypatch.setattr(
        worker_ops,
        # processed=False を返して、圧縮対象でも mirror 時は原本コピーへ退避する分岐を踏ませる。
        'process_single_file',
        lambda task: ('画像失敗: broken.jpg (boom)', source.stat().st_size, source.stat().st_size, False),
    )

    logs: list[str] = []
    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir),
        output_dir=str(sample_paths.output_dir),
        jpg_quality=60,
        png_quality=60,
        use_pngquant=False,
        log_func=logs.append,
        progress_func=lambda _current, _total: None,
        stats_func=lambda _orig, _out, _saved, _pct: None,
        csv_enable=False,
        copy_non_target_files=True,
        log_language='ja',
    )

    assert (sample_paths.output_dir / 'broken.jpg').exists()
    assert any(tlog('ja', 'log_fallback_copy') in message for message in logs)
