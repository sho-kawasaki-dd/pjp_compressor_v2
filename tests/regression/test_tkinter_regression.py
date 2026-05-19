from __future__ import annotations

"""Tk 実体を使った回帰シナリオをまとめる regression test 群。

unit/integration では表現しづらい GUI 導線、ZIP 組み合わせ行列、cleanup と overlap
guard の連携を、実 App に近い形で崩れていないか確認する。
"""

import shutil
import time
import zipfile
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from tkinter import filedialog, messagebox

import frontend.ui_tkinter_controller as controller_module
from backend.orchestrator.job_runner import run_compression_request
from frontend.ui_tkinter_mapper import build_compression_request


pytestmark = [pytest.mark.regression, pytest.mark.requires_tk]


def wait_threads(app, timeout: float = 15.0) -> None:
    """非同期 worker が自然終了するまで UI イベントループを回す。"""

    start = time.time()
    while time.time() - start < timeout:
        app.update()
        app.update_idletasks()
        alive = [thread for thread in app.threads if thread.is_alive()]
        if not alive:
            return
        time.sleep(0.05)
    raise TimeoutError('worker thread timeout')


def snapshot_input_tree(root: Path) -> dict[str, int]:
    """ZIP 展開前後で入力ツリーが不変かを見るためのスナップショット。"""

    snapshot: dict[str, int] = {}
    for file_path in root.rglob('*'):
        if file_path.is_file():
            rel = str(file_path.relative_to(root)).replace('\\', '/')
            snapshot[rel] = file_path.stat().st_size
    return snapshot


def clear_output_dir(output_dir: Path) -> None:
    """ZIP 行列ケースごとの差分を消すため出力を毎回初期化する。"""

    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)


def create_zip_fixture(input_dir: Path) -> tuple[Path, Path, Path]:
    """通常ファイル + ZIP 内 target/non-target を含む行列用 fixture を作る。"""

    normal_jpg = input_dir / 'normal.jpg'
    normal_txt = input_dir / 'normal.txt'
    zip_dir = input_dir / 'subpack'
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / 'myzip.zip'

    Image.new('RGB', (320, 240), color=(0, 0, 255)).save(normal_jpg, 'JPEG', quality=95)
    normal_txt.write_text('normal-text', encoding='utf-8')

    payload_root = input_dir / '_payload_tmp'
    payload_img = payload_root / 'img' / 'photo.jpg'
    payload_txt = payload_root / 'docs' / 'readme.txt'
    payload_img.parent.mkdir(parents=True, exist_ok=True)
    payload_txt.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (240, 180), color=(128, 64, 32)).save(payload_img, 'JPEG', quality=95)
    payload_txt.write_text('zip-non-target', encoding='utf-8')

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(payload_img, arcname='img/photo.jpg')
        archive.write(payload_txt, arcname='docs/readme.txt')

    shutil.rmtree(payload_root, ignore_errors=True)
    return zip_path, normal_jpg, normal_txt


def run_zip_matrix_tests(app, input_dir: Path, output_dir: Path) -> None:
    """ZIP 展開・mirror・ZIP出力の 3 軸組み合わせを回帰確認する。"""

    zip_path, _, _ = create_zip_fixture(input_dir)
    input_before = snapshot_input_tree(input_dir)

    def execute_case(extract_zip: bool, mirror_mode: bool, zip_output_mode: bool = False) -> None:
        app.extract_zip.set(extract_zip)
        app.copy_non_target_files.set(mirror_mode)
        app.zip_output_enabled.set(zip_output_mode)
        request = build_compression_request(app).request
        assert request.extract_zip is extract_zip
        assert request.copy_non_target_files is mirror_mode
        assert request.zip_output_enabled is zip_output_mode
        captured: list[object] = []
        run_compression_request(request=request, event_callback=captured.append)
        assert any(getattr(event, 'kind', '') == 'progress' for event in captured), 'progress event missing in zip case'
        assert any(getattr(event, 'kind', '') == 'stats' for event in captured), 'stats event missing in zip case'

    for extract_zip, mirror_mode, zip_output_mode in product((False, True), repeat=3):
        case_label = (
            f'extract_zip={extract_zip}, '
            f'mirror_mode={mirror_mode}, '
            f'zip_output_mode={zip_output_mode}'
        )
        clear_output_dir(output_dir)
        execute_case(extract_zip=extract_zip, mirror_mode=mirror_mode, zip_output_mode=zip_output_mode)

        normal_jpg_output = output_dir / 'normal.jpg'
        normal_txt_output = output_dir / 'normal.txt'
        zipped_output = output_dir / 'subpack' / 'myzip.zip'
        folder_output = output_dir / 'subpack' / 'myzip'
        zipped_file_entries: set[str] = set()

        assert normal_jpg_output.exists(), case_label
        assert normal_txt_output.exists() is mirror_mode, case_label

        expected_zip_exists = mirror_mode or (extract_zip and zip_output_mode)
        expected_folder_exists = extract_zip and not zip_output_mode
        expected_zip_files = {'img/photo.jpg'}
        if mirror_mode:
            expected_zip_files.add('docs/readme.txt')

        assert zipped_output.exists() is expected_zip_exists, case_label
        assert folder_output.exists() is expected_folder_exists, case_label

        if zipped_output.exists():
            with zipfile.ZipFile(zipped_output, 'r') as archive:
                zipped_file_entries = {name for name in archive.namelist() if not name.endswith('/')}
            assert zipped_file_entries == expected_zip_files, case_label

        photo_output = folder_output / 'img' / 'photo.jpg'
        txt_output = folder_output / 'docs' / 'readme.txt'
        assert photo_output.exists() is expected_folder_exists, case_label
        assert txt_output.exists() is (expected_folder_exists and mirror_mode), case_label

    input_after = snapshot_input_tree(input_dir)
    assert input_before == input_after
    assert zip_path.exists()


def seed_sample_images(input_dir: Path) -> tuple[Path, Path]:
    """GUI 導線テストで十分な JPG/PNG 入力を用意する。"""

    jpg_path = input_dir / 'sample.jpg'
    png_path = input_dir / 'sample.png'
    Image.new('RGB', (320, 240), color=(255, 0, 0)).save(jpg_path, 'JPEG', quality=95)
    Image.new('RGB', (320, 240), color=(0, 255, 0)).save(png_path, 'PNG')
    return jpg_path, png_path


def test_dialog_drop_and_csv_flow(tk_regression_app, monkeypatch: pytest.MonkeyPatch) -> None:
    app, input_dir, output_dir = tk_regression_app
    jpg_path, _ = seed_sample_images(input_dir)
    csv_file = output_dir / 'check.csv'

    monkeypatch.setattr(filedialog, 'askdirectory', lambda initialdir=None: str(input_dir))
    app.choose_input()
    assert Path(app.input_dir.get()) == input_dir

    monkeypatch.setattr(filedialog, 'askdirectory', lambda initialdir=None: str(output_dir))
    app.choose_output()
    assert Path(app.output_dir.get()) == output_dir

    app._on_drop_input(SimpleNamespace(data='{' + str(jpg_path) + '}'))
    assert Path(app.input_dir.get()) == input_dir

    monkeypatch.setattr(filedialog, 'asksaveasfilename', lambda **kwargs: str(csv_file))
    app._choose_csv_path()
    assert Path(app.csv_path.get()) == csv_file


def test_request_mapping_and_compression_run_produces_outputs(tk_regression_app) -> None:
    app, input_dir, output_dir = tk_regression_app
    seed_sample_images(input_dir)
    csv_file = output_dir / 'check.csv'

    app.input_dir.set(str(input_dir))
    app.output_dir.set(str(output_dir))
    app.jpg_quality.set(75)
    app.png_quality.set(70)
    app.resize_enabled.set(True)
    app.resize_mode.set('long_edge')
    app.long_edge_value_str.set('256')
    app.csv_enable.set(True)
    app.csv_path.set(str(csv_file))
    app.extract_zip.set(False)

    request = build_compression_request(app).request
    captured: list[object] = []
    run_compression_request(request=request, event_callback=captured.append)

    assert (output_dir / 'sample.jpg').exists()
    assert (output_dir / 'sample.png').exists()
    assert any(getattr(event, 'kind', '') == 'progress' for event in captured)
    assert any(getattr(event, 'kind', '') == 'stats' for event in captured)


def test_start_compress_cleanup_output_and_overlap_guard(tk_regression_app, monkeypatch: pytest.MonkeyPatch) -> None:
    app, input_dir, output_dir = tk_regression_app
    seed_sample_images(input_dir)

    app.input_dir.set(str(input_dir))
    app.output_dir.set(str(output_dir))

    original_runner = controller_module.run_compression_request
    try:
        def fake_runner(request, event_callback):
            event_callback(SimpleNamespace(kind='log', message='dummy'))
            event_callback(SimpleNamespace(kind='progress', current=1, total=1))
            event_callback(SimpleNamespace(kind='stats', orig_total=1, out_total=1, saved=0, saved_pct=0.0))

        controller_module.run_compression_request = fake_runner
        app.log = lambda msg: None
        app.update_progress = lambda current, total: None
        app.update_stats = lambda orig_total, out_total, saved, saved_pct: None
        app._set_status = lambda text: None

        app.start_compress()
        wait_threads(app)
    finally:
        controller_module.run_compression_request = original_runner

    shutil.copy2(input_dir / 'sample.jpg', output_dir / 'sample.jpg')
    shutil.copy2(input_dir / 'sample.png', output_dir / 'sample.png')

    monkeypatch.setattr(messagebox, 'askyesno', lambda *args, **kwargs: True)
    monkeypatch.setattr(messagebox, 'showerror', lambda *args, **kwargs: None)
    app.cleanup_output()
    wait_threads(app)
    assert not (output_dir / 'sample.jpg').exists()
    assert not (output_dir / 'sample.png').exists()

    app.input_dir.set(str(input_dir))
    app.output_dir.set(str(input_dir))
    monkeypatch.setattr(messagebox, 'showwarning', lambda *args, **kwargs: None)
    app._validate_and_fix_dirs()
    assert app.input_dir.get() != app.output_dir.get()


def test_zip_matrix_full_regression(tk_regression_app) -> None:
    app, input_dir, output_dir = tk_regression_app
    app.input_dir.set(str(input_dir))
    app.output_dir.set(str(output_dir))
    app.csv_path.set(str(output_dir / 'zip_cases.csv'))

    run_zip_matrix_tests(app, input_dir, output_dir)


def test_app_settings_tab_is_built_with_sound_toggles(tk_regression_app) -> None:
    app, _input_dir, _output_dir = tk_regression_app

    assert len(app.notebook.tabs()) == 3
    assert app.play_startup_sound.get() is True
    assert app.play_cleanup_sound.get() is True