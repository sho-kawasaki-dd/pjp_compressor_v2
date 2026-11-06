from __future__ import annotations

import io
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageCms, ImageOps, features

from backend.contracts import ImageCompressionConfig, JobControl
from backend.core import image_utils, job_files
from backend.orchestrator.job_lock import acquire_output_lock
from backend.settings import IMAGE_WORK_OWNER_TOKEN, IMAGE_WORK_SUBDIR, VIDEO_WORK_OWNER_MARKER


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ('config', 'expected', 'resized'),
    [
        (None, (80, 40), False),
        ({'enabled': False, 'width': 20}, (80, 40), False),
        ({'enabled': True, 'mode': 'long_edge', 'long_edge': 20}, (20, 10), True),
        ({'enabled': True, 'mode': 'long_edge', 'long_edge': 0}, (80, 40), False),
        ({'enabled': True, 'width': 30, 'height': 30, 'keep_aspect': True}, (30, 15), True),
        ({'enabled': True, 'width': 30, 'keep_aspect': True}, (30, 15), True),
        ({'enabled': True, 'height': 15, 'keep_aspect': True}, (30, 15), True),
        ({'enabled': True, 'width': 30, 'height': 35, 'keep_aspect': False}, (30, 35), True),
        ({'enabled': True, 'height': 13, 'keep_aspect': False}, (80, 13), True),
        ({'enabled': True, 'width': 0, 'height': 0}, (80, 40), False),
    ],
)
def test_resize_preserves_pillow_and_pngquant_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config,
    expected: tuple[int, int],
    resized: bool,
) -> None:
    source = tmp_path / 'source.png'
    Image.new('RGB', (80, 40), 'red').save(source)
    pillow_out = tmp_path / 'pillow.png'
    pngquant_out = tmp_path / 'quant.png'
    quant_sizes: list[tuple[int, int]] = []

    def fake_run(cmd, **_kwargs):
        with Image.open(cmd[-1]) as image:
            quant_sizes.append(image.size)
        Path(cmd[5]).write_bytes(b'quantized')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(image_utils, 'resolve_pngquant_executable', lambda: SimpleNamespace(available=True, source='system', path='pngquant'))
    monkeypatch.setattr(image_utils.subprocess, 'run', fake_run)

    pillow_ok, pillow_message = image_utils.compress_image_pillow(source, pillow_out, 70, resize_cfg=config)
    quant_ok, quant_message = image_utils.compress_png_pngquant(source, pngquant_out, 50, 70, resize_cfg=config)

    assert pillow_ok and quant_ok
    with Image.open(pillow_out) as image:
        assert image.size == expected
    assert quant_sizes == [expected]
    assert ('resize=' in pillow_message) is bool(config and config.get('enabled'))
    assert ('resize=' in quant_message) is resized
    assert not pngquant_out.with_suffix('.png.tmp_resize.png').exists()


def test_conversion_orients_before_resize_and_preserves_exif_and_rgb_icc(tmp_path: Path) -> None:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = 'metadata retained'
    source = tmp_path / 'oriented.png'
    image = Image.new('RGB', (4, 2), 'white')
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((3, 1), (0, 0, 255))
    image.save(source, exif=exif, icc_profile=profile)

    with Image.open(source) as opened:
        prepared, metadata = image_utils._prepare_image_for_conversion(opened)
        resized, _ = image_utils._prepare_image_for_conversion(
            opened,
            {'enabled': True, 'width': 6, 'keep_aspect': True},
        )

    assert prepared.size == (2, 4)
    assert prepared.getpixel((1, 0)) == (255, 0, 0)
    assert prepared.getpixel((0, 3)) == (0, 0, 255)
    assert resized.size == (6, 12)
    assert metadata['icc_profile'] == profile
    output = tmp_path / 'prepared.png'
    prepared.save(output, **metadata)
    with Image.open(output) as saved:
        assert saved.getexif().get(274, 1) == 1
        assert saved.getexif()[270] == 'metadata retained'
        assert saved.info['icc_profile'] == profile
        assert ImageOps.exif_transpose(saved).tobytes() == saved.tobytes()


def test_cmyk_conversion_discards_incompatible_icc_on_actual_save() -> None:
    source = Image.new('CMYK', (5, 3), (0, 20, 40, 0))
    source.info['icc_profile'] = b'not-an-rgb-profile'

    prepared, metadata = image_utils._prepare_image_for_conversion(source)

    assert prepared.mode == 'RGB'
    assert 'icc_profile' not in metadata
    assert 'icc_profile' not in prepared.info
    formats = ['JPEG', 'PNG']
    if features.check('avif'):
        formats.append('AVIF')
    for format_name in formats:
        buffer = io.BytesIO()
        prepared.save(buffer, format=format_name, **metadata)
        buffer.seek(0)
        with Image.open(buffer) as saved:
            assert 'icc_profile' not in saved.info


@pytest.mark.parametrize('format_name', ['JPEG', 'PNG', 'AVIF'])
def test_conversion_metadata_round_trips_in_supported_output_formats(format_name: str) -> None:
    if format_name == 'AVIF' and not features.check('avif'):
        pytest.skip('Pillow has no AVIF support')
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = 'metadata retained'
    source = Image.new('RGB', (12, 6), 'green')
    source.info['exif'] = exif.tobytes()
    source.info['icc_profile'] = profile
    prepared, metadata = image_utils._prepare_image_for_conversion(source)

    buffer = io.BytesIO()
    prepared.save(buffer, format=format_name, **metadata)
    buffer.seek(0)
    with Image.open(buffer) as saved:
        assert saved.size == (6, 12)
        assert saved.getexif().get(274, 1) == 1
        assert saved.getexif()[270] == 'metadata retained'
        assert saved.info['icc_profile'] == profile
        assert ImageOps.exif_transpose(saved).size == saved.size


def test_legacy_jpeg_compression_does_not_apply_new_orientation_handling(tmp_path: Path) -> None:
    source = tmp_path / 'input.jpg'
    dest = tmp_path / 'output.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (40, 20), 'red').save(source, exif=exif)

    ok, _message = image_utils.compress_image_pillow(source, dest, 70)

    assert ok
    with Image.open(dest) as saved:
        assert saved.size == (40, 20)
        assert 274 not in saved.getexif()


@pytest.mark.parametrize(
    ('extension', 'config', 'expected'),
    [
        ('JPG', ImageCompressionConfig(), None),
        ('.jpg', ImageCompressionConfig(output_format='avif'), '.avif'),
        ('JPEG', ImageCompressionConfig(output_format='avif'), '.avif'),
        ('png', ImageCompressionConfig(output_format='avif'), None),
        ('png', ImageCompressionConfig(output_format='avif', avif_include_png=True), '.avif'),
        ('avif', ImageCompressionConfig(avif_to_jpeg_compat=True), '.jpg'),
        ('jpg', ImageCompressionConfig(avif_to_jpeg_compat=True), None),
    ],
)
def test_converted_extension_uses_image_config(extension, config, expected) -> None:
    assert image_utils.converted_image_extension(extension, config) == expected


@pytest.fixture
def image_workspace(tmp_path: Path):
    output = tmp_path / 'output'
    with acquire_output_lock(output):
        work = image_utils.create_image_job_dir(output)
        yield output, work


@pytest.mark.parametrize('encoded_size', [100, 101])
def test_conversion_keeps_original_when_output_is_not_smaller(image_workspace, tmp_path: Path, encoded_size: int) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b's' * 100)
    dest = output / 'photo.avif'
    dest.write_bytes(b'previous converted output')
    seen: list[Path] = []

    def encode(path: Path) -> image_utils.ImageEncodeOutcome:
        seen.append(path)
        path.write_bytes(b'c' * encoded_size)
        return image_utils.ImageEncodeOutcome('encoded', notes=('encoder_note',))

    result = image_utils.save_converted_image(
        source, dest, output / source.name, encode=encode, keep_if_not_smaller=True,
        job_control=JobControl(), temp_dir=work,
    )

    assert result.ok and result.kept_original and result.kept_original_reason == 'no_gain'
    assert result.final_outpath == str(output / source.name)
    assert result.notes == ('encoder_note',)
    assert (output / source.name).read_bytes() == source.read_bytes()
    assert dest.read_bytes() == b'previous converted output'
    assert re.fullmatch(r'\.pjp_tmp_[0-9a-f]{32}\.avif', seen[0].name)
    assert not list(work.glob('.pjp_tmp_*'))


def test_compat_conversion_keeps_larger_output_and_records_note(image_workspace, tmp_path: Path) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.avif'
    source.write_bytes(b's' * 20)

    def encode(path: Path) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'c' * 50)
        return image_utils.ImageEncodeOutcome('converted', notes=('compat_conversion',))

    dest = output / 'photo.jpg'
    result = image_utils.save_converted_image(
        source, dest, output / source.name, encode=encode, keep_if_not_smaller=False,
        job_control=JobControl(), temp_dir=work,
    )

    assert result.ok and not result.kept_original and result.final_outpath == str(dest)
    assert result.notes == ('compat_conversion', 'size_increased')
    assert dest.read_bytes() == b'c' * 50
    assert not list(work.glob('.pjp_tmp_*'))


def test_published_temporary_files_are_not_reported_as_cleanup_failures(
    image_workspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b's' * 100)
    real_unlink = Path.unlink

    def fail_temp_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.parent == work and self.name.startswith('.pjp_tmp_'):
            raise PermissionError('should not unlink a published file')
        real_unlink(self, missing_ok=missing_ok)

    def encode(path: Path) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'c' * 10)
        return image_utils.ImageEncodeOutcome('encoded')

    monkeypatch.setattr(Path, 'unlink', fail_temp_unlink)
    result = image_utils.save_converted_image(
        source, output / 'photo.avif', output / source.name,
        encode=encode, keep_if_not_smaller=True, job_control=JobControl(), temp_dir=work,
    )
    copied = image_utils.place_image_original_copy(source, output / source.name, work, JobControl())

    assert result.ok and result.notes == () and copied
    assert (output / 'photo.avif').read_bytes() == b'c' * 10
    assert (output / source.name).read_bytes() == source.read_bytes()


def test_retention_uses_original_extension_without_requiring_encoded_file(image_workspace, tmp_path: Path) -> None:
    output, work = image_workspace
    source = tmp_path / 'animated.avif'
    source.write_bytes(b'animated')
    dest = output / 'animated.jpg'
    result = image_utils.save_converted_image(
        source, dest, output / source.name,
        encode=lambda _path: image_utils.ImageEncodeOutcome('retain', retention=True, notes=('animated_avif',)),
        keep_if_not_smaller=False, job_control=JobControl(), temp_dir=work,
    )

    assert result.ok and result.kept_original_reason == 'retention'
    assert result.notes == ('animated_avif',)
    assert result.final_outpath == str(output / source.name)
    assert (output / source.name).read_bytes() == source.read_bytes()
    assert not dest.exists()
    assert not list(work.glob('.pjp_tmp_*'))


def test_conversion_rejects_wrong_original_extension_without_encoding(image_workspace, tmp_path: Path) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'original')
    encoded: list[Path] = []
    result = image_utils.save_converted_image(
        source, output / 'photo.avif', output / 'wrong.avif',
        encode=lambda path: encoded.append(path) or image_utils.ImageEncodeOutcome('encoded'),
        keep_if_not_smaller=True, job_control=JobControl(), temp_dir=work, log_language='en',
    )

    assert not result.ok and 'correct extensions' in result.message
    assert encoded == [] and not (output / 'wrong.avif').exists()
    with pytest.raises(ValueError, match='retain the input extension'):
        image_utils.place_image_original_copy(source, output / 'wrong.avif', work, JobControl())


def test_conversion_rejects_unowned_temp_directory(image_workspace, tmp_path: Path) -> None:
    output, _work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'original')
    unowned = output / '.pjp_work' / IMAGE_WORK_SUBDIR / 'unowned'
    unowned.mkdir()
    (unowned / 'user.txt').write_text('keep', encoding='utf-8')
    encoded: list[Path] = []

    result = image_utils.save_converted_image(
        source, output / 'photo.avif', output / source.name,
        encode=lambda path: encoded.append(path) or image_utils.ImageEncodeOutcome('encoded'),
        keep_if_not_smaller=True, job_control=JobControl(), temp_dir=unowned, log_language='en',
    )

    assert not result.ok and 'ownership could not be verified' in result.message
    assert encoded == [] and not (output / 'photo.avif').exists()
    assert (unowned / 'user.txt').read_text(encoding='utf-8') == 'keep'
    assert list(unowned.iterdir()) == [unowned / 'user.txt']


@pytest.mark.parametrize('empty_file', [False, True])
def test_missing_or_empty_encoded_image_is_a_failure(
    image_workspace,
    tmp_path: Path,
    empty_file: bool,
) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'original')
    dest = output / 'photo.avif'
    dest.write_bytes(b'previous result')

    def encode(path: Path) -> image_utils.ImageEncodeOutcome:
        if empty_file:
            path.write_bytes(b'')
        return image_utils.ImageEncodeOutcome('reported success')

    result = image_utils.save_converted_image(
        source, dest, output / source.name, encode=encode, keep_if_not_smaller=True,
        job_control=JobControl(), temp_dir=work, log_language='en',
    )

    assert not result.ok and result.final_outpath is None
    assert 'did not produce an output file' in result.message
    assert dest.read_bytes() == b'previous result'
    assert not list(work.glob('.pjp_tmp_*'))


def test_cancel_after_encoding_preserves_existing_outputs(image_workspace, tmp_path: Path) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b's' * 100)
    dest = output / 'photo.avif'
    dest.write_bytes(b'previous')
    control = JobControl()

    def encode(path: Path) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'new')
        control.request_cancel()
        return image_utils.ImageEncodeOutcome('encoded')

    result = image_utils.save_converted_image(
        source, dest, output / source.name, encode=encode, keep_if_not_smaller=True,
        job_control=control, temp_dir=work,
    )

    assert result.cancelled and not result.ok and result.final_outpath is None
    assert dest.read_bytes() == b'previous'
    assert not (output / source.name).exists()
    assert not list(work.glob('.pjp_tmp_*'))


def test_temp_deletion_failure_is_reported_in_image_result(
    image_workspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'original')
    real_unlink = Path.unlink

    def fail_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.parent == work and self.name.startswith('.pjp_tmp_'):
            raise PermissionError('temporary file locked')
        real_unlink(self, missing_ok=missing_ok)

    def fail_encode(path: Path) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'partial')
        raise OSError('encoding failed')

    monkeypatch.setattr(Path, 'unlink', fail_unlink)
    result = image_utils.save_converted_image(
        source, output / 'photo.avif', output / source.name,
        encode=fail_encode, keep_if_not_smaller=True, job_control=JobControl(), temp_dir=work,
        log_language='en',
    )

    assert not result.ok and result.final_outpath is None
    assert 'encoding failed' in result.message and 'temporary file locked' in result.message
    assert 'temp_delete_failed' in result.notes


def test_parallel_image_staging_uses_unique_paths(image_workspace, tmp_path: Path) -> None:
    output, work = image_workspace
    control = JobControl()
    barrier = threading.Barrier(8)
    staged_paths: list[Path] = []

    def run(index: int) -> image_utils.ImageCompressResult:
        source = tmp_path / f'{index}.jpg'
        source.write_bytes(b's' * 100)

        def encode(path: Path) -> image_utils.ImageEncodeOutcome:
            staged_paths.append(path)
            path.write_bytes(b'c' * 10)
            barrier.wait(timeout=10)
            return image_utils.ImageEncodeOutcome('encoded')

        return image_utils.save_converted_image(
            source, output / f'{index}.avif', output / source.name,
            encode=encode, keep_if_not_smaller=True, job_control=control, temp_dir=work,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(run, range(8)))

    assert all(result.ok for result in results)
    assert len(set(staged_paths)) == 8
    assert all(path.parent == work for path in staged_paths)
    assert all((output / f'{index}.avif').read_bytes() == b'c' * 10 for index in range(8))
    assert not list(work.glob('.pjp_tmp_*'))


def test_publish_and_cancel_are_serialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    staged = tmp_path / 'staged'
    staged.write_bytes(b'new')
    dest = tmp_path / 'output'
    dest.write_bytes(b'old')
    control = JobControl()
    replacing = threading.Event()
    release = threading.Event()
    cancel_returned = threading.Event()
    original_replace = Path.replace

    def delayed_replace(self: Path, target: Path):
        if self == staged:
            replacing.set()
            assert release.wait(timeout=10)
        return original_replace(self, target)

    def cancel() -> None:
        control.request_cancel()
        cancel_returned.set()

    monkeypatch.setattr(Path, 'replace', delayed_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        publish_future = executor.submit(job_files.publish, staged, dest, control)
        try:
            assert replacing.wait(timeout=10)
            cancel_future = executor.submit(cancel)
            assert not cancel_returned.wait(timeout=0.1)
        finally:
            release.set()
        publish_future.result(timeout=10)
        cancel_future.result(timeout=10)

    assert cancel_returned.is_set() and control.is_cancelled
    assert dest.read_bytes() == b'new'
    other = tmp_path / 'other'
    other.write_bytes(b'later')
    with pytest.raises(job_files.JobCancelled):
        job_files.publish(other, dest, control)
    assert dest.read_bytes() == b'new'


def test_cancel_before_fallback_copy_start_prevents_opening_input(
    image_workspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, work = image_workspace
    source = tmp_path / 'source.jpg'
    source.write_bytes(b'original')
    control = JobControl()
    ready = threading.Event()
    release = threading.Event()
    input_opens: list[str] = []
    original_temp_path = job_files.temp_path
    real_open = open

    def delayed_temp_path(directory: Path, suffix: str) -> Path:
        path = original_temp_path(directory, suffix)
        ready.set()
        assert release.wait(timeout=10)
        return path

    def tracked_open(path, mode='r', *args, **kwargs):
        if Path(path) == source:
            input_opens.append(mode)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(job_files, 'temp_path', delayed_temp_path)
    monkeypatch.setattr('builtins.open', tracked_open)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(job_files.place_original_copy, source, output / source.name, work, control)
        try:
            assert ready.wait(timeout=10)
            control.request_cancel()
        finally:
            release.set()
        assert future.result(timeout=10) is False

    assert input_opens == []
    assert not (output / source.name).exists()
    assert not list(work.glob('.pjp_tmp_*'))


def test_stale_cleanup_removes_only_owned_image_job_dirs(tmp_path: Path) -> None:
    output = tmp_path / 'output'
    with acquire_output_lock(output):
        owned = image_utils.create_image_job_dir(output, 'owned')
        (owned / '.pjp_tmp_123.avif').write_bytes(b'temporary')
        image_root = output / '.pjp_work' / IMAGE_WORK_SUBDIR
        unknown = image_root / 'unknown'
        unknown.mkdir()
        (unknown / '.pjp_tmp_unknown').write_bytes(b'keep')
        wrong = image_root / 'wrong'
        wrong.mkdir()
        (wrong / VIDEO_WORK_OWNER_MARKER).write_text('not ours', encoding='utf-8')
        stray = image_root / '.pjp_tmp_stray'
        stray.write_bytes(b'keep')
        outside = output / '.pjp_tmp_user'
        outside.write_bytes(b'keep')

        assert image_utils.cleanup_stale_image_temps(output) == 1

    assert not owned.exists()
    assert (unknown / '.pjp_tmp_unknown').read_bytes() == b'keep'
    assert wrong.exists() and stray.exists() and outside.exists()


def test_work_directory_creation_does_not_claim_existing_directory(tmp_path: Path) -> None:
    output = tmp_path / 'output'
    with acquire_output_lock(output):
        existing = output / '.pjp_work' / IMAGE_WORK_SUBDIR / 'existing'
        existing.mkdir(parents=True)
        (existing / 'user.txt').write_text('keep', encoding='utf-8')
        with pytest.raises(FileExistsError):
            image_utils.create_image_job_dir(output, 'existing')
        assert not (existing / VIDEO_WORK_OWNER_MARKER).exists()
        assert (existing / 'user.txt').read_text(encoding='utf-8') == 'keep'


def _create_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            pytest.skip('directory link creation is not permitted')
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        if result.returncode != 0:
            pytest.skip('directory link creation is not permitted')


def test_image_workspace_does_not_create_or_cleanup_through_directory_link(tmp_path: Path) -> None:
    output = tmp_path / 'output'
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / '.pjp_tmp_user').write_bytes(b'keep')
    with acquire_output_lock(output):
        image_root = output / '.pjp_work' / IMAGE_WORK_SUBDIR
        _create_directory_link(image_root, outside)
        with pytest.raises(OSError, match='work directory is a link'):
            image_utils.create_image_job_dir(output)
        assert image_utils.cleanup_stale_image_temps(output) == 0
    assert (outside / '.pjp_tmp_user').read_bytes() == b'keep'
    assert list(outside.iterdir()) == [outside / '.pjp_tmp_user']


def test_output_lock_rejects_linked_work_directory_without_touching_target(tmp_path: Path) -> None:
    output = tmp_path / 'output'
    output.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    _create_directory_link(output / '.pjp_work', outside)

    with pytest.raises(OSError, match='work directory is a link'):
        acquire_output_lock(output)

    assert list(outside.iterdir()) == []


def test_conversion_does_not_publish_through_output_directory_link(image_workspace, tmp_path: Path) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'original')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'user.txt').write_text('keep', encoding='utf-8')
    _create_directory_link(output / 'linked', outside)
    encoded: list[Path] = []

    result = image_utils.save_converted_image(
        source, output / 'linked' / 'photo.avif', output / 'linked' / source.name,
        encode=lambda path: encoded.append(path) or image_utils.ImageEncodeOutcome('encoded'),
        keep_if_not_smaller=True, job_control=JobControl(), temp_dir=work, log_language='en',
    )

    assert not result.ok and 'outside the output folder' in result.message
    assert encoded == []
    assert (outside / 'user.txt').read_text(encoding='utf-8') == 'keep'
    assert list(outside.iterdir()) == [outside / 'user.txt']


def test_image_workspace_rejects_a_different_filesystem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / 'output'
    with acquire_output_lock(output):
        image_root = output / '.pjp_work' / IMAGE_WORK_SUBDIR
        image_root.mkdir()
        original_stat = Path.stat

        def fake_stat(path: Path, *args, **kwargs):
            stat = original_stat(path, *args, **kwargs)
            if path == image_root and kwargs.get('follow_symlinks', True):
                return SimpleNamespace(st_dev=stat.st_dev + 1, st_mode=stat.st_mode)
            return stat

        monkeypatch.setattr(Path, 'stat', fake_stat)
        with pytest.raises(OSError, match='different filesystem'):
            image_utils.create_image_job_dir(output)
        assert list(image_root.iterdir()) == []


def test_conversion_rejects_output_directory_on_a_different_filesystem(
    image_workspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, work = image_workspace
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'original')
    mounted = output / 'mounted'
    mounted.mkdir()
    encoded: list[Path] = []
    original_stat = Path.stat

    def fake_stat(path: Path, *args, **kwargs):
        stat = original_stat(path, *args, **kwargs)
        if path == mounted and kwargs.get('follow_symlinks', True):
            return SimpleNamespace(st_dev=stat.st_dev + 1, st_mode=stat.st_mode)
        return stat

    monkeypatch.setattr(Path, 'stat', fake_stat)
    result = image_utils.save_converted_image(
        source, mounted / 'photo.avif', mounted / source.name,
        encode=lambda path: encoded.append(path) or image_utils.ImageEncodeOutcome('encoded'),
        keep_if_not_smaller=True, job_control=JobControl(), temp_dir=work, log_language='en',
    )

    assert not result.ok and 'different filesystem' in result.message
    assert encoded == [] and list(mounted.iterdir()) == []
    assert not list(work.glob('.pjp_tmp_*'))


def test_work_directory_removal_rechecks_ownership(image_workspace) -> None:
    output, work = image_workspace
    (work / 'user.txt').write_text('keep', encoding='utf-8')
    (work / VIDEO_WORK_OWNER_MARKER).write_text('ownership changed', encoding='utf-8')

    with pytest.raises(OSError, match='ownership could not be verified'):
        job_files.remove_owned_job_dir(output, IMAGE_WORK_SUBDIR, work, IMAGE_WORK_OWNER_TOKEN)

    assert (work / 'user.txt').read_text(encoding='utf-8') == 'keep'


def test_stale_cleanup_surfaces_deletion_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / 'output'
    with acquire_output_lock(output):
        owned = image_utils.create_image_job_dir(output, 'owned')
        original_rmtree = job_files.shutil.rmtree

        def fail_for_owned(path, *args, **kwargs):
            if Path(path) == owned:
                raise PermissionError('locked work directory')
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(job_files.shutil, 'rmtree', fail_for_owned)
        with pytest.raises(PermissionError, match='locked work directory'):
            image_utils.cleanup_stale_image_temps(output)
        assert owned.exists()
