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

# MP4 へ音声コピーを許可するコーデック。opus / flac は採用ビルドの検証後に追加する。
VIDEO_MP4_AUDIO_COPY_CODECS = frozenset({'aac', 'mp3', 'ac3', 'eac3', 'alac'})
# 削除を許容し notes に記録するデータストリーム。
VIDEO_DROPPABLE_DATA_CODECS = frozenset({'tmcd', 'mebx'})
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
