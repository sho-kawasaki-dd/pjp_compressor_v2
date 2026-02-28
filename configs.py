#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
configs.py

アプリ全体で共有する設定値や定数を集約するモジュール。
目的:
- GUI と圧縮ロジックの両方から同じ値を参照できるようにし、
    モジュール間の依存を低減する。
- OS 依存のコマンド名（Ghostscript）やプリセット一覧、
    GUI のレイアウト既定値、サウンドパスなどを一元管理する。

注意:
- 値のみを提供し、副作用（ファイル作成・外部コマンド検出）は行わない。
"""
import os

# Ghostscript のコマンド名（OSにより差異）
GS_COMMAND = 'gswin64c' if os.name == 'nt' else 'gs'
# Windows では `gswin64c`、UNIX 系では `gs` が一般的。
# 実行可否の最終確認は呼び出し側（compressor_utils）で行う。

# Ghostscript 圧縮プリセットの説明
GS_OPTIONS = {
    '/screen': '最小サイズ（低画質）',
    '/ebook': 'やや強め圧縮（電子書籍向け）',
    '/printer': '標準（印刷向け・中圧縮）',
    '/prepress': '高画質（出版印刷向け・低圧縮）',
    '/default': 'Ghostscript既定'
}
# Ghostscript の `-dPDFSETTINGS` に渡すプリセット。説明文は UI 表示用。

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
