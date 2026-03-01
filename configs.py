#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
configs.py

アプリ全体で共有する設定値や定数を集約するモジュール。
目的:
- GUI と圧縮ロジックの両方から同じ値を参照できるようにし、
    モジュール間の依存を低減する。
- PDF 圧縮設定（PyMuPDF + pikepdf）やプリセット一覧、
    GUI のレイアウト既定値、サウンドパスなどを一元管理する。

注意:
- 値のみを提供し、副作用（ファイル作成・外部コマンド検出）は行わない。
"""
import os

# ---------------------------------------------------------------------------
# PDF 圧縮設定（PyMuPDF + pikepdf）
# ---------------------------------------------------------------------------

# ユーザーが選択可能な圧縮モード（UI ラジオボタン用）
PDF_COMPRESS_MODES = {
    'lossy':    '非可逆（画像再圧縮）',
    'lossless': '可逆（構造最適化）',
    'both':     '両方',
}

# 非可逆圧縮: 埋め込み画像リサンプル時の DPI 設定
PDF_LOSSY_DPI_DEFAULT = 150
PDF_LOSSY_DPI_RANGE = (36, 600)          # スライダーの min / max

# 非可逆圧縮: JPEG 再圧縮時の品質（1–100）
PDF_LOSSY_JPEG_QUALITY_DEFAULT = 75

# 非可逆圧縮: 埋め込み PNG 画像を JPEG に変換するかどうかのデフォルト
# False = PNG はリサイズのみ行い、フォーマットは維持する（安全側）
PDF_LOSSY_PNG_TO_JPEG_DEFAULT = False

# 可逆圧縮（pikepdf 構造最適化）のオプション既定値
PDF_LOSSLESS_OPTIONS_DEFAULT = {
    'linearize':            True,   # Web 最適化（Linearize）
    'object_streams':       True,   # オブジェクトストリーム圧縮
    'clean_metadata':       False,  # メタデータ除去
    'recompress_streams':   True,   # 既存 Flate ストリームを最高圧縮率で再圧縮
    'remove_unreferenced':  True,   # 孤立リソース（未参照オブジェクト）の削除
}

# ---------------------------------------------------------------------------
# クリーンアップ対象拡張子
# ---------------------------------------------------------------------------

# 入力フォルダクリーンアップ対象拡張子
INPUT_DIR_CLEANUP_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.zip'}
# 入力フォルダのクリーンアップ対象拡張子（サンプル画像や PDF を想定）。

# 出力フォルダクリーンアップ対象拡張子
OUTPUT_DIR_CLEANUP_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.csv'}
# 出力フォルダのクリーンアップ対象拡張子。CSV はログファイルを含むため注意。

# アプリ起動時のデフォルト入力フォルダ
APP_DEFAULT_INPUT_DIR = r".\input_files"
# 起動時に UI から参照され、存在しない場合は UI 側で作成される。

# アプリ起動時のデフォルト出力フォルダ
APP_DEFAULT_OUTPUT_DIR = r".\output_files"
# 既定出力フォルダ。Windows の場合は UI 側でデスクトップ配下の作成を促す。

# GUI ウィンドウのデフォルトサイズ
APP_DEFAULT_WINDOW_SIZE = "750x850"
# Tk ウィンドウのサイズ指定（幅x高さ）。

# サウンドファイル格納ディレクトリ
SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
# 効果音ファイルの配置ディレクトリ。存在しなくても致命的ではない。

LONG_EDGE_PRESETS = ["640","800","1024","1280","1600","1920","2048","2560","3840"]
# 長辺指定リサイズのプリセット値。UI のコンボボックスで使用。
