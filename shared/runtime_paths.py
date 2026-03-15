#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""実行時パス解決を集約する。"""

from __future__ import annotations

import sys
from pathlib import Path


def runtime_base_dir() -> Path:
    """実行時の基準ディレクトリを返す。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_base_dir() -> Path:
    """同梱リソース探索の基準ディレクトリを返す。"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(getattr(sys, '_MEIPASS'))
    return runtime_base_dir()


APP_BASE_DIR = runtime_base_dir()
RESOURCE_BASE_DIR = resource_base_dir()
