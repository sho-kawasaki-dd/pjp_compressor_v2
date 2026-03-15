#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_launcher_tkinter.py

tkinter 版 GUI のエントリポイント（起動スクリプト）。

背後の構成:
- GUI ロジック: `frontend/ui_tkinter.py`
- 圧縮ロジック: `backend/core/compressor_utils.py`
- 設定・定数: `shared/configs.py`
- 効果音ユーティリティ: `frontend/sound_utils.py`

注意:
- 本ファイルは最小限の起動処理のみを行い、設定や検証は各モジュールに委譲する。
- PySide6 版は `compressor_launcher_pyside.py` を使用してください。
"""
import sys
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, Tk
from frontend.bootstrap import run_tkinter_app


def _runtime_base_dir() -> Path:
    """実行体の基準ディレクトリを返す（exe優先、通常実行時は本ファイル基準）。"""
    # PyInstaller 化された実行ファイルでは `__file__` ではなく exe の位置を基準にしないと、
    # ログや同梱リソースの保存先がずれる。
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _write_crash_log(exc: BaseException) -> Path | None:
    """起動失敗時にクラッシュログを保存する。"""
    base_dir = _runtime_base_dir()
    log_dir = base_dir / "logs"
    log_path = log_dir / "launcher_crash.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_text = f"[{timestamp}] Fatal startup error\n{details}\n"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(log_text)
        return log_path
    except Exception:
        return None


def _show_startup_error(exc: BaseException, log_path: Path | None) -> None:
    """コンソール非表示環境向けに起動失敗メッセージを表示する。"""
    log_hint = f"\n\n詳細ログ: {log_path}" if log_path else "\n\n詳細ログの保存にも失敗しました。"
    message = (
        "アプリの起動中に致命的なエラーが発生しました。\n"
        f"{type(exc).__name__}: {exc}"
        f"{log_hint}"
    )

    try:
        # GUI 本体の起動前でも例外内容を知らせるため、一時的な最小 Tk だけ作る。
        root = Tk()
        root.withdraw()
        messagebox.showerror("起動エラー", message)
        root.destroy()
    except Exception:
        pass


def main() -> int:
    """tkinter アプリを安全に起動する。"""
    try:
        return run_tkinter_app()
    except Exception as exc:
        # 起動失敗時は再送出せず、GUI アプリとして分かりやすいエラー導線を優先する。
        log_path = _write_crash_log(exc)
        _show_startup_error(exc, log_path)
        return 1

# ------------- アプリ起動 -------------
if __name__ == "__main__":
    raise SystemExit(main())