from __future__ import annotations

"""動画圧縮 backend（video_utils）の unit test。外部プロセスは起動しない。"""

import dataclasses
import hashlib
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from backend.contracts import CapabilityReport, JobControl, VideoCompressionConfig
from backend.core import video_utils
from backend.core.video_utils import (
    AudioPlanItem,
    AudioStreamInfo,
    ChapterInfo,
    DataStreamInfo,
    EncodePlan,
    MediaInfo,
    ProgressReporter,
    SubtitleStreamInfo,
    VideoStreamInfo,
)
from backend.settings import VIDEO_WORK_OWNER_MARKER, VIDEO_WORK_OWNER_TOKEN

pytestmark = pytest.mark.unit

ALL_ENCODERS = frozenset({'libx264', 'aac'})


def make_caps(encoders: frozenset[str] = ALL_ENCODERS, **overrides: Any) -> CapabilityReport:
    values: dict[str, Any] = dict(
        fitz_available=False,
        pikepdf_available=False,
        ghostscript_path=None,
        pngquant_path=None,
        ffmpeg_path='C:/tools/ffmpeg.exe',
        ffmpeg_source='system',
        ffmpeg_encoders=encoders,
        ffprobe_path='C:/tools/ffprobe.exe',
        ffprobe_source='system',
    )
    values.update(overrides)
    return CapabilityReport(**values)


def make_video(**overrides: Any) -> VideoStreamInfo:
    values: dict[str, Any] = dict(
        index=0, codec='h264', width=1280, height=720, rotation=0, pix_fmt='yuv420p', bit_depth=8, hdr=False,
    )
    values.update(overrides)
    return VideoStreamInfo(**values)


def make_audio(index: int = 1, **overrides: Any) -> AudioStreamInfo:
    values: dict[str, Any] = dict(
        index=index, codec='aac', channels=2, layout='stereo', language='jpn', title='', default=True,
        extra_dispositions=(),
    )
    values.update(overrides)
    return AudioStreamInfo(**values)


def make_sub(index: int = 2, **overrides: Any) -> SubtitleStreamInfo:
    values: dict[str, Any] = dict(
        index=index, codec='mov_text', language='jpn', title='', default=True, extra_dispositions=(),
    )
    values.update(overrides)
    return SubtitleStreamInfo(**values)


def make_info(**overrides: Any) -> MediaInfo:
    values: dict[str, Any] = dict(
        duration=10.0,
        video=make_video(),
        video_count=1,
        audio=(make_audio(),),
        subtitles=(),
        data_streams=(),
        attachment_count=0,
        chapters=(),
        format_tags={},
    )
    values.update(overrides)
    return MediaInfo(**values)


def probe_payload(streams: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {'streams': streams, 'format': {'duration': '10.0', 'tags': {'creation_time': 'x'}}}
    payload.update(extra)
    return payload


VIDEO_STREAM = {
    'index': 0, 'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080,
    'pix_fmt': 'yuv420p', 'disposition': {'default': 1},
}
AUDIO_STREAM = {
    'index': 1, 'codec_type': 'audio', 'codec_name': 'aac', 'channels': 2, 'channel_layout': 'stereo',
    'tags': {'language': 'jpn', 'name': 'Main'}, 'disposition': {'default': 1},
}


# --- ffprobe JSON の解析 ---------------------------------------------------


def test_parse_probe_json_extracts_streams_and_skips_cover_art() -> None:
    cover = {**VIDEO_STREAM, 'index': 5, 'disposition': {'attached_pic': 1}}
    info = video_utils.parse_probe_json(probe_payload([cover, VIDEO_STREAM, AUDIO_STREAM], chapters=[
        {'start_time': '1.500000', 'tags': {'title': 'Intro'}},
    ]))

    assert info.video is not None and info.video.index == 0
    assert info.video_count == 1
    assert info.duration == 10.0
    assert info.audio[0].title == 'Main'  # MOV / MP4 では name タグ
    assert info.audio[0].default is True
    assert info.chapters == (ChapterInfo(start=1.5, title='Intro'),)
    assert info.format_tags == {'creation_time': 'x'}
    assert info.contains_hevc is False


def test_parse_probe_json_detects_hevc_in_cover_art_and_secondary_video() -> None:
    cover = {**VIDEO_STREAM, 'index': 4, 'codec_name': 'hevc', 'disposition': {'attached_pic': 1}}
    secondary = {**VIDEO_STREAM, 'index': 5, 'codec_name': 'HEVC'}

    info = video_utils.parse_probe_json(probe_payload([VIDEO_STREAM, cover, secondary]))

    assert info.contains_hevc is True
    assert info.video_count == 2


@pytest.mark.parametrize(
    ('stream', 'message'),
    [
        ({**VIDEO_STREAM, 'codec_name': None}, 'has no codec name'),
        ({**VIDEO_STREAM, 'codec_name': 'unknown'}, 'has no codec name'),
        ({'index': 0, 'codec_name': 'hevc'}, 'has no codec type'),
    ],
)
def test_parse_probe_json_rejects_video_streams_without_identifiable_codec(
    stream: dict[str, Any], message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        video_utils.parse_probe_json(probe_payload([stream]))


@pytest.mark.parametrize(
    ('extra', 'expected_rotation', 'expected_display'),
    [
        ({'side_data_list': [{'side_data_type': 'Display Matrix', 'rotation': -90}]}, 270, (1080, 1920)),
        ({'tags': {'rotate': '90'}}, 90, (1080, 1920)),
        ({'side_data_list': [{'rotation': 180}]}, 180, (1920, 1080)),
    ],
)
def test_parse_probe_json_detects_rotation(extra: dict[str, Any], expected_rotation: int, expected_display: tuple[int, int]) -> None:
    info = video_utils.parse_probe_json(probe_payload([{**VIDEO_STREAM, **extra}]))

    assert info.video is not None
    assert info.video.rotation == expected_rotation
    assert info.video.display_size == expected_display


@pytest.mark.parametrize(
    ('extra', 'expected_depth'),
    [
        ({}, 8),
        ({'pix_fmt': 'yuv420p10le'}, 10),
        ({'pix_fmt': 'p010le'}, 10),
        ({'bits_per_raw_sample': '10'}, 10),
    ],
)
def test_parse_probe_json_detects_bit_depth(extra: dict[str, Any], expected_depth: int) -> None:
    info = video_utils.parse_probe_json(probe_payload([{**VIDEO_STREAM, **extra}]))

    assert info.video is not None and info.video.bit_depth == expected_depth


@pytest.mark.parametrize(
    'extra',
    [
        {'color_transfer': 'smpte2084'},
        {'color_transfer': 'arib-std-b67'},
        {'side_data_list': [{'side_data_type': 'DOVI configuration record'}]},
        {'side_data_list': [{'side_data_type': 'Mastering display metadata'}]},
        {'codec_tag_string': 'dvh1'},
    ],
)
def test_parse_probe_json_detects_hdr(extra: dict[str, Any]) -> None:
    info = video_utils.parse_probe_json(probe_payload([{**VIDEO_STREAM, **extra}]))

    assert info.video is not None and info.video.hdr is True


def test_parse_probe_json_identifies_generic_data_streams_by_tag() -> None:
    streams = [
        VIDEO_STREAM,
        {'index': 1, 'codec_type': 'data', 'codec_name': 'none', 'codec_tag_string': 'tmcd'},
        {'index': 2, 'codec_type': 'data', 'codec_name': 'bin_data', 'codec_tag_string': 'gpmd'},
        {'index': 3, 'codec_type': 'attachment', 'codec_name': 'ttf'},
    ]

    info = video_utils.parse_probe_json(probe_payload(streams))

    assert [s.label for s in info.data_streams] == ['tmcd', 'gpmd']
    assert info.attachment_count == 1


@pytest.mark.parametrize('duration', ['N/A', 'nan', 'inf', '0', '-3', None])
def test_parse_probe_json_treats_invalid_duration_as_unknown(duration: Any) -> None:
    payload = probe_payload([VIDEO_STREAM])
    payload['format'] = {'duration': duration}

    assert video_utils.parse_probe_json(payload).duration is None


def test_parse_probe_json_falls_back_to_video_stream_duration() -> None:
    payload = probe_payload([{**VIDEO_STREAM, 'duration': '4.5'}])
    payload['format'] = {}

    assert video_utils.parse_probe_json(payload).duration == 4.5


@pytest.mark.parametrize(
    'payload',
    [
        [],
        {'format': {}},
        {'streams': 'x', 'format': {}},
        {'streams': [1], 'format': {}},
        {'streams': []},
        {'streams': [{'codec_type': 'video', 'codec_name': 'h264'}], 'format': {}},
        {'streams': [VIDEO_STREAM], 'format': {}, 'chapters': 'x'},
        {'streams': [VIDEO_STREAM], 'format': {}, 'chapters': [{'start_time': 'N/A'}]},
    ],
)
def test_parse_probe_json_rejects_malformed_payload(payload: Any) -> None:
    with pytest.raises(ValueError):
        video_utils.parse_probe_json(payload)


# --- 保持条件の事前判定 -----------------------------------------------------


def plan_for(info: MediaInfo, config: VideoCompressionConfig | None = None, caps: CapabilityReport | None = None):
    return video_utils.plan_encode(info, config or VideoCompressionConfig(), caps or make_caps())


def test_plan_encode_accepts_preservable_input_and_copies_allowed_audio() -> None:
    info = make_info(audio=(
        make_audio(codec='aac'),
        make_audio(2, codec='ac3', channels=6, layout='5.1(side)'),
        make_audio(3, codec='flac'),
    ))

    plan, reasons = plan_for(info)

    assert reasons == []
    assert plan is not None
    assert [(p.action, p.bitrate) for p in plan.audio] == [('copy', None), ('copy', None), ('copy', None)]


def test_plan_encode_keeps_original_without_primary_video() -> None:
    plan, reasons = plan_for(make_info(video=None, video_count=0))

    assert plan is None and reasons == ['no_primary_video']


def test_plan_encode_reports_high_bit_depth_and_hdr() -> None:
    plan, reasons = plan_for(make_info(video=make_video(bit_depth=10, hdr=True)))

    assert plan is None
    assert reasons == ['high_bit_depth', 'hdr']


def test_plan_encode_drops_tmcd_and_mebx_with_notes() -> None:
    info = make_info(data_streams=(DataStreamInfo(None, 'tmcd'), DataStreamInfo(None, 'mebx')))

    plan, reasons = plan_for(info)

    assert reasons == [] and plan is not None
    assert 'dropped_data_streams=mebx,tmcd' in plan.notes


def test_plan_encode_rejects_other_data_streams_and_attachments() -> None:
    info = make_info(data_streams=(DataStreamInfo(None, 'gpmd'),), attachment_count=1)

    plan, reasons = plan_for(info)

    assert plan is None
    assert reasons == ['unsupported_data_stream=gpmd', 'attachment']


def test_plan_encode_allows_chapter_text_track_only_with_chapters() -> None:
    track = DataStreamInfo('bin_data', 'text')

    with_chapters, reasons = plan_for(make_info(data_streams=(track,), chapters=(ChapterInfo(0.0, 'a'),)))
    without_chapters, reasons_without = plan_for(make_info(data_streams=(track,)))

    assert with_chapters is not None and reasons == []
    assert without_chapters is None and reasons_without == ['unsupported_data_stream=text']


def test_plan_encode_rejects_non_mov_text_and_special_subtitle_dispositions() -> None:
    info = make_info(subtitles=(make_sub(codec='subrip'), make_sub(3, extra_dispositions=('forced',))))

    plan, reasons = plan_for(info)

    assert plan is None
    assert 'subtitle_not_mov_text=subrip' in reasons
    assert 'subtitle_disposition' in reasons


def test_plan_encode_accepts_mov_text_subtitles() -> None:
    plan, reasons = plan_for(make_info(subtitles=(make_sub(),)))

    assert plan is not None and reasons == []


@pytest.mark.parametrize(
    ('channels', 'layout', 'expected_bitrate'),
    [(1, 'mono', '96k'), (2, 'stereo', '128k'), (6, '5.1', '384k'), (8, '7.1', '512k')],
)
def test_plan_encode_converts_non_allowlisted_audio_per_track(channels: int, layout: str, expected_bitrate: str) -> None:
    info = make_info(audio=(
        make_audio(codec='aac'),
        make_audio(2, codec='opus', channels=channels, layout=layout),
    ))

    plan, reasons = plan_for(info)

    assert reasons == [] and plan is not None
    assert plan.audio[0] == AudioPlanItem(codec='aac', action='copy')
    assert plan.audio[1] == AudioPlanItem(codec='opus', action='aac', bitrate=expected_bitrate)
    assert any(note.startswith('audio_aac_converted=a1:opus->aac@') for note in plan.notes)


def test_plan_encode_prefers_explicit_audio_bitrate() -> None:
    config = VideoCompressionConfig(audio_mode='aac', audio_bitrate='192k')

    plan, _ = plan_for(make_info(audio=(make_audio(codec='aac', channels=6),)), config)

    assert plan is not None
    assert plan.audio == (AudioPlanItem(codec='aac', action='aac', bitrate='192k'),)


def test_plan_encode_keeps_original_when_aac_encoder_is_missing() -> None:
    info = make_info(audio=(make_audio(codec='opus'),))

    plan, reasons = plan_for(info, caps=make_caps(frozenset({'libx264'})))

    assert plan is None
    assert reasons == ['audio_codec_not_copyable=a0:opus']


@pytest.mark.parametrize('channels', [None, 0, 9])
def test_plan_encode_keeps_original_for_unsupported_aac_layout(channels: int | None) -> None:
    info = make_info(audio=(make_audio(codec='opus', channels=channels, layout='weird'),))

    plan, reasons = plan_for(info)

    assert plan is None
    assert reasons[0].startswith('audio_layout_unsupported=')


def test_plan_encode_audio_none_removes_audio_without_checks() -> None:
    info = make_info(audio=(make_audio(codec='opus', extra_dispositions=('dub',)),))

    plan, reasons = plan_for(info, VideoCompressionConfig(audio_mode='none'))

    assert reasons == [] and plan is not None and plan.audio == ()


# --- ffmpeg コマンド -------------------------------------------------------


def build(config: VideoCompressionConfig, info: MediaInfo, plan: EncodePlan) -> list[str]:
    return video_utils.build_ffmpeg_command('ffmpeg', 'in.mov', Path('out.mp4'), config, info, plan)


def test_build_ffmpeg_command_contains_required_arguments_in_order() -> None:
    info = make_info(
        audio=(make_audio(language='ja', title='Main', default=False), make_audio(2, codec='opus', language='eng')),
        subtitles=(make_sub(),),
    )
    plan = EncodePlan(audio=(AudioPlanItem('aac', 'copy'), AudioPlanItem('opus', 'aac', '128k')))

    cmd = build(VideoCompressionConfig(crf=28, preset='slow'), info, plan)

    assert cmd[:6] == ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-i', 'in.mov']
    assert cmd[cmd.index('-map'):cmd.index('-map') + 2] == ['-map', '0:V:0']
    assert ['-map', '0:a?'] == cmd[cmd.index('0:a?') - 1:cmd.index('0:a?') + 1]
    assert '0:s?' in cmd
    assert cmd[cmd.index('-crf') + 1] == '28' and cmd[cmd.index('-preset') + 1] == 'slow'
    assert cmd[cmd.index('-pix_fmt') + 1] == 'yuv420p'
    assert cmd[cmd.index('-c:a:0') + 1] == 'copy'
    assert cmd[cmd.index('-c:a:1') + 1:cmd.index('-c:a:1') + 4] == ['aac', '-b:a:1', '128k']
    assert cmd[cmd.index('-c:s') + 1] == 'copy'
    assert cmd[cmd.index('-map_chapters') + 1] == '0'
    assert cmd[cmd.index('-movflags') + 1] == '+faststart+use_metadata_tags'
    assert cmd[cmd.index('-write_tmcd') + 1] == '0'
    assert cmd[cmd.index('-progress') + 1] == 'pipe:1' and '-nostats' in cmd
    assert cmd[-1] == 'out.mp4'
    assert '-ac' not in cmd  # 暗黙のダウンミックスをしない
    assert '-tag:v' not in cmd


def test_build_ffmpeg_command_sets_stream_metadata_explicitly() -> None:
    info = make_info(
        audio=(make_audio(language='ja', title='Main', default=False), make_audio(2, language=None, default=True)),
    )
    plan = EncodePlan(audio=(AudioPlanItem('aac', 'copy'), AudioPlanItem('aac', 'copy')))

    cmd = build(VideoCompressionConfig(), info, plan)

    pairs = list(zip(cmd, cmd[1:]))
    assert ('-metadata:s:a:0', 'language=jpn') in pairs  # ISO 639-2 へ正規化
    assert ('-metadata:s:a:0', 'title=Main') in pairs
    assert ('-disposition:a:0', '0') in pairs
    assert ('-disposition:a:1', 'default') in pairs
    assert not any(arg == '-metadata:s:a:1' for arg in cmd)  # und / title なしは指定しない


def test_build_ffmpeg_command_audio_none_uses_an_and_no_subtitle_copy_without_subtitles() -> None:
    cmd = build(VideoCompressionConfig(audio_mode='none'), make_info(), EncodePlan(audio=()))

    assert '-an' in cmd and '0:a?' not in cmd
    assert '-c:s' not in cmd
    assert '-c:a:0' not in cmd


def test_build_video_filter_always_rounds_to_even_and_optionally_resizes() -> None:
    assert video_utils.build_video_filter(0) == 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
    resized = video_utils.build_video_filter(1280)
    assert "min(1280,iw)" in resized and "min(1280,ih)" in resized
    assert resized.endswith(',scale=trunc(iw/2)*2:trunc(ih/2)*2')


# --- 進捗 ------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_progress_reporter_throttles_by_percent_and_time() -> None:
    clock = FakeClock()
    reported: list[int | None] = []
    reporter = ProgressReporter(reported.append, total_us=100_000_000, clock=clock)

    reporter.feed('out_time_us=0')  # 0% は初回通知
    clock.now = 0.1
    reporter.feed('out_time_us=5000000')  # 時間不足
    clock.now = 0.3
    reporter.feed('out_time_us=5000000')  # 5%
    reporter.feed('out_time_us=5400000')  # 同じ 5% は通知しない
    clock.now = 0.6
    reporter.feed('out_time_us=5800000')  # 5% のまま
    clock.now = 1.0
    reporter.feed('out_time_us=999999999')  # 99% で頭打ち

    assert reported == [0, 5, 99]


def test_progress_reporter_ignores_na_and_marks_end_without_reporting() -> None:
    reported: list[int | None] = []
    reporter = ProgressReporter(reported.append, total_us=1_000_000)

    reporter.feed('out_time_us=N/A')
    reporter.feed('progress=end')

    assert reported == [] and reporter.ended is True


def test_progress_reporter_reports_unknown_once_when_duration_is_unknown() -> None:
    clock = FakeClock()
    reported: list[int | None] = []
    reporter = ProgressReporter(reported.append, total_us=None, clock=clock)

    reporter.feed('frame=10')
    clock.now = 5
    reporter.feed('out_time_us=2000000')
    reporter.feed('progress=continue')

    assert reported == [None]


def test_progress_reporter_swallows_callback_errors() -> None:
    def broken(_: int | None) -> None:
        raise RuntimeError('ui gone')

    ProgressReporter(broken, total_us=1_000_000).feed('out_time_us=500000')


# --- 出力検証 --------------------------------------------------------------


def verify(src: MediaInfo, out: MediaInfo, plan: EncodePlan | None = None):
    plan = plan or EncodePlan(audio=tuple(AudioPlanItem(a.codec, 'copy') for a in src.audio))
    return video_utils.verify_output(src, out, plan)


def test_verify_output_accepts_equivalent_output_with_normalization() -> None:
    src = make_info(
        audio=(make_audio(language='ja', layout='5.1(side)', channels=6, title=' Main '),),
        subtitles=(make_sub(),),
        chapters=(ChapterInfo(1.0, 'A'),),
        format_tags={'creation_time': 'x', 'com.apple.quicktime.make': 'Apple', 'other': '1'},
    )
    out = dataclasses.replace(
        src,
        duration=10.4,
        audio=(make_audio(language='jpn', layout='5.1', channels=6, title='Main'),),
        chapters=(ChapterInfo(1.005, 'A'),),
        format_tags={'creation_time': 'y', 'COM.APPLE.QUICKTIME.MAKE': 'Apple'},
    )
    out = dataclasses.replace(out, format_tags={k.casefold(): v for k, v in out.format_tags.items()})

    mismatches, _ = verify(src, out)

    assert mismatches == []


@pytest.mark.parametrize(
    ('change', 'expected'),
    [
        ({'video': None, 'video_count': 0}, 'video'),
        ({'video': make_video(rotation=90)}, 'rotation'),
        ({'video': make_video(width=720, height=1280)}, 'orientation'),
        ({'duration': 12.0}, 'duration'),
        ({'duration': None}, 'duration'),
        ({'audio': ()}, 'audio_count'),
        ({'audio': (make_audio(codec='mp3'),)}, 'audio_codec:0'),
        ({'audio': (make_audio(channels=1, layout='mono'),)}, 'audio_channels:0'),
        ({'audio': (make_audio(layout='quad'),)}, 'audio_layout:0'),
        ({'audio': (make_audio(language='eng'),)}, 'audio_language:0'),
        ({'audio': (make_audio(title='Other'),)}, 'audio_title:0'),
        ({'audio': (make_audio(default=False),)}, 'audio_default:0'),
        ({'subtitles': ()}, 'subtitle_count'),
        ({'chapters': ()}, 'chapter_count'),
        ({'chapters': (ChapterInfo(1.0, 'B'),)}, 'chapter_title:0'),
        ({'chapters': (ChapterInfo(1.5, 'A'),)}, 'chapter_start:0'),
        ({'format_tags': {}}, 'metadata:creation_time'),
    ],
)
def test_verify_output_reports_each_violation(change: dict[str, Any], expected: str) -> None:
    src = make_info(subtitles=(make_sub(),), chapters=(ChapterInfo(1.0, 'A'),), format_tags={'creation_time': 'x'})
    out = dataclasses.replace(src, **change)

    mismatches, _ = verify(src, out)

    assert expected in mismatches


def test_verify_output_allows_first_track_default_when_input_has_none() -> None:
    src = make_info(audio=(make_audio(default=False), make_audio(2, default=False)))
    ok = dataclasses.replace(src, audio=(make_audio(default=True), make_audio(2, default=False)))
    bad = dataclasses.replace(src, audio=(make_audio(default=False), make_audio(2, default=True)))

    assert verify(src, ok)[0] == []
    assert verify(src, bad)[0] == ['audio_default:1']


def test_verify_output_treats_und_and_missing_language_as_equal_and_records_ietf_tags() -> None:
    src = make_info(audio=(make_audio(language='und'),), subtitles=(make_sub(language='ja-JP'),))
    out = dataclasses.replace(src, audio=(make_audio(language=None),), subtitles=(make_sub(language='und'),))

    mismatches, notes = verify(src, out)

    assert mismatches == []
    assert 'ietf_language_tag=subtitle0:ja-JP' in notes


def test_verify_output_expects_aac_for_converted_tracks_and_no_audio_for_none() -> None:
    src = make_info(audio=(make_audio(codec='opus'),))
    converted = EncodePlan(audio=(AudioPlanItem('opus', 'aac', '128k'),))
    out_aac = dataclasses.replace(src, audio=(make_audio(codec='aac'),))

    assert video_utils.verify_output(src, out_aac, converted)[0] == []
    assert video_utils.verify_output(src, dataclasses.replace(src, audio=()), EncodePlan(audio=()))[0] == []


def test_verify_output_tolerates_even_rounding_that_squares_the_frame() -> None:
    src = make_info(video=make_video(width=1281, height=1280))
    out = dataclasses.replace(src, video=make_video(width=1280, height=1280))

    assert verify(src, out)[0] == []


# --- 実行制御（モックした Popen） ---------------------------------------------


class FakeProc:
    def __init__(self, stdout: str = '', stderr: str = '', returncode: int = 0, communicate_timeouts: int = 0, pid: int = 1) -> None:
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.returncode: int | None = returncode
        self._timeouts = communicate_timeouts
        self.killed = False
        self.terminated = False
        self.pid = pid
        self.wait_timeouts = 0

    def communicate(self, timeout: float | None = None):
        if self._timeouts > 0:
            self._timeouts -= 1
            raise subprocess.TimeoutExpired('x', timeout or 0)
        return self.stdout_text, self.stderr_text

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def terminate(self) -> None:
        self.terminated = True
        if self.wait_timeouts == 0:
            self.returncode = -15

    def wait(self, timeout: float | None = None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired('x', timeout or 0)
        return self.returncode


def test_probe_media_times_out_kills_process_and_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = FakeProc(communicate_timeouts=1)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: proc)
    control = JobControl()

    with pytest.raises(video_utils._VideoError):
        video_utils.probe_media('ffprobe', Path('a.mp4'), control, 'en')

    assert proc.killed is True
    assert control.snapshot() == ()


def test_probe_media_rejects_invalid_json_and_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    control = JobControl()

    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: FakeProc(stdout='not json'))
    with pytest.raises(video_utils._VideoError):
        video_utils.probe_media('ffprobe', Path('a.mp4'), control, 'en')

    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: FakeProc(stderr='boom a.mp4', returncode=1))
    with pytest.raises(video_utils._VideoError) as exc_info:
        video_utils.probe_media('ffprobe', Path('a.mp4'), control, 'en')
    assert 'boom' in str(exc_info.value)


def test_spawn_does_not_start_process_after_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_popen(*_a: Any, **_k: Any):
        raise AssertionError('Popen must not be called after cancel')

    monkeypatch.setattr(subprocess, 'Popen', fail_popen)
    control = JobControl()
    control.request_cancel()

    with pytest.raises(video_utils._Cancelled):
        video_utils._spawn(['ffprobe'], control)


def test_cancel_and_spawn_race_never_starts_process_after_request(monkeypatch: pytest.MonkeyPatch) -> None:
    started_after_cancel: list[bool] = []
    control = JobControl()

    def popen(*_a: Any, **_k: Any):
        started_after_cancel.append(control.cancel_event.is_set())
        return FakeProc()

    monkeypatch.setattr(subprocess, 'Popen', popen)

    def worker() -> None:
        for _ in range(200):
            try:
                proc = video_utils._spawn(['x'], control)
                control.unregister(proc)
            except video_utils._Cancelled:
                return

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    control.request_cancel()
    for t in threads:
        t.join()

    assert not any(started_after_cancel)


def test_terminate_active_video_processes_stops_and_unregisters_processes() -> None:
    control = JobControl()
    graceful = FakeProc(returncode=None)  # type: ignore[arg-type]
    stubborn = FakeProc(returncode=None, pid=2)  # type: ignore[arg-type]
    stubborn.wait_timeouts = 1  # terminate では終了しない
    control.register(graceful)  # type: ignore[arg-type]
    control.register(stubborn)  # type: ignore[arg-type]

    video_utils.terminate_active_video_processes(control, timeout=0.01)

    assert control.is_cancelled
    assert graceful.terminated and not graceful.killed
    assert stubborn.terminated and stubborn.killed
    assert control.snapshot() == ()


def test_terminate_active_video_processes_reports_failures() -> None:
    class Unstoppable(FakeProc):
        def terminate(self) -> None:
            raise OSError('denied')

    control = JobControl()
    proc = Unstoppable(returncode=None, pid=42)  # type: ignore[arg-type]
    control.register(proc)  # type: ignore[arg-type]
    logs: list[str] = []

    video_utils.terminate_active_video_processes(control, timeout=0.01, log_func=logs.append, log_language='en')

    assert len(logs) == 1 and '42' in logs[0]
    assert control.snapshot() == (proc,)  # 停止できなかったものは追跡を残す


# --- compress_video_ffmpeg のフロー（probe / ffmpeg をスタブ化） -----------------------


class Flow:
    """probe と ffmpeg 実行をスタブ化してフロー全体を検証するための補助。"""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, src_size: int = 1000, out_size: int = 400) -> None:
        self.src = tmp_path / 'in' / 'clip.mov'
        self.src.parent.mkdir()
        self.src.write_bytes(b's' * src_size)
        self.out_dir = tmp_path / 'out'
        self.work = tmp_path / 'out' / '.pjp_work' / 'video' / 'job'
        self.control = JobControl()
        self.src_info = make_info(subtitles=(make_sub(),), chapters=(ChapterInfo(0.0, 'A'),))
        self.out_info = self.src_info
        self.out_size = out_size
        self.ffmpeg_calls = 0
        self.ffmpeg_returncode = 0
        self.on_ffmpeg = None
        monkeypatch.setattr(video_utils, 'probe_media', self._probe)
        monkeypatch.setattr(video_utils, '_run_ffmpeg', self._ffmpeg)

    def _probe(self, _ffprobe: str, path: Path, _control: JobControl, _lang: str = 'ja') -> MediaInfo:
        return self.src_info if path == self.src else self.out_info

    def _ffmpeg(self, cmd: list[str], control: JobControl, reporter: ProgressReporter):
        self.ffmpeg_calls += 1
        if self.ffmpeg_returncode == 0:
            Path(cmd[-1]).write_bytes(b'o' * self.out_size)
        if self.on_ffmpeg:
            self.on_ffmpeg()
        return self.ffmpeg_returncode, 'Error opening input'

    def run(
        self,
        config: VideoCompressionConfig | None = None,
        caps: CapabilityReport | None = None,
        *,
        log_language: str = 'en',
    ):
        return video_utils.compress_video_ffmpeg(
            str(self.src),
            str(self.out_dir / 'clip.mp4'),
            str(self.out_dir / 'clip.mov'),
            config or VideoCompressionConfig(),
            capabilities=caps or make_caps(),
            job_control=self.control,
            temp_dir=self.work,
            log_language=log_language,
        )

    def leftovers(self) -> list[str]:
        return [p.name for p in self.work.glob('*')] if self.work.exists() else []


@pytest.fixture
def flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flow:
    return Flow(tmp_path, monkeypatch)


def test_compress_places_mp4_when_smaller(flow: Flow) -> None:
    result = flow.run()

    assert result.ok and not result.kept_original and not result.cancelled
    assert result.final_outpath == str(flow.out_dir / 'clip.mp4')
    assert (flow.out_dir / 'clip.mp4').stat().st_size == 400
    assert not (flow.out_dir / 'clip.mov').exists()
    assert flow.leftovers() == []


@pytest.mark.parametrize('language', ['ja', 'en'])
def test_compress_reports_automatic_aac_conversion(flow: Flow, language: str) -> None:
    flow.src_info = make_info(audio=(make_audio(codec='opus'),))
    flow.out_info = make_info(audio=(make_audio(codec='aac'),))

    result = flow.run(log_language=language)

    assert result.ok and not result.kept_original
    assert result.notes == ('audio_aac_converted=a0:opus->aac@128k',)
    assert 'AAC' in result.message
    assert 'opus' in result.message and '128k' in result.message


def test_compress_does_not_report_conversion_when_original_is_kept(flow: Flow) -> None:
    flow.src_info = make_info(audio=(make_audio(codec='opus'),))
    flow.out_info = make_info(audio=(make_audio(codec='aac'),))
    flow.out_size = flow.src.stat().st_size

    result = flow.run()

    assert result.ok and result.kept_original and result.kept_original_reason == 'no_gain'
    assert 'AAC' not in result.message
    assert result.notes == ()


def test_compress_keeps_original_with_original_extension_when_not_smaller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flow = Flow(tmp_path, monkeypatch, src_size=1000, out_size=1000)

    result = flow.run()

    assert result.ok and result.kept_original and result.kept_original_reason == 'no_gain'
    assert result.final_outpath == str(flow.out_dir / 'clip.mov')
    assert (flow.out_dir / 'clip.mov').read_bytes() == flow.src.read_bytes()
    assert not (flow.out_dir / 'clip.mp4').exists()
    assert flow.leftovers() == []


def test_compress_keeps_original_on_retention_without_running_ffmpeg(flow: Flow) -> None:
    flow.src_info = make_info(video=make_video(hdr=True))

    result = flow.run()

    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert result.notes == ('hdr',)
    assert flow.ffmpeg_calls == 0
    assert (flow.out_dir / 'clip.mov').exists()


def test_compress_keeps_original_when_output_verification_fails(flow: Flow) -> None:
    flow.out_info = dataclasses.replace(flow.src_info, chapters=())

    result = flow.run()

    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert result.notes == ('validation_mismatch=chapter_count',)
    assert (flow.out_dir / 'clip.mov').exists() and not (flow.out_dir / 'clip.mp4').exists()
    assert flow.leftovers() == []


def test_compress_failure_cleans_up_and_never_retries_with_aac(flow: Flow) -> None:
    flow.ffmpeg_returncode = 1

    result = flow.run(VideoCompressionConfig(audio_mode='copy'))

    assert not result.ok and not result.cancelled and result.final_outpath is None
    assert 'Error opening input' in result.message
    assert flow.ffmpeg_calls == 1
    assert not flow.out_dir.joinpath('clip.mp4').exists() and not flow.out_dir.joinpath('clip.mov').exists()
    assert flow.leftovers() == []


def test_compress_reports_tool_unavailable_with_reason(flow: Flow) -> None:
    result = flow.run(caps=make_caps(ffprobe_path=None))

    assert not result.ok and 'ffprobe was not found' in result.message
    assert flow.ffmpeg_calls == 0


def test_compress_keeps_hevc_input_without_starting_ffmpeg(flow: Flow) -> None:
    flow.src_info = dataclasses.replace(flow.src_info, contains_hevc=True)

    result = flow.run()

    copied = flow.out_dir / 'clip.mov'
    assert result.ok and result.kept_original and result.kept_original_reason == 'retention'
    assert result.notes == ('hevc_input_prohibited',)
    assert 'H.265/HEVC' in result.message
    assert flow.ffmpeg_calls == 0
    assert copied.exists() and not (flow.out_dir / 'clip.mp4').exists()
    assert hashlib.sha256(flow.src.read_bytes()).digest() == hashlib.sha256(copied.read_bytes()).digest()
    assert flow.leftovers() == []


def test_compress_keeps_hevc_input_without_h264_encoder(flow: Flow) -> None:
    flow.src_info = dataclasses.replace(flow.src_info, contains_hevc=True)

    result = flow.run(caps=make_caps(
        frozenset({'aac'}),
        ffmpeg_path=None,
        ffmpeg_source='unavailable',
    ))

    copied = flow.out_dir / 'clip.mov'
    assert result.ok and result.kept_original
    assert result.notes == ('hevc_input_prohibited',)
    assert flow.ffmpeg_calls == 0
    assert copied.read_bytes() == flow.src.read_bytes()


def test_compress_cancelled_before_start_does_nothing(flow: Flow) -> None:
    flow.control.request_cancel()

    result = flow.run()

    assert result.cancelled and not result.ok and result.final_outpath is None
    assert flow.ffmpeg_calls == 0 and not flow.out_dir.exists()


def test_compress_cancel_during_encode_discards_output(flow: Flow) -> None:
    flow.on_ffmpeg = flow.control.request_cancel
    flow.ffmpeg_returncode = 1  # 停止で強制終了されたプロセスを模擬

    result = flow.run()

    assert result.cancelled and not result.ok
    assert flow.leftovers() == [] and not flow.out_dir.joinpath('clip.mov').exists()


def test_compress_cancel_before_final_placement_keeps_existing_output(flow: Flow) -> None:
    flow.out_dir.mkdir()
    existing = flow.out_dir / 'clip.mp4'
    existing.write_bytes(b'previous result')
    flow.on_ffmpeg = flow.control.request_cancel  # 出力生成後に停止要求

    result = flow.run()

    assert result.cancelled and not result.ok
    assert existing.read_bytes() == b'previous result'
    assert flow.leftovers() == []


def test_compress_cancel_during_original_copy_keeps_existing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flow = Flow(tmp_path, monkeypatch, src_size=40, out_size=40)
    flow.out_dir.mkdir()
    existing = flow.out_dir / 'clip.mov'
    existing.write_bytes(b'previous result')
    monkeypatch.setattr(video_utils, 'VIDEO_COPY_CHUNK_BYTES', 4)

    original_copy = video_utils._copy_with_cancel

    def copy_then_cancel(src: Path, dest: Path, job_control: JobControl) -> None:
        job_control.request_cancel()
        original_copy(src, dest, job_control)

    monkeypatch.setattr(video_utils, '_copy_with_cancel', copy_then_cancel)

    result = flow.run()

    assert result.cancelled and not result.ok
    assert existing.read_bytes() == b'previous result'
    assert flow.leftovers() == []


def test_copy_with_cancel_stops_between_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / 'big.bin'
    src.write_bytes(b'x' * 64)
    dest = tmp_path / 'copy.bin'
    monkeypatch.setattr(video_utils, 'VIDEO_COPY_CHUNK_BYTES', 8)
    control = JobControl()
    reads = {'n': 0}
    real_open = open

    class CountingFile:
        def __init__(self, handle: Any) -> None:
            self._h = handle

        def read(self, size: int) -> bytes:
            reads['n'] += 1
            if reads['n'] == 3:
                control.request_cancel()
            return self._h.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *exc: Any) -> None:
            self._h.close()

    def fake_open(path: Any, mode: str = 'r', *a: Any, **k: Any):
        handle = real_open(path, mode, *a, **k)
        return CountingFile(handle) if 'r' in mode else handle

    monkeypatch.setattr('builtins.open', fake_open)

    with pytest.raises(video_utils._Cancelled):
        video_utils._copy_with_cancel(src, dest, control)

    assert reads['n'] == 3


def test_compress_reports_copy_failure_for_original(flow: Flow, monkeypatch: pytest.MonkeyPatch) -> None:
    flow.src_info = make_info(video=make_video(hdr=True))

    def failing_copy(*_a: Any, **_k: Any) -> None:
        raise OSError('disk full')

    monkeypatch.setattr(video_utils, '_copy_with_cancel', failing_copy)

    result = flow.run()

    assert not result.ok and 'disk full' in result.message
    assert result.notes == ('hdr',)
    assert flow.leftovers() == []


def test_compress_reports_placement_failure(flow: Flow, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_publish(*_a: Any, **_k: Any) -> None:
        raise OSError('access denied')

    monkeypatch.setattr(video_utils, '_publish', failing_publish)

    result = flow.run()

    assert not result.ok and result.final_outpath is None and 'access denied' in result.message
    assert flow.leftovers() == []


def test_compress_reports_temp_delete_failure(flow: Flow, monkeypatch: pytest.MonkeyPatch) -> None:
    flow.ffmpeg_returncode = 1
    # 一時ファイルが存在する状態で削除に失敗するケース
    original_ffmpeg = flow._ffmpeg

    def ffmpeg_with_output(cmd: list[str], control: JobControl, reporter: ProgressReporter):
        Path(cmd[-1]).write_bytes(b'partial')
        return original_ffmpeg(cmd, control, reporter)

    monkeypatch.setattr(video_utils, '_run_ffmpeg', ffmpeg_with_output)
    real_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name.startswith('.pjp_tmp_'):
            raise PermissionError(f'locked {self}')
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, 'unlink', failing_unlink)

    result = flow.run()

    assert not result.ok
    assert 'temp_delete_failed' in result.notes
    assert 'Failed to delete temporary file' in result.message
    assert str(flow.work) not in result.message  # 内部パスは露出しない


# --- 作業領域・残留掃除 -------------------------------------------------------


def test_create_video_job_dir_writes_owner_marker(tmp_path: Path) -> None:
    job_dir = video_utils.create_video_job_dir(tmp_path, 'abc')

    assert job_dir == tmp_path / '.pjp_work' / 'video' / 'abc'
    assert (job_dir / VIDEO_WORK_OWNER_MARKER).read_text(encoding='utf-8') == VIDEO_WORK_OWNER_TOKEN


def test_cleanup_stale_video_temps_removes_only_owned_job_dirs(tmp_path: Path) -> None:
    video_root = tmp_path / '.pjp_work' / 'video'
    owned = video_utils.create_video_job_dir(tmp_path, 'owned')
    (owned / '.pjp_tmp_x.mp4').write_bytes(b'x')
    unknown = video_root / 'unknown'
    unknown.mkdir()
    (unknown / 'keep.txt').write_text('keep', encoding='utf-8')
    wrong_marker = video_root / 'wrong'
    wrong_marker.mkdir()
    (wrong_marker / VIDEO_WORK_OWNER_MARKER).write_text('someone else', encoding='utf-8')
    stray_file = video_root / '.pjp_tmp_stray.mp4'
    stray_file.write_bytes(b'x')
    outside_tree = tmp_path / 'user' / '.pjp_tmp_user.mp4'
    outside_tree.parent.mkdir()
    outside_tree.write_bytes(b'x')

    removed = video_utils.cleanup_stale_video_temps(tmp_path)

    assert removed == 1
    assert not owned.exists()
    assert (unknown / 'keep.txt').exists() and wrong_marker.exists()
    assert stray_file.exists() and outside_tree.exists()


def test_cleanup_stale_video_temps_does_not_follow_links_out_of_work_area(tmp_path: Path) -> None:
    video_root = tmp_path / '.pjp_work' / 'video'
    video_root.mkdir(parents=True)
    target = tmp_path / 'precious'
    target.mkdir()
    (target / VIDEO_WORK_OWNER_MARKER).write_text(VIDEO_WORK_OWNER_TOKEN, encoding='utf-8')
    (target / 'data.txt').write_text('data', encoding='utf-8')
    link = video_root / 'linked'
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if sys.platform != 'win32':
            pytest.skip('symlink creation is not permitted')
        # 権限なしで作れる NTFS ジャンクションで代替する
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        if made.returncode != 0:
            pytest.skip('link creation is not permitted')

    removed = video_utils.cleanup_stale_video_temps(tmp_path)

    assert removed == 0
    assert (target / 'data.txt').read_text(encoding='utf-8') == 'data'


def test_cleanup_stale_video_temps_without_work_dir_returns_zero(tmp_path: Path) -> None:
    assert video_utils.cleanup_stale_video_temps(tmp_path) == 0
