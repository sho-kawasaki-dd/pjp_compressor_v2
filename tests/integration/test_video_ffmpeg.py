from __future__ import annotations

"""実 ffmpeg / ffprobe を使う動画圧縮の統合テスト。

採用ビルドで保持条件・出力検証・元維持の配置を確認する。ツールが無い環境ではスキップする。
"""

import subprocess
import threading
import time
from pathlib import Path

import pytest

from backend import capabilities
from backend.contracts import JobControl, VideoCompressionConfig
from backend.core.video_utils import compress_video_ffmpeg, terminate_active_video_processes

pytestmark = [pytest.mark.integration, pytest.mark.requires_external]


@pytest.fixture
def caps():
    report = capabilities.detect_capabilities()
    if not report.video_available:
        pytest.skip('ffmpeg / ffprobe is not available')
    return report


def _ffmpeg(caps, *args: str) -> None:
    subprocess.run(
        [caps.ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-y', *args],
        check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


def _make_sample(
    caps, tmp_path: Path, name: str = 'src.mp4', *, size: str = '320x240', pix_fmt: str = 'yuv420p', with_extras: bool = True
) -> Path:
    out = tmp_path / name
    meta = tmp_path / 'meta.txt'
    meta.write_text(
        ';FFMETADATA1\n'
        '[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Intro\n'
        '[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Main\n',
        encoding='utf-8',
    )
    srt = tmp_path / 's.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n', encoding='utf-8')
    args = [
        '-f', 'lavfi', '-i', f'testsrc=size={size}:rate=25:duration=2',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2',
        '-i', str(srt), '-i', str(meta),
        '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:s',
        '-c:v', 'libx264', '-b:v', '6M', '-pix_fmt', pix_fmt,
        '-c:a:0', 'aac', '-c:a:1', 'mp3', '-c:s', 'mov_text',
        '-metadata:s:a:0', 'language=jpn', '-metadata:s:a:0', 'title=Main audio',
        '-metadata:s:a:1', 'language=eng', '-metadata:s:a:1', 'title=Commentary',
        '-disposition:a:0', '0', '-disposition:a:1', 'default',
        '-metadata', 'creation_time=2024-01-02T03:04:05Z',
    ]
    if with_extras:
        args += ['-map_metadata', '4', '-map_chapters', '4']
    _ffmpeg(caps, *args, str(out))
    return out


def _run(caps, src: Path, tmp_path: Path, *, config: VideoCompressionConfig | None = None, control: JobControl | None = None, progress=None):
    work = tmp_path / '.pjp_work' / 'video' / 'job'
    out_dir = tmp_path / 'out'
    result = compress_video_ffmpeg(
        str(src),
        str(out_dir / (src.stem + '.mp4')),
        str(out_dir / src.name),
        config or VideoCompressionConfig(crf=35, preset='ultrafast'),
        capabilities=caps,
        job_control=control or JobControl(),
        temp_dir=work,
        progress_callback=progress,
        log_language='en',
    )
    return result, out_dir, work


def test_preservable_input_is_compressed_to_mp4(caps, tmp_path: Path) -> None:
    src = _make_sample(caps, tmp_path)
    reports: list[int | None] = []

    result, out_dir, work = _run(caps, src, tmp_path, progress=reports.append)

    assert result.ok, result.message
    assert not result.kept_original, result.notes
    assert result.final_outpath == str(out_dir / 'src.mp4')
    assert Path(result.final_outpath).stat().st_size < src.stat().st_size
    assert not any(work.glob('*')), 'temporary files must be removed'
    assert all(p is None or 0 <= p <= 99 for p in reports)


def test_odd_sized_mov_is_converted_to_mp4(caps, tmp_path: Path) -> None:
    mp4 = _make_sample(caps, tmp_path, 'base.mp4', size='321x241', pix_fmt='yuv444p', with_extras=False)
    mov = tmp_path / 'clip.mov'
    _ffmpeg(caps, '-i', str(mp4), '-map', '0:v', '-map', '0:a', '-c', 'copy', str(mov))

    result, out_dir, _ = _run(caps, mov, tmp_path)

    assert result.ok, result.message
    assert not result.kept_original, result.notes
    assert result.final_outpath == str(out_dir / 'clip.mp4')


def test_audio_only_input_keeps_original_with_original_extension(caps, tmp_path: Path) -> None:
    src = tmp_path / 'audio.m4v'
    _ffmpeg(caps, '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', 'aac', '-f', 'mp4', str(src))

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and result.kept_original
    assert result.kept_original_reason == 'retention'
    assert 'no_primary_video' in result.notes
    assert result.final_outpath == str(out_dir / 'audio.m4v')
    assert (out_dir / 'audio.m4v').read_bytes() == src.read_bytes()


def test_non_mov_text_subtitle_keeps_original(caps, tmp_path: Path) -> None:
    srt = tmp_path / 's.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n', encoding='utf-8')
    src = tmp_path / 'sub.mkv'
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=25:duration=1', '-i', str(srt),
        '-c:v', 'libx264', '-c:s', 'srt', str(src),
    )

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert any(note.startswith('subtitle_not_mov_text') for note in result.notes)
    assert (out_dir / 'sub.mkv').read_bytes() == src.read_bytes()


def test_output_not_smaller_keeps_original(caps, tmp_path: Path) -> None:
    src = tmp_path / 'tiny.mp4'
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5:duration=1',
        '-c:v', 'libx264', '-crf', '51', '-preset', 'veryslow', str(src),
    )

    result, out_dir, _ = _run(caps, src, tmp_path, config=VideoCompressionConfig(crf=10, preset='ultrafast'))

    assert result.ok and result.kept_original and result.kept_original_reason == 'no_gain'
    assert result.final_outpath == str(out_dir / 'tiny.mp4')
    assert (out_dir / 'tiny.mp4').read_bytes() == src.read_bytes()


def test_ffmpeg_failure_is_reported_without_leftovers(caps, tmp_path: Path) -> None:
    src = tmp_path / 'broken.mp4'
    src.write_bytes(b'not a video')

    result, out_dir, work = _run(caps, src, tmp_path)

    assert not result.ok and not result.cancelled
    assert result.final_outpath is None
    assert not out_dir.exists() or not any(out_dir.iterdir())


def test_cancel_before_start_does_nothing(caps, tmp_path: Path) -> None:
    src = _make_sample(caps, tmp_path)
    control = JobControl()
    control.request_cancel()

    result, out_dir, _ = _run(caps, src, tmp_path, control=control)

    assert result.cancelled and not result.ok
    assert not out_dir.exists()


def test_stop_during_encode_terminates_ffmpeg_and_cleans_up(caps, tmp_path: Path) -> None:
    src = tmp_path / 'long.mp4'
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=120',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30', str(src),
    )
    control = JobControl()
    outcome: dict[str, object] = {}

    def worker() -> None:
        outcome['result'] = _run(caps, src, tmp_path, config=VideoCompressionConfig(crf=18, preset='veryslow'), control=control)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any('-progress' in (proc.args or []) for proc in control.snapshot()):
            break
        time.sleep(0.05)
    else:
        control.request_cancel()
        thread.join()
        pytest.fail('ffmpeg encode did not start')

    terminate_active_video_processes(control)
    thread.join(timeout=30)

    assert not thread.is_alive()
    result, out_dir, work = outcome['result']  # type: ignore[misc]
    assert result.cancelled and not result.ok
    assert control.snapshot() == ()
    assert not out_dir.exists() or not any(out_dir.iterdir())
    assert not work.exists() or not any(work.iterdir())
