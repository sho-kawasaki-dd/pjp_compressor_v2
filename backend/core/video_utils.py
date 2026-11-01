from __future__ import annotations

"""ffmpeg / ffprobe による動画圧縮。

本編映像・全音声・全字幕と関連情報の保持を MP4 統一より優先する。保持条件を満たして
元より小さくなる場合だけ `.mp4` を出力し、それ以外（保持不可・サイズ増）は元拡張子のまま
元ファイルを配置する。保持可否は ffprobe の解析結果から事前に判定し、出力は項目別の
比較ルールで検証する。実行失敗からの AAC 再試行は行わない。

停止要求は `JobControl` で受け取る。ffmpeg / ffprobe の起動は `launch_lock` 内で停止確認と
登録を行い、停止要求後に新しいプロセスが起動しないようにする。
"""

import collections
import dataclasses
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from backend.contracts import CapabilityReport, JobControl, VideoCompressionConfig
from backend.core.subprocess_utils import sanitize_subprocess_error
from backend.settings import (
    APP_WORK_DIR_NAME,
    VIDEO_CHAPTER_TRACK_TAGS,
    VIDEO_COPY_CHUNK_BYTES,
    VIDEO_DROPPABLE_DATA_CODECS,
    VIDEO_MAX_BIT_DEPTH,
    VIDEO_MP4_AUDIO_COPY_CODECS,
    VIDEO_PRESERVED_METADATA_KEYS,
    VIDEO_PROBE_TIMEOUT_SECONDS,
    VIDEO_TEMP_PREFIX,
    VIDEO_WORK_OWNER_MARKER,
    VIDEO_WORK_OWNER_TOKEN,
    VIDEO_WORK_SUBDIR,
    aac_bitrate_for_channels,
)
from shared.locale_catalog import translate

KeptReason = Literal['no_gain', 'retention']

PROGRESS_MIN_INTERVAL_SECONDS = 0.2
DURATION_TOLERANCE_SECONDS = 0.5
DURATION_TOLERANCE_RATIO = 0.01
CHAPTER_START_TOLERANCE_SECONDS = 0.010
FFMPEG_TAIL_LINES = 30
AAC_MAX_CHANNELS = 8
_AAC_ENCODER = 'aac'

_HDR_TRANSFERS = frozenset({'smpte2084', 'arib-std-b67'})
_HDR_SIDE_DATA_MARKERS = ('dovi', 'dolby vision', 'mastering display', 'content light level', 'hdr dynamic', 'hdr10+')
_HDR_CODEC_TAGS = frozenset({'dvh1', 'dvhe', 'dav1', 'dvav', 'dva1'})

# ISO 639-1 / 639-2/B を ISO 639-2/T へ寄せる最小限の対応表（出力検証の正規化用）。
_LANGUAGE_ALIASES = {
    'ja': 'jpn', 'en': 'eng', 'fr': 'fra', 'de': 'deu', 'es': 'spa', 'it': 'ita', 'zh': 'zho',
    'ko': 'kor', 'pt': 'por', 'ru': 'rus', 'nl': 'nld', 'sv': 'swe', 'pl': 'pol', 'tr': 'tur',
    'ar': 'ara', 'hi': 'hin', 'th': 'tha', 'vi': 'vie', 'id': 'ind', 'uk': 'ukr', 'cs': 'ces',
    'el': 'ell', 'he': 'heb', 'hu': 'hun', 'fi': 'fin', 'da': 'dan', 'no': 'nor',
    'fre': 'fra', 'ger': 'deu', 'chi': 'zho', 'dut': 'nld', 'gre': 'ell', 'cze': 'ces',
    'per': 'fas', 'rum': 'ron', 'slo': 'slk', 'may': 'msa', 'mac': 'mkd', 'ice': 'isl',
    'arm': 'hye', 'baq': 'eus', 'bur': 'mya', 'geo': 'kat', 'alb': 'sqi', 'tib': 'bod',
    'wel': 'cym', 'mao': 'mri',
}

_PROGRESS_KEYS = re.compile(
    r'^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time_us|out_time_ms|out_time|'
    r'dup_frames|drop_frames|speed|progress)='
)
_OUT_TIME_US = re.compile(r'^out_time_us=(\d+)\s*$')
_BIT_DEPTH_SUFFIX = re.compile(r'(\d{2})(?:le|be)$')


@dataclass(frozen=True)
class VideoCompressResult:
    ok: bool  # 縮小出力または元維持の配置が完了したか
    message: str
    final_outpath: str | None  # 実際に配置したファイル（失敗時 None）
    kept_original: bool = False
    kept_original_reason: KeptReason | None = None
    cancelled: bool = False
    notes: tuple[str, ...] = ()  # 保持不可理由・AAC変換トラック・削除したデータストリーム等


class _VideoError(Exception):
    """通常失敗。メッセージは翻訳済みで、そのまま `VideoCompressResult.message` になる。"""


class _Cancelled(Exception):
    """停止要求を受けた。"""


# ---------------------------------------------------------------------------
# 解析結果モデル
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoStreamInfo:
    index: int
    codec: str | None
    width: int
    height: int
    rotation: int
    pix_fmt: str | None
    bit_depth: int | None
    hdr: bool

    @property
    def display_size(self) -> tuple[int, int]:
        """回転メタデータを反映した実際の表示サイズ。"""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height


@dataclass(frozen=True)
class AudioStreamInfo:
    index: int
    codec: str | None
    channels: int | None
    layout: str | None
    language: str | None
    title: str
    default: bool
    extra_dispositions: tuple[str, ...]


@dataclass(frozen=True)
class SubtitleStreamInfo:
    index: int
    codec: str | None
    language: str | None
    title: str
    default: bool
    extra_dispositions: tuple[str, ...]


@dataclass(frozen=True)
class DataStreamInfo:
    codec: str | None
    tag: str | None

    @property
    def label(self) -> str:
        return self.tag or self.codec or 'unknown'

    @property
    def identifiers(self) -> frozenset[str]:
        return frozenset(v for v in (self.codec, self.tag) if v)


@dataclass(frozen=True)
class ChapterInfo:
    start: float
    title: str


@dataclass(frozen=True)
class MediaInfo:
    duration: float | None
    video: VideoStreamInfo | None  # 最初の非カバー映像
    video_count: int
    audio: tuple[AudioStreamInfo, ...]
    subtitles: tuple[SubtitleStreamInfo, ...]
    data_streams: tuple[DataStreamInfo, ...]
    attachment_count: int
    chapters: tuple[ChapterInfo, ...]
    format_tags: dict[str, str]
    contains_hevc: bool = False


@dataclass(frozen=True)
class AudioPlanItem:
    codec: str | None
    action: Literal['copy', 'aac']
    bitrate: str | None = None


@dataclass(frozen=True)
class EncodePlan:
    audio: tuple[AudioPlanItem, ...]  # `audio_mode='none'` のときは空
    notes: tuple[str, ...] = ()


def _t(log_language: str, key: str, **kwargs: Any) -> str:
    return translate(log_language, key, **kwargs)


# ---------------------------------------------------------------------------
# ffprobe JSON の解析
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_positive_finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _tags_of(node: Any) -> dict[str, str]:
    tags = node.get('tags') if isinstance(node, dict) else None
    if not isinstance(tags, dict):
        return {}
    return {str(k).casefold(): str(v) for k, v in tags.items()}


def _title_of(tags: dict[str, str]) -> str:
    # MOV / MP4 ではトラック名が `name` タグとして読み出される。
    return (tags.get('title') or tags.get('name') or '').strip()


def _extra_dispositions(stream: dict[str, Any]) -> tuple[str, ...]:
    disposition = stream.get('disposition')
    if not isinstance(disposition, dict):
        return ()
    return tuple(sorted(k for k, v in disposition.items() if k != 'default' and v))


def _is_default(stream: dict[str, Any]) -> bool:
    disposition = stream.get('disposition')
    return isinstance(disposition, dict) and bool(disposition.get('default'))


def _detect_bit_depth(stream: dict[str, Any]) -> int | None:
    depths: list[int] = []
    raw = _to_int(stream.get('bits_per_raw_sample'))
    if raw:
        depths.append(raw)
    pix_fmt = stream.get('pix_fmt')
    if isinstance(pix_fmt, str):
        match = _BIT_DEPTH_SUFFIX.search(pix_fmt)
        depths.append(int(match.group(1)) if match else 8)
    return max(depths) if depths else None


def _detect_rotation(stream: dict[str, Any]) -> int:
    rotation: Any = None
    side_data = stream.get('side_data_list')
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict) and 'rotation' in item:
                rotation = item['rotation']
                break
    if rotation is None:
        rotation = _tags_of(stream).get('rotate')
    try:
        # 表示向きの比較には 90 度単位の値だけが必要。
        return int(round(float(rotation))) % 360 if rotation is not None else 0
    except (TypeError, ValueError):
        return 0


def _detect_hdr(stream: dict[str, Any]) -> bool:
    if str(stream.get('color_transfer') or '').lower() in _HDR_TRANSFERS:
        return True
    if str(stream.get('codec_tag_string') or '').lower() in _HDR_CODEC_TAGS:
        return True
    side_data = stream.get('side_data_list')
    if isinstance(side_data, list):
        for item in side_data:
            kind = str(item.get('side_data_type') or '').lower() if isinstance(item, dict) else ''
            if any(marker in kind for marker in _HDR_SIDE_DATA_MARKERS):
                return True
    return False


def _parse_video(stream: dict[str, Any], index: int) -> VideoStreamInfo:
    width = _to_int(stream.get('width'))
    height = _to_int(stream.get('height'))
    if not width or not height or width <= 0 or height <= 0:
        raise ValueError('video stream has no valid dimensions')
    pix_fmt = stream.get('pix_fmt')
    return VideoStreamInfo(
        index=index,
        codec=stream.get('codec_name') if isinstance(stream.get('codec_name'), str) else None,
        width=width,
        height=height,
        rotation=_detect_rotation(stream),
        pix_fmt=pix_fmt if isinstance(pix_fmt, str) else None,
        bit_depth=_detect_bit_depth(stream),
        hdr=_detect_hdr(stream),
    )


def parse_probe_json(payload: Any) -> MediaInfo:
    """ffprobe の JSON を検証して `MediaInfo` へ変換する。不正なら `ValueError`。"""
    if not isinstance(payload, dict):
        raise ValueError('ffprobe output is not an object')
    streams = payload.get('streams')
    fmt = payload.get('format')
    if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
        raise ValueError('ffprobe output has no valid streams list')
    if not isinstance(fmt, dict):
        raise ValueError('ffprobe output has no valid format object')

    videos: list[VideoStreamInfo] = []
    video_durations: list[float | None] = []
    audio: list[AudioStreamInfo] = []
    subtitles: list[SubtitleStreamInfo] = []
    data: list[DataStreamInfo] = []
    attachments = 0
    contains_hevc = False

    for position, stream in enumerate(streams):
        index = _to_int(stream.get('index'))
        index = position if index is None else index
        kind = stream.get('codec_type')
        codec = stream.get('codec_name') if isinstance(stream.get('codec_name'), str) else None
        tags = _tags_of(stream)
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError(f'stream {index} has no codec type')
        if kind == 'video':
            normalized_codec = codec.casefold().strip() if isinstance(codec, str) else ''
            if normalized_codec in {'', 'none', 'unknown'}:
                raise ValueError(f'video stream {index} has no codec name')
            contains_hevc = contains_hevc or normalized_codec == 'hevc'
            disposition = stream.get('disposition')
            if isinstance(disposition, dict) and disposition.get('attached_pic'):
                continue  # カバーアートは保持対象外
            videos.append(_parse_video(stream, index))
            video_durations.append(_to_positive_finite(stream.get('duration')))
        elif kind == 'audio':
            layout = stream.get('channel_layout')
            audio.append(AudioStreamInfo(
                index=index,
                codec=codec,
                channels=_to_int(stream.get('channels')),
                layout=layout if isinstance(layout, str) else None,
                language=tags.get('language'),
                title=_title_of(tags),
                default=_is_default(stream),
                extra_dispositions=_extra_dispositions(stream),
            ))
        elif kind == 'subtitle':
            subtitles.append(SubtitleStreamInfo(
                index=index,
                codec=codec,
                language=tags.get('language'),
                title=_title_of(tags),
                default=_is_default(stream),
                extra_dispositions=_extra_dispositions(stream),
            ))
        elif kind == 'attachment':
            attachments += 1
        else:
            tag = stream.get('codec_tag_string')
            # codec_name が `none` / `bin_data` の汎用値のときは codec tag で識別する。
            data.append(DataStreamInfo(
                codec=None if codec in (None, 'none', 'bin_data') else codec,
                tag=tag.lower() if isinstance(tag, str) and tag else None,
            ))

    chapters: list[ChapterInfo] = []
    raw_chapters = payload.get('chapters')
    if raw_chapters is not None:
        if not isinstance(raw_chapters, list):
            raise ValueError('ffprobe chapters is not a list')
        for item in raw_chapters:
            if not isinstance(item, dict):
                raise ValueError('ffprobe chapter is not an object')
            try:
                start = float(str(item.get('start_time')))
            except ValueError as exc:
                raise ValueError('chapter has no valid start_time') from exc
            if not math.isfinite(start):
                raise ValueError('chapter has no valid start_time')
            chapters.append(ChapterInfo(start=start, title=_title_of(_tags_of(item))))

    duration = _to_positive_finite(fmt.get('duration'))
    if duration is None and video_durations:
        duration = video_durations[0]

    return MediaInfo(
        duration=duration,
        video=videos[0] if videos else None,
        video_count=len(videos),
        audio=tuple(audio),
        subtitles=tuple(subtitles),
        data_streams=tuple(data),
        attachment_count=attachments,
        chapters=tuple(chapters),
        format_tags=_tags_of(fmt),
        contains_hevc=contains_hevc,
    )


# ---------------------------------------------------------------------------
# サブプロセス（ffmpeg / ffprobe）の起動と追跡
# ---------------------------------------------------------------------------


def _creationflags(low_priority: bool = False) -> int:
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if low_priority:
        flags |= getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
    return flags


def _spawn(cmd: list[str], job_control: JobControl, *, low_priority: bool = False, merge_stderr: bool = False):
    """停止確認→Popen→登録を `launch_lock` 内で行い、停止要求後の起動を防ぐ。"""
    with job_control.launch_lock:
        if job_control.is_cancelled:
            raise _Cancelled()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=_creationflags(low_priority),
        )
        job_control.register(proc)
    return proc


def _kill_and_reap(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def _run_ffprobe(ffprobe_path: str, path: Path, job_control: JobControl, log_language: str) -> Any:
    """ffprobe を `Popen` + `communicate(timeout)` で実行して JSON を返す。"""
    name = path.name
    cmd = [
        ffprobe_path, '-v', 'error', '-show_format', '-show_streams', '-show_chapters',
        '-of', 'json', '-i', str(path),
    ]
    proc = _spawn(cmd, job_control)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=VIDEO_PROBE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise _VideoError(_t(log_language, 'video_probe_timeout', name=name)) from None
    finally:
        job_control.unregister(proc)
        _kill_and_reap(proc)
    if proc.returncode != 0:
        if job_control.is_cancelled:
            raise _Cancelled()
        detail = sanitize_subprocess_error(stderr, path, Path(ffprobe_path)) or f'ffprobe_exit_{proc.returncode}'
        raise _VideoError(_t(log_language, 'video_probe_failed', name=name, detail=detail))
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise _VideoError(_t(log_language, 'video_probe_invalid', name=name, detail=str(exc)[:120])) from exc


def probe_media(ffprobe_path: str, path: Path, job_control: JobControl, log_language: str = 'ja') -> MediaInfo:
    """ファイルを ffprobe で解析する。失敗は `_VideoError`、停止は `_Cancelled`。"""
    payload = _run_ffprobe(ffprobe_path, path, job_control, log_language)
    try:
        return parse_probe_json(payload)
    except ValueError as exc:
        raise _VideoError(_t(log_language, 'video_probe_invalid', name=path.name, detail=str(exc))) from exc


# ---------------------------------------------------------------------------
# 保持条件の事前判定
# ---------------------------------------------------------------------------


def plan_encode(
    info: MediaInfo,
    config: VideoCompressionConfig,
    capabilities: CapabilityReport,
) -> tuple[EncodePlan | None, list[str]]:
    """保持条件を判定する。保持不可なら `(None, 理由トークン)`、可能なら `(計画, [])`。

    理由トークンは `code` または `code=detail`。そのまま CSV notes へ連結できる。
    """
    if info.video is None:
        return None, ['no_primary_video']

    reasons: list[str] = []
    notes: list[str] = []
    video = info.video

    if video.bit_depth is not None and video.bit_depth > VIDEO_MAX_BIT_DEPTH:
        reasons.append('high_bit_depth')
    if video.hdr:
        reasons.append('hdr')

    dropped: list[str] = []
    unsupported: list[str] = []
    for stream in info.data_streams:
        if stream.identifiers & VIDEO_DROPPABLE_DATA_CODECS:
            dropped.append(stream.label)
        elif info.chapters and stream.identifiers & VIDEO_CHAPTER_TRACK_TAGS:
            continue
        else:
            unsupported.append(stream.label)
    if unsupported:
        reasons.append(f'unsupported_data_stream={",".join(sorted(set(unsupported)))}')
    if info.attachment_count:
        reasons.append('attachment')
    if dropped:
        notes.append(f'dropped_data_streams={",".join(sorted(set(dropped)))}')

    non_text = sorted({s.codec or 'unknown' for s in info.subtitles if s.codec != 'mov_text'})
    if non_text:
        reasons.append(f'subtitle_not_mov_text={",".join(non_text)}')
    if any(s.extra_dispositions for s in info.subtitles):
        reasons.append('subtitle_disposition')
    if config.audio_mode != 'none' and any(a.extra_dispositions for a in info.audio):
        reasons.append('audio_disposition')

    audio_plan: list[AudioPlanItem] = []
    converted: list[str] = []
    if config.audio_mode != 'none':
        aac_available = _AAC_ENCODER in capabilities.ffmpeg_encoders
        not_copyable: list[str] = []
        bad_layout: list[str] = []
        for position, track in enumerate(info.audio):
            if config.audio_mode == 'copy' and track.codec in VIDEO_MP4_AUDIO_COPY_CODECS:
                audio_plan.append(AudioPlanItem(codec=track.codec, action='copy'))
                continue
            # 明示的な AAC 指定と、許可リスト外コーデックの通知付き変換
            if not aac_available:
                not_copyable.append(f'a{position}:{track.codec or "unknown"}')
                continue
            channels = track.channels
            bitrate = (
                aac_bitrate_for_channels(channels, config.audio_bitrate)
                if channels is not None and 1 <= channels <= AAC_MAX_CHANNELS
                else None
            )
            if bitrate is None:
                bad_layout.append(f'a{position}:{track.layout or channels}')
                continue
            audio_plan.append(AudioPlanItem(codec=track.codec, action='aac', bitrate=bitrate))
            converted.append(f'a{position}:{track.codec or "unknown"}->aac@{bitrate}')
        if not_copyable:
            reasons.append(f'audio_codec_not_copyable={",".join(not_copyable)}')
        if bad_layout:
            reasons.append(f'audio_layout_unsupported={",".join(bad_layout)}')
    if converted:
        notes.append(f'audio_aac_converted={",".join(converted)}')

    if reasons:
        return None, reasons
    return EncodePlan(audio=tuple(audio_plan), notes=tuple(notes)), []


# ---------------------------------------------------------------------------
# ffmpeg コマンド構築
# ---------------------------------------------------------------------------


def build_video_filter(max_long_edge: int) -> str:
    """yuv420p は偶数解像度が必須のため、常に末尾で偶数丸めを行う。"""
    even = 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
    if max_long_edge > 0:
        e = max_long_edge
        return (
            f"scale=w='if(gte(iw,ih),min({e},iw),-2)':"
            f"h='if(gte(iw,ih),-2,min({e},ih))',{even}"
        )
    return even


def _normalize_language(value: str | None) -> str:
    """ISO 639-2 へ正規化する。未設定は `und`。IETF タグ（`-` を含む）は比較対象外として呼び出し側で扱う。"""
    lang = (value or '').strip().lower()
    if not lang:
        return 'und'
    return _LANGUAGE_ALIASES.get(lang, lang)


def _stream_metadata_args(kind: Literal['a', 's'], tracks: tuple[AudioStreamInfo, ...] | tuple[SubtitleStreamInfo, ...]) -> list[str]:
    """入力トラックと出力トラックの対応（入力順）に基づき、言語・タイトル・default を明示する。"""
    args: list[str] = []
    for position, track in enumerate(tracks):
        spec = f'{kind}:{position}'
        language = _normalize_language(track.language)
        if language != 'und' and '-' not in language:
            args += [f'-metadata:s:{spec}', f'language={language}']
        if track.title:
            args += [f'-metadata:s:{spec}', f'title={track.title}']
        args += [f'-disposition:{spec}', 'default' if track.default else '0']
    return args


def build_ffmpeg_command(
    ffmpeg_path: str,
    inpath: str,
    temp_out: Path,
    config: VideoCompressionConfig,
    info: MediaInfo,
    plan: EncodePlan,
) -> list[str]:
    cmd = [ffmpeg_path, '-hide_banner', '-nostdin', '-y', '-i', inpath, '-map', '0:V:0']
    audio_map_args = ['-an'] if config.audio_mode == 'none' else ['-map', '0:a?']
    cmd += audio_map_args
    cmd += ['-map', '0:s?']
    cmd += ['-vf', build_video_filter(config.max_long_edge)]
    cmd += ['-c:v', config.codec, '-crf', str(config.crf), '-preset', config.preset, '-pix_fmt', 'yuv420p']

    for position, item in enumerate(plan.audio):
        if item.action == 'copy':
            cmd += [f'-c:a:{position}', 'copy']
        else:
            cmd += [f'-c:a:{position}', 'aac', f'-b:a:{position}', str(item.bitrate)]
    if info.subtitles:
        cmd += ['-c:s', 'copy']
    if config.audio_mode != 'none':
        cmd += _stream_metadata_args('a', info.audio)
    cmd += _stream_metadata_args('s', info.subtitles)
    cmd += [
        '-map_metadata', '0',
        '-map_chapters', '0',
        '-movflags', '+faststart+use_metadata_tags',
        '-write_tmcd', '0',
        '-progress', 'pipe:1', '-nostats',
        str(temp_out),
    ]
    return cmd


# ---------------------------------------------------------------------------
# 進捗
# ---------------------------------------------------------------------------


class ProgressReporter:
    """`-progress` の出力行から進捗を算出し、通知頻度を間引く。

    割合既知時は前回通知から 1% 以上増加かつ 0.2 秒以上経過したときのみ通知する。総尺不明時は
    初回のみ `None` を通知する。`progress=end` は成功を意味しないため通知せず、成否は
    終了コード・出力検証・配置後に判定する。
    """

    def __init__(
        self,
        callback: Callable[[int | None], None] | None,
        total_us: float | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._callback = callback
        self._total_us = total_us
        self._clock = clock
        self._last_pct = -1
        self._last_time: float | None = None
        self._unknown_notified = False
        self.ended = False

    def _emit(self, value: int | None) -> None:
        if self._callback is None:
            return
        try:
            self._callback(value)
        except Exception:
            pass  # UI 側の通知失敗でエンコードを止めない

    def feed(self, line: str) -> None:
        line = line.strip()
        if line == 'progress=end':
            self.ended = True
            return
        if self._total_us is None:
            if not self._unknown_notified and _PROGRESS_KEYS.match(line):
                self._unknown_notified = True
                self._emit(None)
            return
        match = _OUT_TIME_US.match(line)
        if not match:
            return  # `N/A` を含む不正値は無視する
        pct = min(99, max(0, int(int(match.group(1)) * 100 / self._total_us)))
        now = self._clock()
        if pct >= self._last_pct + 1 and (self._last_time is None or now - self._last_time >= PROGRESS_MIN_INTERVAL_SECONDS):
            self._last_pct = pct
            self._last_time = now
            self._emit(pct)


def _run_ffmpeg(
    cmd: list[str],
    job_control: JobControl,
    reporter: ProgressReporter,
) -> tuple[int, str]:
    """ffmpeg を実行して (終了コード, 末尾ログ) を返す。stderr は stdout へ統合してデッドロックを防ぐ。"""
    proc = _spawn(cmd, job_control, low_priority=True, merge_stderr=True)
    tail: collections.deque[str] = collections.deque(maxlen=FFMPEG_TAIL_LINES)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if _PROGRESS_KEYS.match(line):
                reporter.feed(line)
            elif line.strip():
                tail.append(line.rstrip())
        returncode = proc.wait()
    finally:
        job_control.unregister(proc)
        _kill_and_reap(proc)
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass
    return returncode, '\n'.join(tail)


# ---------------------------------------------------------------------------
# 出力検証
# ---------------------------------------------------------------------------


def _normalize_layout(layout: str | None) -> str | None:
    if not layout or layout.lower() == 'unknown':
        return None
    return re.sub(r'\(.*?\)', '', layout).strip().lower() or None


def _orientation(width: int, height: int) -> int:
    return (width > height) - (width < height)


def _default_matches(src_tracks: tuple, out_tracks: tuple, position: int) -> bool:
    src_default = src_tracks[position].default
    out_default = out_tracks[position].default
    if src_default == out_default:
        return True
    # 入力に default がなく、出力で先頭トラックが default になるのは MP4 の仕様として許容する
    return out_default and position == 0 and not any(t.default for t in src_tracks)


def _verify_tracks(kind: str, src_tracks: tuple, out_tracks: tuple, mismatches: list[str], notes: list[str]) -> None:
    for position, (src, out) in enumerate(zip(src_tracks, out_tracks)):
        raw_language = (src.language or '').strip()
        if '-' in raw_language:
            notes.append(f'ietf_language_tag={kind}{position}:{raw_language}')
        elif _normalize_language(src.language) != _normalize_language(out.language):
            mismatches.append(f'{kind}_language:{position}')
        if src.title.strip() != out.title.strip():
            mismatches.append(f'{kind}_title:{position}')
        if not _default_matches(src_tracks, out_tracks, position):
            mismatches.append(f'{kind}_default:{position}')


def verify_output(src: MediaInfo, out: MediaInfo, plan: EncodePlan) -> tuple[list[str], list[str]]:
    """項目別の比較ルールで出力を検証する。`(違反項目, 追加 notes)` を返す。"""
    mismatches: list[str] = []
    notes: list[str] = []

    if out.video is None or out.video_count != 1:
        mismatches.append('video')
    elif src.video is not None:
        if out.video.rotation != 0:
            mismatches.append('rotation')
        src_o = _orientation(*src.video.display_size)
        out_o = _orientation(*out.video.display_size)
        if src_o * out_o < 0:  # 縦横が入れ替わった場合のみ違反（偶数丸めによる正方形化は許容）
            mismatches.append('orientation')

    if src.duration is not None:
        tolerance = max(DURATION_TOLERANCE_SECONDS, src.duration * DURATION_TOLERANCE_RATIO)
        if out.duration is None or abs(out.duration - src.duration) > tolerance:
            mismatches.append('duration')

    if len(out.audio) != len(plan.audio):
        mismatches.append('audio_count')
    else:
        src_audio = src.audio[:len(plan.audio)]
        for position, (item, s, o) in enumerate(zip(plan.audio, src_audio, out.audio)):
            expected_codec = 'aac' if item.action == 'aac' else s.codec
            if o.codec != expected_codec:
                mismatches.append(f'audio_codec:{position}')
            if s.channels != o.channels:
                mismatches.append(f'audio_channels:{position}')
            src_layout, out_layout = _normalize_layout(s.layout), _normalize_layout(o.layout)
            if src_layout and out_layout and src_layout != out_layout:
                mismatches.append(f'audio_layout:{position}')
        _verify_tracks('audio', src_audio, out.audio, mismatches, notes)

    if len(out.subtitles) != len(src.subtitles):
        mismatches.append('subtitle_count')
    else:
        if any(s.codec != 'mov_text' for s in out.subtitles):
            mismatches.append('subtitle_codec')
        _verify_tracks('subtitle', src.subtitles, out.subtitles, mismatches, notes)

    if len(out.chapters) != len(src.chapters):
        mismatches.append('chapter_count')
    else:
        for position, (s, o) in enumerate(zip(src.chapters, out.chapters)):
            if s.title.strip() != o.title.strip():
                mismatches.append(f'chapter_title:{position}')
            if abs(s.start - o.start) > CHAPTER_START_TOLERANCE_SECONDS:
                mismatches.append(f'chapter_start:{position}')

    for key in sorted(VIDEO_PRESERVED_METADATA_KEYS & src.format_tags.keys()):
        if key not in out.format_tags:
            mismatches.append(f'metadata:{key}')

    return mismatches, notes


# ---------------------------------------------------------------------------
# 配置・一時ファイル
# ---------------------------------------------------------------------------


def _temp_path(temp_dir: Path, suffix: str) -> Path:
    return temp_dir / f'{VIDEO_TEMP_PREFIX}{uuid.uuid4().hex}{suffix}'


def _publish(temp_path: Path, dest: Path, job_control: JobControl) -> None:
    """停止要求が受理されていないことを確認した上で配置する。確認と `replace` は同じロック内。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with job_control.launch_lock:
        if job_control.is_cancelled:
            raise _Cancelled()
        temp_path.replace(dest)


def _copy_with_cancel(src: Path, dest: Path, job_control: JobControl) -> None:
    """ブロック単位で停止要求を確認しながらコピーし、更新時刻等を引き継ぐ。"""
    with open(src, 'rb') as fin, open(dest, 'wb') as fout:
        while True:
            if job_control.is_cancelled:
                raise _Cancelled()
            chunk = fin.read(VIDEO_COPY_CHUNK_BYTES)
            if not chunk:
                break
            fout.write(chunk)
    shutil.copystat(src, dest)


def _remove_temps(paths: list[Path], log_language: str) -> list[str]:
    failures: list[str] = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            detail = sanitize_subprocess_error(str(exc), path)
            failures.append(_t(log_language, 'video_temp_delete_failed', detail=f'{path.name}: {detail}'))
    return failures


def _reason_label(token: str, log_language: str) -> str:
    code, _, detail = token.partition('=')
    label = _t(log_language, f'video_reason.{code}')
    return f'{label} [{detail}]' if detail else label


def _keep_original(
    inpath: Path,
    original_outpath: Path,
    reason: KeptReason,
    notes: list[str],
    job_control: JobControl,
    temp_dir: Path,
    temps: list[Path],
    log_language: str,
) -> VideoCompressResult:
    """元ファイルを元拡張子のままジョブ一時領域へ完全コピーしてから配置する。"""
    name = inpath.name
    if job_control.is_cancelled:
        raise _Cancelled()
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        staged = _temp_path(temp_dir, '.orig')
        temps.append(staged)
        _copy_with_cancel(inpath, staged, job_control)
        _publish(staged, original_outpath, job_control)
    except OSError as exc:
        detail = sanitize_subprocess_error(str(exc), inpath, original_outpath)
        return VideoCompressResult(
            ok=False,
            message=_t(log_language, 'video_copy_failed', name=name, detail=detail),
            final_outpath=None,
            notes=tuple(notes),
        )
    if reason == 'no_gain':
        message = _t(log_language, 'video_kept_original_no_gain', name=name)
    else:
        reasons = ', '.join(_reason_label(token, log_language) for token in notes)
        message = _t(log_language, 'video_kept_original_retention', name=name, reasons=reasons)
    return VideoCompressResult(
        ok=True,
        message=message,
        final_outpath=str(original_outpath),
        kept_original=True,
        kept_original_reason=reason,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------


def tool_unavailable_reason(capabilities: CapabilityReport, config: VideoCompressionConfig, log_language: str) -> str | None:
    """動画処理を始められない理由を翻訳済み文言で返す。利用可能なら None。"""
    if not capabilities.ffmpeg_path:
        return _t(log_language, 'video_ffmpeg_missing')
    if capabilities.ffmpeg_detection_error:
        return _t(log_language, 'video_ffmpeg_detect_failed', detail=capabilities.ffmpeg_detection_error)
    if not capabilities.ffmpeg_available:
        return _t(log_language, 'video_ffmpeg_no_h264')
    if not capabilities.ffprobe_path:
        return _t(log_language, 'video_ffprobe_missing')
    if capabilities.ffprobe_detection_error:
        return _t(log_language, 'video_ffprobe_detect_failed', detail=capabilities.ffprobe_detection_error)
    if config.codec not in capabilities.ffmpeg_encoders:
        return _t(log_language, 'video_codec_unavailable', codec=config.codec)
    return None


def _compress(
    inpath: Path,
    outpath: Path,
    original_outpath: Path,
    config: VideoCompressionConfig,
    capabilities: CapabilityReport,
    job_control: JobControl,
    temp_dir: Path,
    progress_callback: Callable[[int | None], None] | None,
    log_language: str,
    temps: list[Path],
) -> VideoCompressResult:
    name = inpath.name

    def check_cancel() -> None:
        if job_control.is_cancelled:
            raise _Cancelled()

    def keep(reason: KeptReason, notes: list[str]) -> VideoCompressResult:
        return _keep_original(inpath, original_outpath, reason, notes, job_control, temp_dir, temps, log_language)

    check_cancel()
    if not capabilities.ffprobe_path:
        reason = _t(log_language, 'video_ffprobe_missing')
        raise _VideoError(_t(log_language, 'video_tool_unavailable', reason=reason))
    if capabilities.ffprobe_detection_error:
        reason = _t(log_language, 'video_ffprobe_detect_failed', detail=capabilities.ffprobe_detection_error)
        raise _VideoError(_t(log_language, 'video_tool_unavailable', reason=reason))
    ffprobe_path = capabilities.ffprobe_path

    info = probe_media(ffprobe_path, inpath, job_control, log_language)
    check_cancel()

    if info.contains_hevc:
        return keep('retention', ['hevc_input_prohibited'])

    unavailable = tool_unavailable_reason(capabilities, config, log_language)
    if unavailable:
        raise _VideoError(_t(log_language, 'video_tool_unavailable', reason=unavailable))
    ffmpeg_path = str(capabilities.ffmpeg_path)

    plan, reasons = plan_encode(info, config, capabilities)
    if plan is None:
        return keep('retention', reasons)

    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_out = _temp_path(temp_dir, '.mp4')
    temps.append(temp_out)
    cmd = build_ffmpeg_command(ffmpeg_path, str(inpath), temp_out, config, info, plan)

    check_cancel()
    total_us = info.duration * 1_000_000 if info.duration else None
    returncode, tail = _run_ffmpeg(cmd, job_control, ProgressReporter(progress_callback, total_us))
    if returncode != 0:
        check_cancel()  # 停止要求による終了は失敗ではなく中断として扱う
        detail = sanitize_subprocess_error(tail, inpath, temp_out, Path(ffmpeg_path)) or f'ffmpeg_exit_{returncode}'
        raise _VideoError(_t(log_language, 'video_ffmpeg_failed', name=name, detail=detail))
    if not temp_out.is_file() or temp_out.stat().st_size == 0:
        raise _VideoError(_t(log_language, 'video_output_missing', name=name))
    check_cancel()

    out_info = probe_media(ffprobe_path, temp_out, job_control, log_language)
    mismatches, verify_notes = verify_output(info, out_info, plan)
    if mismatches:
        return keep('retention', [f'validation_mismatch={",".join(mismatches)}'])

    check_cancel()
    if temp_out.stat().st_size >= inpath.stat().st_size:
        return keep('no_gain', [])

    try:
        _publish(temp_out, outpath, job_control)
    except OSError as exc:
        detail = sanitize_subprocess_error(str(exc), temp_out, outpath)
        return VideoCompressResult(
            ok=False,
            message=_t(log_language, 'video_place_failed', name=name, detail=detail),
            final_outpath=None,
            notes=(*plan.notes, *verify_notes),
        )
    message = _t(log_language, 'video_success', name=name)
    for note in plan.notes:
        if note.startswith('audio_aac_converted='):
            message += ' / ' + _t(log_language, 'video_audio_aac_converted', tracks=note.partition('=')[2])
    return VideoCompressResult(
        ok=True,
        message=message,
        final_outpath=str(outpath),
        notes=(*plan.notes, *verify_notes),
    )


def compress_video_ffmpeg(
    inpath: str,
    outpath: str,  # 予定出力先（.mp4、衝突回避済み）
    original_outpath: str,  # 入力と同じ拡張子の出力先（元維持時に使用）
    video_config: VideoCompressionConfig,
    *,
    capabilities: CapabilityReport,
    job_control: JobControl,
    temp_dir: Path,  # 排他取得済みのジョブ専用作業領域
    progress_callback: Callable[[int | None], None] | None = None,
    log_language: str = 'ja',
) -> VideoCompressResult:
    """動画を圧縮して配置する。結果の配置規則は `VideoCompressResult` と plan の表に従う。"""
    src = Path(inpath)
    temps: list[Path] = []
    try:
        result = _compress(
            src, Path(outpath), Path(original_outpath), video_config, capabilities,
            job_control, Path(temp_dir), progress_callback, log_language, temps,
        )
    except _Cancelled:
        result = VideoCompressResult(
            ok=False,
            message=_t(log_language, 'video_cancelled', name=src.name),
            final_outpath=None,
            cancelled=True,
        )
    except _VideoError as exc:
        result = VideoCompressResult(ok=False, message=str(exc), final_outpath=None)
    except Exception as exc:
        detail = sanitize_subprocess_error(f'{type(exc).__name__}: {exc}', src, Path(outpath))
        result = VideoCompressResult(
            ok=False,
            message=_t(log_language, 'video_ffmpeg_failed', name=src.name, detail=detail),
            final_outpath=None,
        )

    failures = _remove_temps(temps, log_language)
    if failures:
        result = dataclasses.replace(
            result,
            message=' / '.join([result.message, *failures]),
            notes=(*result.notes, 'temp_delete_failed'),
        )
    return result


# ---------------------------------------------------------------------------
# 停止処理・作業領域
# ---------------------------------------------------------------------------


def terminate_active_video_processes(
    job_control: JobControl,
    timeout: float = 3.0,
    *,
    log_func: Callable[[str], None] | None = None,
    log_language: str = 'ja',
) -> None:
    """停止要求を確定させ、実行中の ffmpeg / ffprobe を停止して回収する。

    停止要求の確定後に `snapshot()` を取るため、以降に新しいプロセスは起動しない。
    待機はロック外で行う。停止できなかったプロセスは `log_func` で通知する。
    """
    job_control.request_cancel()
    for proc in job_control.snapshot():
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=timeout)
        except Exception:
            if log_func is not None:
                log_func(_t(log_language, 'video_terminate_failed', pid=getattr(proc, 'pid', '?')))
        finally:
            if proc.poll() is not None:
                job_control.unregister(proc)


def place_original_copy(inpath: str | Path, dest: str | Path, temp_dir: str | Path, job_control: JobControl) -> bool:
    """失敗時のミラーコピー用に、元ファイルをジョブ一時領域経由で配置する。

    停止要求を受理していて配置しなかった場合は False、配置できた場合は True を返す。
    コピー・配置の失敗は OSError のまま送出する。
    """
    temp_dir = Path(temp_dir)
    temps: list[Path] = []
    try:
        if job_control.is_cancelled:
            return False
        temp_dir.mkdir(parents=True, exist_ok=True)
        staged = _temp_path(temp_dir, '.orig')
        temps.append(staged)
        _copy_with_cancel(Path(inpath), staged, job_control)
        _publish(staged, Path(dest), job_control)
        return True
    except _Cancelled:
        return False
    finally:
        _remove_temps(temps, 'ja')


def _is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def create_video_job_dir(output_dir: str | Path, job_id: str | None = None) -> Path:
    """`<出力>/.pjp_work/video/<job_uuid>/` を所有マーカー付きで作成する。出力排他の取得後に呼ぶ。"""
    job_dir = Path(output_dir) / APP_WORK_DIR_NAME / VIDEO_WORK_SUBDIR / (job_id or uuid.uuid4().hex)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / VIDEO_WORK_OWNER_MARKER).write_text(VIDEO_WORK_OWNER_TOKEN, encoding='utf-8')
    return job_dir


def cleanup_stale_video_temps(output_dir: str | Path) -> int:
    """過去ジョブの残留作業領域を削除し、削除した数を返す。出力排他の取得中だけ呼ぶ。

    対象は `.pjp_work/video/` 直下で所有マーカーを確認できるジョブ用ディレクトリのみ。
    所有不明のディレクトリ・ファイル、リンク、作業領域外を指すものは削除しない。
    """
    work_dir = Path(output_dir) / APP_WORK_DIR_NAME
    video_root = work_dir / VIDEO_WORK_SUBDIR
    if _is_link(work_dir) or _is_link(video_root) or not video_root.is_dir():
        return 0
    try:
        resolved_root = video_root.resolve()
        entries = list(os.scandir(video_root))
    except OSError:
        return 0

    removed = 0
    for entry in entries:
        path = Path(entry.path)
        try:
            if _is_link(path) or not entry.is_dir(follow_symlinks=False):
                continue
            if path.resolve().parent != resolved_root:
                continue
            marker = path / VIDEO_WORK_OWNER_MARKER
            if _is_link(marker) or not marker.is_file():
                continue
            if marker.read_text(encoding='utf-8').strip() != VIDEO_WORK_OWNER_TOKEN:
                continue
            shutil.rmtree(path)
            removed += 1
        except OSError:
            continue
    return removed
