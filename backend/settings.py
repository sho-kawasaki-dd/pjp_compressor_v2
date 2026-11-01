#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backend の処理既定値を集約する。

既定値をここへ寄せる理由は、UI の初期表示、mapper の補正、backend の最終防衛線が
同じ基準を共有できるようにするためである。圧縮アルゴリズム本体には「値の意味」だけ
を残し、「既定で何を選ぶか」はこのモジュールへ閉じ込める。
"""

from __future__ import annotations

PDF_ALLOWED_MODES = frozenset({'lossy', 'lossless', 'both'})

# 画質と圧縮率のバランスが極端に崩れにくい既定値を採用する。
PDF_LOSSY_DPI_DEFAULT = 150
PDF_LOSSY_JPEG_QUALITY_DEFAULT = 75
PDF_LOSSY_PNG_QUALITY_DEFAULT = 70

# pikepdf の可逆最適化は、サイズ改善が出やすいものを既定で有効にしている。
PDF_LOSSLESS_OPTIONS_DEFAULT = {
    'linearize': True,
    'object_streams': True,
    'clean_metadata': False,
    'recompress_streams': True,
    'remove_unreferenced': True,
}

# Ghostscript は汎用用途で破綻しにくい `ebook` を backend 標準とする。
GS_DEFAULT_PRESET = 'ebook'

# ZIP 展開後の出力は既定でフォルダのままにする。
ZIP_OUTPUT_ENABLED_DEFAULT = False

# 動画圧縮（ffmpeg）。拡張子定義の正はここで、frontend のクリーンアップ対象もここから派生させる。
VIDEO_EXTENSIONS = frozenset({'mp4', 'mov', 'avi', 'mkv', 'webm', 'wmv', 'm4v'})
VIDEO_ENABLED_DEFAULT = True
VIDEO_QUALITY_DEFAULT = 75  # UI 用。backend は CRF のみを正とする。
VIDEO_CODEC_DEFAULT = 'libx264'
VIDEO_PRESET_DEFAULT = 'medium'
VIDEO_AUDIO_MODE_DEFAULT = 'copy'
VIDEO_AUDIO_BITRATE_DEFAULT = None
VIDEO_MAX_LONG_EDGE_DEFAULT = 0
VIDEO_CRF_DEFAULT = 24

VIDEO_ALLOWED_CODECS = frozenset({'libx264', 'libx265'})
VIDEO_ALLOWED_PRESETS = frozenset({
    'ultrafast', 'superfast', 'veryfast', 'faster', 'fast',
    'medium', 'slow', 'slower', 'veryslow',
})
VIDEO_ALLOWED_AUDIO_MODES = frozenset({'aac', 'copy', 'none'})
VIDEO_CRF_RANGE = (0, 51)

# 出力フォルダ直下のアプリ専用作業領域（ロックファイルと動画の一時ファイル）。
VIDEO_TEMP_PREFIX = '.pjp_tmp_'
APP_WORK_DIR_NAME = '.pjp_work'
JOB_LOCK_FILENAME = 'job.lock'
VIDEO_WORK_SUBDIR = 'video'
# 所有確認用マーカー。これを持つジョブ作業領域だけを残留掃除の対象にする。
VIDEO_WORK_OWNER_MARKER = '.pjp_owner'
VIDEO_WORK_OWNER_TOKEN = 'pjp_compressor_video_job_v1'

# ffprobe の解析・出力検証のタイムアウト（秒）。エンコード自体には固定タイムアウトを設けない。
VIDEO_PROBE_TIMEOUT_SECONDS = 30
# 元ファイル維持コピーのブロックサイズ。ブロックごとに停止要求を確認する。
VIDEO_COPY_CHUNK_BYTES = 4 * 1024 * 1024
# 出力検証で「入力にあれば出力にも残っていること」を要求する全体メタデータキー（小文字）。
VIDEO_PRESERVED_METADATA_KEYS = frozenset({
    'creation_time',
    'location',
    'location-eng',
    'make',
    'model',
    'com.apple.quicktime.location.iso6709',
    'com.apple.quicktime.make',
    'com.apple.quicktime.model',
    'com.apple.quicktime.software',
    'com.apple.quicktime.creationdate',
})

# Opus は MP4 コピー時にデコード後のサンプル数・位置が変わる入力があるため対象外。
VIDEO_MP4_AUDIO_COPY_CODECS = frozenset({'aac', 'mp3', 'ac3', 'eac3', 'alac', 'flac'})
# 削除を許容し notes に記録するデータストリーム。
VIDEO_DROPPABLE_DATA_CODECS = frozenset({'tmcd', 'mebx'})
# MOV / MP4 のチャプタートラック（QuickTime 形式のテキストトラック）。チャプターがある入力では
# `-map_chapters` で再構築されるため、データストリームとしては扱わない。
VIDEO_CHAPTER_TRACK_TAGS = frozenset({'text'})
# これを超えるビット深度の入力は元維持にする。
VIDEO_MAX_BIT_DEPTH = 8

# AAC 自動ビットレート（チャンネル数 -> bitrate）。未対応レイアウトは暗黙にダウンミックスしない。
VIDEO_AAC_AUTO_BITRATES = {
    1: '96k',
    2: '128k',
    3: '384k',
    4: '384k',
    5: '384k',
    6: '384k',
    7: '512k',
    8: '512k',
}


def aac_bitrate_for_channels(channels: int | None, explicit_bitrate: str | None = None) -> str | None:
    """トラック単位の AAC ビットレートを返す。明示指定を優先し、未対応チャンネル数は None。"""
    if explicit_bitrate:
        return explicit_bitrate
    if channels is None:
        return None
    return VIDEO_AAC_AUTO_BITRATES.get(channels)
