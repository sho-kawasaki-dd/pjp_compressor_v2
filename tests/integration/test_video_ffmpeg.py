from __future__ import annotations

"""実 ffmpeg / ffprobe を使う動画圧縮の統合テスト。

採用ビルドで保持条件・出力検証・元維持の配置を確認する。ツールが無い環境ではスキップする。
"""

import csv
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest

from backend import capabilities
from backend.contracts import JobControl, VideoCompressionConfig
from backend.core.video_utils import VideoCompressResult, compress_video_ffmpeg, terminate_active_video_processes, tool_unavailable_reason
from backend.orchestrator import job_runner
from shared.locale_catalog import translate

pytestmark = [pytest.mark.integration, pytest.mark.requires_external]


@pytest.fixture
def caps():
    report = capabilities.detect_capabilities()
    if not report.video_available:
        pytest.skip(tool_unavailable_reason(report, VideoCompressionConfig(), 'en') or 'video tools unavailable')
    if 'aac' not in report.ffmpeg_encoders:
        pytest.skip('ffmpeg AAC encoder is required for video fixtures')
    return report


def _require_encoder(caps, name: str) -> None:
    completed = subprocess.run(
        [caps.ffmpeg_path, '-hide_banner', '-encoders'],
        check=True,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    if not re.search(rf'(?m)^\s*[A-Z.]{{6}}\s+{re.escape(name)}\s', completed.stdout):
        pytest.skip(f'ffmpeg encoder {name} is unavailable')


def _require_option(caps, option: str) -> None:
    completed = subprocess.run(
        [caps.ffmpeg_path, '-hide_banner', '-h', 'full'],
        check=True,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    if option not in completed.stdout:
        pytest.skip(f'ffmpeg option {option} is unavailable')


def _ffmpeg(caps, *args: str) -> None:
    subprocess.run(
        [caps.ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-y', *args],
        check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


def _probe(caps, path: Path) -> dict:
    completed = subprocess.run(
        [caps.ffprobe_path, '-v', 'error', '-show_streams', '-show_chapters', '-show_format', '-of', 'json', str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding='utf-8',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    return json.loads(completed.stdout)


def _streams(probe: dict, kind: str) -> list[dict]:
    return [stream for stream in probe['streams'] if stream.get('codec_type') == kind]


def _decoded_audio(caps, path: Path, index: int) -> bytes:
    completed = subprocess.run(
        [
            caps.ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-i', str(path),
            '-map', f'0:a:{index}', '-c:a', 'pcm_s16le', '-f', 's16le', '-',
        ],
        check=True,
        capture_output=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    return completed.stdout


def _subtitle_text(caps, path: Path, index: int) -> str:
    completed = subprocess.run(
        [
            caps.ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-i', str(path),
            '-map', f'0:s:{index}', '-c:s', 'srt', '-f', 'srt', '-',
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding='utf-8',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    return completed.stdout.replace('\r\n', '\n')


def _make_video_only(caps, path: Path) -> Path:
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '4', '-pix_fmt', 'yuv420p',
        str(path),
    )
    return path


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
    assert result.final_outpath is not None
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
    output_video = _streams(_probe(caps, out_dir / 'clip.mp4'), 'video')[0]
    assert (output_video['width'], output_video['height']) == (320, 240)


def test_copy_mode_preserves_flac_and_converts_only_unlisted_track(caps, tmp_path: Path) -> None:
    _require_encoder(caps, 'flac')
    src = tmp_path / 'mixed.mkv'
    _ffmpeg(
        caps,
        '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2',
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=5.1:d=2',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
        '-map', '0:v', '-map', '1:a', '-map', '2:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '4', '-pix_fmt', 'yuv420p',
        '-c:a:0', 'flac', '-c:a:1', 'pcm_s16le',
        '-metadata:s:a:0', 'language=jpn', '-metadata:s:a:1', 'language=eng',
        '-disposition:a:0', 'default', '-disposition:a:1', '0',
        str(src),
    )
    input_audio = _streams(_probe(caps, src), 'audio')
    assert [stream['codec_name'] for stream in input_audio] == ['flac', 'pcm_s16le']

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and not result.kept_original, (result.message, result.notes)
    out = out_dir / 'mixed.mp4'
    output_audio = _streams(_probe(caps, out), 'audio')
    assert [stream['codec_name'] for stream in output_audio] == ['flac', 'aac']
    assert [stream['channels'] for stream in output_audio] == [6, 1]
    assert [stream['tags']['language'] for stream in output_audio] == ['jpn', 'eng']
    assert [stream['disposition']['default'] for stream in output_audio] == [1, 0]
    assert _decoded_audio(caps, src, 0) == _decoded_audio(caps, out, 0)
    assert result.notes == ('audio_aac_converted=a1:pcm_s16le->aac@96k',)
    assert 'AAC' in result.message and 'pcm_s16le' in result.message


def test_opus_is_converted_with_a_notice(caps, tmp_path: Path, sample_paths, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_encoder(caps, 'libopus')
    src = sample_paths.input_dir / 'opus.mkv'
    _ffmpeg(
        caps,
        '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
        '-map', '0:v', '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '4', '-pix_fmt', 'yuv420p',
        '-c:a', 'libopus', '-metadata:s:a:0', 'language=eng', str(src),
    )
    assert _streams(_probe(caps, src), 'audio')[0]['codec_name'] == 'opus'

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and not result.kept_original, (result.message, result.notes)
    assert _streams(_probe(caps, out_dir / 'opus.mp4'), 'audio')[0]['codec_name'] == 'aac'
    assert result.notes == ('audio_aac_converted=a0:opus->aac@96k',)
    assert 'AAC' in result.message and 'opus' in result.message

    logs: list[str] = []
    monkeypatch.setattr(job_runner, 'detect_capabilities', lambda: caps)
    job_runner.run_compression_job(
        input_dir=str(sample_paths.input_dir), output_dir=str(sample_paths.output_dir),
        jpg_quality=70, png_quality=70, use_pngquant=False, log_func=logs.append,
        progress_func=lambda _current, _total: None, stats_func=lambda _orig, _out, _saved, _pct: None,
        csv_enable=True, csv_path=str(sample_paths.csv_path), log_language='en',
        video_config=VideoCompressionConfig(crf=35, preset='ultrafast'),
    )
    notice = translate('en', 'video_audio_aac_converted', tracks='a0:opus->aac@96k')
    assert any(notice in message for message in logs)
    with sample_paths.csv_path.open(newline='', encoding='utf-8') as handle:
        (row,) = list(csv.DictReader(handle))
    assert row[translate('en', 'csv_header_action')] == translate('en', 'csv_action_video')
    assert row[translate('en', 'csv_header_output_path')] == 'opus.mp4'
    assert row[translate('en', 'csv_header_notes')] == result.notes[0]
    assert _streams(_probe(caps, sample_paths.output_dir / 'opus.mp4'), 'audio')[0]['codec_name'] == 'aac'


def test_audio_subtitles_chapters_and_metadata_survive(caps, tmp_path: Path) -> None:
    first = tmp_path / 'first.srt'
    second = tmp_path / 'second.srt'
    metadata = tmp_path / 'metadata.txt'
    first.write_text(
        '1\n00:00:00,200 --> 00:00:00,900\n<i>Hello</i>\n\n'
        '2\n00:00:01,100 --> 00:00:01,800\nSecond line\n',
        encoding='utf-8',
    )
    second.write_text('1\n00:00:00,400 --> 00:00:01,600\n<b>World</b>\n', encoding='utf-8')
    metadata.write_text(
        ';FFMETADATA1\ncreation_time=2024-01-02T03:04:05Z\nmake=PJP Test\nmodel=Synthetic Camera\n'
        '[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Intro\n'
        '[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Main\n',
        encoding='utf-8',
    )
    src = tmp_path / 'rich.mp4'
    _ffmpeg(
        caps,
        '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2',
        '-i', str(first), '-i', str(second), '-i', str(metadata),
        '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:s', '-map', '4:s',
        '-map_metadata', '5', '-map_chapters', '5',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '4', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-c:s', 'mov_text',
        '-metadata:s:a:0', 'language=jpn', '-metadata:s:a:1', 'language=eng',
        '-metadata:s:s:0', 'language=jpn', '-metadata:s:s:1', 'language=eng',
        '-metadata:s:a:0', 'title=Main audio', '-metadata:s:a:1', 'title=Commentary',
        '-metadata:s:s:0', 'title=Japanese subtitles', '-metadata:s:s:1', 'title=English subtitles',
        '-disposition:a:0', '0', '-disposition:a:1', 'default',
        '-disposition:s:0', '0', '-disposition:s:1', 'default',
        '-movflags', '+use_metadata_tags', str(src),
    )
    source_probe = _probe(caps, src)
    source_subtitles = [_subtitle_text(caps, src, index) for index in range(2)]
    assert '<i>Hello</i>' in source_subtitles[0] and '00:00:00,200' in source_subtitles[0]
    assert '<b>World</b>' in source_subtitles[1] and '00:00:00,400' in source_subtitles[1]

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and not result.kept_original, (result.message, result.notes)
    out = out_dir / 'rich.mp4'
    output_probe = _probe(caps, out)
    for kind, expected_titles in (
        ('audio', ['Main audio', 'Commentary']),
        ('subtitle', ['Japanese subtitles', 'English subtitles']),
    ):
        source_tracks = _streams(source_probe, kind)
        output_tracks = _streams(output_probe, kind)
        assert len(source_tracks) == len(output_tracks) == 2
        assert [stream['tags']['name'] for stream in source_tracks] == expected_titles
        assert [stream['tags']['name'] for stream in output_tracks] == expected_titles
        assert [stream['tags']['language'] for stream in output_tracks] == ['jpn', 'eng']
        assert [stream['disposition']['default'] for stream in output_tracks] == [0, 1]
        assert [stream['codec_name'] for stream in output_tracks] == [
            stream['codec_name'] for stream in source_tracks
        ]
    assert [_subtitle_text(caps, out, index) for index in range(2)] == source_subtitles
    assert len(source_probe['chapters']) == len(output_probe['chapters']) == 2
    for original, published in zip(source_probe['chapters'], output_probe['chapters']):
        assert original['tags']['title'] == published['tags']['title']
        assert abs(float(original['start_time']) - float(published['start_time'])) <= 0.010
    for key in ('creation_time', 'make', 'model'):
        assert source_probe['format']['tags'][key] == output_probe['format']['tags'][key]


def test_rotated_video_without_audio_or_subtitles_keeps_display_orientation(caps, tmp_path: Path) -> None:
    _require_option(caps, '-display_rotation')
    base = _make_video_only(caps, tmp_path / 'base.mp4')
    src = tmp_path / 'rotated.mov'
    _ffmpeg(caps, '-display_rotation:v:0', '90', '-i', str(base), '-map', '0:v:0', '-c', 'copy', str(src))
    input_video = _streams(_probe(caps, src), 'video')[0]
    assert abs(input_video['side_data_list'][0]['rotation']) == 90

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and not result.kept_original, (result.message, result.notes)
    output_probe = _probe(caps, out_dir / 'rotated.mp4')
    output_video = _streams(output_probe, 'video')[0]
    assert output_video['height'] > output_video['width']
    assert not output_video.get('side_data_list')
    assert _streams(output_probe, 'audio') == []
    assert _streams(output_probe, 'subtitle') == []


def test_cover_art_does_not_replace_the_primary_video(caps, tmp_path: Path) -> None:
    cover = tmp_path / 'cover.jpg'
    _ffmpeg(caps, '-f', 'lavfi', '-i', 'color=c=red:size=64x64', '-frames:v', '1', str(cover))
    src = tmp_path / 'covered.mp4'
    _ffmpeg(
        caps, '-i', str(cover), '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2',
        '-map', '0:v', '-map', '1:v', '-c:v:0', 'copy', '-disposition:v:0', 'attached_pic',
        '-c:v:1', 'libx264', '-preset', 'ultrafast', '-crf', '4', str(src),
    )
    source_video = _streams(_probe(caps, src), 'video')
    assert len(source_video) == 2 and sum(stream['disposition']['attached_pic'] for stream in source_video) == 1

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and not result.kept_original, (result.message, result.notes)
    output_video = _streams(_probe(caps, out_dir / 'covered.mp4'), 'video')
    assert len(output_video) == 1
    assert (output_video[0]['width'], output_video[0]['height']) == (320, 240)
    assert not output_video[0]['disposition']['attached_pic']


def test_timecode_data_is_dropped_and_reported(caps, tmp_path: Path) -> None:
    src = tmp_path / 'timecode.mov'
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=25:duration=2',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '4',
        '-timecode', '01:02:03:04', str(src),
    )
    assert any(stream['codec_tag_string'] == 'tmcd' for stream in _streams(_probe(caps, src), 'data'))

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and not result.kept_original, (result.message, result.notes)
    assert 'dropped_data_streams=tmcd' in result.notes
    assert not _streams(_probe(caps, out_dir / 'timecode.mp4'), 'data')


def test_unsupported_gpmd_data_keeps_original(caps, tmp_path: Path) -> None:
    data = tmp_path / 'data.bin'
    data.write_bytes(b'GPMF' + bytes(256))
    src = tmp_path / 'gpmd.mov'
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=10:duration=1',
        '-f', 'data', '-i', str(data), '-map', '0:v', '-map', '1:0',
        '-c:v', 'libx264', '-c:d', 'copy', '-tag:d', 'gpmd', str(src),
    )
    assert any(stream['codec_tag_string'] == 'gpmd' for stream in _streams(_probe(caps, src), 'data'))

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert 'unsupported_data_stream=gpmd' in result.notes
    assert (out_dir / src.name).read_bytes() == src.read_bytes()


def test_hevc_output_uses_hvc1_tag(caps, tmp_path: Path) -> None:
    if not caps.ffmpeg_hevc_available:
        pytest.skip('ffmpeg libx265 encoder is unavailable')
    src = _make_video_only(caps, tmp_path / 'hevc.mov')

    result, out_dir, _ = _run(
        caps, src, tmp_path, config=VideoCompressionConfig(codec='libx265', crf=35, preset='ultrafast'),
    )

    assert result.ok and not result.kept_original, (result.message, result.notes)
    output_video = _streams(_probe(caps, out_dir / 'hevc.mp4'), 'video')[0]
    assert output_video['codec_name'] == 'hevc'
    assert output_video['codec_tag_string'] == 'hvc1'


@pytest.mark.parametrize(
    ('pix_fmt', 'reason'),
    [('yuv420p10le', 'high_bit_depth'), ('yuv420p', 'hdr')],
)
def test_high_bit_depth_and_hdr_keep_original(caps, tmp_path: Path, pix_fmt: str, reason: str) -> None:
    src = tmp_path / f'{reason}.mkv'
    if reason == 'hdr':
        codec_args = ['-c:v', 'libx264', '-x264-params', 'colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc']
    else:
        _require_encoder(caps, 'ffv1')
        codec_args = ['-c:v', 'ffv1']
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=10:duration=1',
        *codec_args, '-pix_fmt', pix_fmt, str(src),
    )
    input_video = _streams(_probe(caps, src), 'video')[0]
    assert input_video['pix_fmt'] == pix_fmt
    if reason == 'hdr':
        assert input_video['color_transfer'] == 'smpte2084'

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert reason in result.notes
    assert (out_dir / src.name).read_bytes() == src.read_bytes()


def test_forced_mov_text_subtitle_keeps_original(caps, tmp_path: Path) -> None:
    subtitle = tmp_path / 'forced.srt'
    subtitle.write_text('1\n00:00:00,000 --> 00:00:00,800\nforced\n', encoding='utf-8')
    src = tmp_path / 'forced.mp4'
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=10:duration=1', '-i', str(subtitle),
        '-map', '0:v', '-map', '1:s', '-c:v', 'libx264', '-c:s', 'mov_text',
        '-disposition:s:0', 'forced', str(src),
    )
    assert _streams(_probe(caps, src), 'subtitle')[0]['disposition']['forced'] == 1

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert 'subtitle_disposition' in result.notes
    assert (out_dir / src.name).read_bytes() == src.read_bytes()


def test_ass_subtitle_and_attachment_keep_original(caps, tmp_path: Path) -> None:
    subtitle = tmp_path / 'styled.ass'
    subtitle.write_text(
        '[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 240\n'
        '[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
        'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, '
        'Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
        'Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,'
        '0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        'Dialogue: 0,0:00:00.00,0:00:00.80,Default,,0,0,0,,Hello\n',
        encoding='utf-8',
    )
    attachment = tmp_path / 'font.ttf'
    attachment.write_bytes(b'synthetic-font-attachment')
    src = tmp_path / 'attachment.mkv'
    _ffmpeg(
        caps, '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=10:duration=1', '-i', str(subtitle),
        '-map', '0:v', '-map', '1:s', '-c:v', 'libx264', '-c:s', 'copy',
        '-attach', str(attachment), '-metadata:s:t', 'mimetype=application/x-truetype', str(src),
    )
    source_probe = _probe(caps, src)
    assert _streams(source_probe, 'subtitle')[0]['codec_name'] == 'ass'
    assert len(_streams(source_probe, 'attachment')) == 1

    result, out_dir, _ = _run(caps, src, tmp_path)

    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert 'attachment' in result.notes
    assert 'subtitle_not_mov_text=ass' in result.notes
    assert (out_dir / src.name).read_bytes() == src.read_bytes()


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

    result, out_dir, _ = _run(caps, src, tmp_path)

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
    outcome: list[tuple[VideoCompressResult, Path, Path]] = []

    def worker() -> None:
        outcome.append(_run(caps, src, tmp_path, config=VideoCompressionConfig(crf=18, preset='veryslow'), control=control))

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(isinstance(proc.args, (list, tuple)) and '-progress' in proc.args for proc in control.snapshot()):
            break
        time.sleep(0.05)
    else:
        control.request_cancel()
        thread.join()
        pytest.fail('ffmpeg encode did not start')

    terminate_active_video_processes(control)
    thread.join(timeout=30)

    assert not thread.is_alive()
    result, out_dir, work = outcome[0]
    assert result.cancelled and not result.ok
    assert control.snapshot() == ()
    assert not out_dir.exists() or not any(out_dir.iterdir())
    assert not work.exists() or not any(work.iterdir())
