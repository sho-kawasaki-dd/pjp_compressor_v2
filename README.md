# フォルダ一括圧縮アプリ（PDF・画像対応版）v2

PDF、JPG、PNG ファイルを「フォルダ単位」で一括圧縮できる GUI アプリケーションです。

PDF 圧縮は Ghostscript（任意）またはネイティブエンジン（PyMuPDF + pikepdf）を利用し、画像は Pillow による品質指定圧縮、PNG は pngquant（不可逆）も選択可能です。画像の一括リサイズ（手動指定 / 長辺指定）にも対応し、並列処理で大量ファイルにも対応します。

## 主な機能

- **PDF 圧縮**（Ghostscript エンジン / ネイティブエンジンを選択可能）
  - Ghostscript: PDF 再蒸留（プリセット選択またはカスタム DPI）
  - ネイティブ: PyMuPDF（画像再圧縮）+ pikepdf（可逆最適化）
  - 外部ツール未導入でも該当機能のみ無効化してアプリを継続起動
- **画像圧縮**（JPG/PNG を Pillow で圧縮、PNG は pngquant による不可逆圧縮も可能）
- **画像リサイズ**（手動: 幅/高さ指定、または長辺指定、アスペクト比保持）
- **ZIP 自動展開**（ZIP 内のファイルを一時領域で再帰展開してから圧縮）
- **進捗・統計表示**、**CSV ログ出力**、**効果音**（pygame）
- ドラッグ＆ドロップ対応、バックグラウンド処理による UI フリーズ防止

## 動作環境と依存

- Python 3.13+
- 必須: `Pillow`, `PyMuPDF`, `pikepdf`, `tkinterdnd2`
- 任意: `pygame`（効果音）、`Ghostscript`（PDF 再蒸留）、`pngquant`（PNG 不可逆圧縮）

## セットアップ

```powershell
# 仮想環境の作成・有効化（PowerShell）
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# 依存インストール
python -m pip install -r requirements.txt
```

外部ツールのインストール（任意）:

```powershell
# Windows（Chocolatey）
choco install ghostscript
choco install pngquant

# macOS（Homebrew）
brew install ghostscript
brew install pngquant

# Ubuntu/Debian
sudo apt install ghostscript pngquant
```

## 起動

```powershell
python compressor_launcher_tkinter.py
```

PowerShell スクリプト経由:

```powershell
./compressor_launcher.ps1 -Mode Run
```

## 実行ファイルのビルド（PyInstaller）

```powershell
python -m PyInstaller --clean .\compressor_launcher_tkinter.spec
```

ビルド成果物は `dist/PDF_JPG_PNG_Compressor_v2.5.2/` に生成されます。

## テスト

```powershell
# 通常開発・CI 推奨
python -m pytest -m "unit or integration"

# GUI 回帰テスト（必要時のみ）
python -m pytest -m regression
```

## プロジェクト構成

```
pjp_compressor_v2/
├── compressor_launcher_tkinter.py   # 起動エントリポイント
├── frontend/                        # GUI 層（Tkinter）
├── backend/                         # 圧縮処理層（UI 非依存）
│   ├── contracts.py                 # FE/BE 境界契約（DTO）
│   ├── capabilities.py              # 外部ツール可用性検出
│   ├── orchestrator/                # ジョブ実行オーケストレーション
│   ├── services/                    # PDF・画像・ZIP・クリーンアップ
│   └── core/                        # 低レベル処理ユーティリティ
├── shared/                          # 共通パス解決・互換レイヤ
├── tests/                           # pytest テスト群
├── sounds/                          # 効果音ファイル
├── images/                          # アイコン等
└── Documentation/                   # 詳細ドキュメント
```

## 詳細ドキュメント

より詳しい機能説明・設定・よくある質問・開発者向けメモは [`Documentation/README.md`](./Documentation/README.md) を参照してください。

## ライセンス

[LICENSE](./LICENSE) を参照してください。
