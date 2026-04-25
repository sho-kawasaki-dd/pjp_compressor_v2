#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""実行時パス解決を集約する。"""

from __future__ import annotations

from dataclasses import dataclass
import shutil
import sys
from pathlib import Path
from typing import Literal


ToolSource = Literal['system', 'bundled', 'unavailable']
TOOL_SOURCE_LABELS: dict[ToolSource, str] = {
    'system': 'system',
    'bundled': 'bundled',
    'unavailable': '未検出',
}


@dataclass(frozen=True)
class ExternalToolResolution:
    """外部ツールの検出結果を path/source 付きで表す。"""

    path: str | None
    source: ToolSource

    @property
    def available(self) -> bool:
        """実行可能パスが解決できているかを返す。"""
        return bool(self.path)


def describe_tool_source(source: ToolSource) -> str:
    """UI/ログ用の外部ツール供給元ラベルを返す。"""
    return TOOL_SOURCE_LABELS[source]


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


def vendor_base_dir() -> Path:
    """同梱外部ツールを配置する vendor ディレクトリを返す。"""
    bundled_vendor = RESOURCE_BASE_DIR / 'vendor'
    if bundled_vendor.exists():
        return bundled_vendor
    return APP_BASE_DIR / 'vendor'


def _resolve_bundled_executable(relative_candidates: tuple[str, ...]) -> str | None:
    """vendor 配下の既知候補から実行可能ファイルを解決する。"""
    base_dir = vendor_base_dir()
    for relative_path in relative_candidates:
        candidate = (base_dir / relative_path).resolve()
        if candidate.is_file():
            return str(candidate)
    return None


def resolve_external_tool(
    system_candidates: tuple[str, ...],
    bundled_relative_candidates: tuple[str, ...],
) -> ExternalToolResolution:
    """system 優先、bundled 次点、未検出なら unavailable で解決する。"""
    for command_name in system_candidates:
        resolved = shutil.which(command_name)
        if resolved:
            return ExternalToolResolution(path=resolved, source='system')

    bundled_path = _resolve_bundled_executable(bundled_relative_candidates)
    if bundled_path:
        return ExternalToolResolution(path=bundled_path, source='bundled')

    return ExternalToolResolution(path=None, source='unavailable')


def resolve_ghostscript_executable() -> ExternalToolResolution:
    """Ghostscript 実行ファイルを system 優先で解決する。"""
    return resolve_external_tool(
        system_candidates=('gswin64c', 'gswin32c', 'gs'),
        bundled_relative_candidates=(
            'Ghostscript-windows/bin/gswin64c.exe',
            'Ghostscript-windows/bin/gswin32c.exe',
            'Ghostscript-windows/bin/gs.exe',
        ),
    )


def resolve_pngquant_executable() -> ExternalToolResolution:
    """pngquant 実行ファイルを system 優先で解決する。"""
    return resolve_external_tool(
        system_candidates=('pngquant',),
        bundled_relative_candidates=(
            'pngquant-windows/pngquant/pngquant.exe',
            'pngquant-windows/pngquant.exe',
        ),
    )


APP_BASE_DIR = runtime_base_dir()
RESOURCE_BASE_DIR = resource_base_dir()
