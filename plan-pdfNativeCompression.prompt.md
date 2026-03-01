## Plan: PDF圧縮エンジンのPythonネイティブ化（改訂版 v2）

**TL;DR**
pypdf ベースの PDF 圧縮を撤廃し、**PyMuPDF（埋め込み画像の再圧縮）+ pikepdf（構造最適化）**の2段構成を主エンジンとする。加えて **GhostScript（再蒸留）+ pikepdf（構造最適化）** を第二エンジンとしてオプション残置する。ユーザーは UI でまずエンジン（ネイティブ / GhostScript）を選択し、ネイティブ側では「非可逆」「可逆」「両方」をラジオボタンで選択、可逆側はチェックボックスでオプションを個別に制御可能。品質指定は GS プリセット5択を廃止し、DPI スライダー + JPEG 品質スライダーの2本に変更。GhostScript 側ではプリセット5種＋カスタムDPI を選択し、追加で pikepdf 可逆オプションを適用できる。全埋め込み画像を対象とする。pypdf/PyPDF2 フォールバックは削除し、pikepdf を必須依存とする。PDF内埋め込みPNG画像のJPEG変換をユーザーが選択可能にする。非可逆モードにおいて、埋め込み画像がPNG（ロスレス）だった場合、「JPEG変換する（リサイズ＋JPEG品質圧縮）」か「PNG維持する（リサイズのみ）」かをチェックボックスで切り替えられるようにする。JPEG元画像は常にJPEG品質で再圧縮。

---

**Steps**

### Phase 1: 依存関係の更新

1. `requirements.txt` に `PyMuPDF` と `pikepdf` を追加し、`pypdf` と `PyPDF2` を削除
2. `pyproject.toml` の `dependencies` にも `PyMuPDF`, `pikepdf` を追加

### Phase 2: configs.py の定数変更

3. `configs.py` から `GS_COMMAND`, `GS_OPTIONS` を削除
4. 新たに以下の定数を追加:
   - `PDF_COMPRESS_MODES`: `{'lossy': '非可逆（画像再圧縮）', 'lossless': '可逆（構造最適化）', 'both': '両方'}`
   - `PDF_LOSSY_DPI_DEFAULT`: `150`
   - `PDF_LOSSY_DPI_RANGE`: `(36, 600)`
   - `PDF_LOSSY_JPEG_QUALITY_DEFAULT`: `75`
   - `PDF_LOSSY_PNG_TO_JPEG_DEFAULT`: `False` — PNG→JPEG変換のデフォルトOFF（ロスレス画像はリサイズのみ）
   - `PDF_LOSSLESS_OPTIONS_DEFAULT`: `{'linearize': True, 'object_streams': True, 'clean_metadata': False, 'recompress_streams': True, 'remove_unreferenced': True}`
   - `GS_PRESETS`: `{'screen': '画面用 (72dpi)', 'ebook': '電子書籍用 (150dpi)', 'printer': '印刷用 (300dpi)', 'prepress': 'プリプレス用 (300dpi, カラー保持)', 'default': 'デフォルト'}` — GS エンジン用プリセット定数
   - `GS_DEFAULT_PRESET`: `'ebook'`

### Phase 3: compressor_utils.py の PDF 関数全面書き換え

5. **インポート変更**: `from configs import GS_COMMAND, GS_OPTIONS` 削除、pypdf/PyPDF2 の try/except 全削除。`import fitz`（PyMuPDF）と `import pikepdf` を追加
6. **`compress_pdf_pypdf()` を削除**
7. **`get_ghostscript_path()` と `compress_pdf_ghostscript()` を残置** — GS エンジン選択時に使用する既存関数として保持
8. **`compress_pdf()` の既存ディスパッチロジックを削除**
9. **新関数 `compress_pdf_lossy()` を作成** — PyMuPDF で PDF 内の全埋め込み画像を走査・再圧縮。`png_to_jpeg` パラメータを受け取る:
   - `fitz.open(input_path)` で PDF を開く
   - 各ページの `page.get_images(full=True)` で画像 xref を列挙
   - 各画像について Pixmap で取得し、元画像のフォーマットを判定（カラースペース・アルファチャンネルの有無等）
   - **分岐ロジック**:
     - **元画像が JPEG 系の場合**: 指定DPIでリサンプル → 指定JPEG品質で再圧縮 → ストリーム差し替え
     - **元画像が PNG/ロスレス系の場合**:
       - `png_to_jpeg=True`: JPEG 系と同じ処理（リサンプル＋JPEG品質圧縮）。ただしアルファチャンネルを持つ画像は白背景で合成してからJPEG化
       - `png_to_jpeg=False`: 指定DPIでリサンプルのみ行い、PNG（Deflate）のまま再保存。JPEG品質は適用しない
   - 元より小さくなった場合のみ差し替えるガード付き
   - `doc.save(output_path, garbage=4, deflate=True)` で保存
10. **新関数 `compress_pdf_lossless()` を作成** — pikepdf による構造最適化。オプション dict に応じて:
    - `linearize`: Web 最適化
    - `object_streams`: オブジェクトストリーム圧縮
    - `clean_metadata`: メタデータ除去
    - `recompress_streams`: 既存 Flate ストリームを最高圧縮率で再圧縮
    - `remove_unreferenced`: 孤立リソース（未参照オブジェクト）の削除
11. **`compress_pdf_native()` ディスパッチ関数（旧 `compress_pdf()`）** — ネイティブエンジン用。`mode` パラメータに応じて: - `'lossy'`: `compress_pdf_lossy()` のみ（`png_to_jpeg` を渡す）- `'lossless'`: `compress_pdf_lossless()` のみ - `'both'`: lossy → lossless の2段パイプライン
    11b. **新関数 `compress_pdf_gs()` を作成** — GhostScript エンジン用ディスパッチ関数: - `compress_pdf_ghostscript()` で再蒸留を実行 - `lossless_options` が指定されている場合は GS 出力に対して `compress_pdf_lossless()` を直列適用 - GS が未インストールの場合はエラーを返す
12. **`process_single_file()` のタプル構造を変更** — 旧 `gs_quality`, `pdf_engine`, `pdf_quality` → 新 `pdf_engine`（`'native'` or `'gs'`）, `pdf_mode`, `pdf_dpi`, `pdf_jpeg_quality`, `pdf_png_to_jpeg`, `pdf_lossless_options`, `gs_preset`, `gs_custom_dpi`。`pdf_engine` に応じて `compress_pdf_native()` または `compress_pdf_gs()` を呼び分ける
13. **`compress_folder()` のシグネチャ変更** — 旧パラメータ廃止、新パラメータ `pdf_engine`, `pdf_mode`, `pdf_dpi`, `pdf_jpeg_quality`, `pdf_png_to_jpeg`, `pdf_lossless_options`, `gs_preset`, `gs_custom_dpi` を追加

### Phase 4: ui_app.py の PDF 関連 UI 刷新

14. **インポート変更**: `PYPDF_AVAILABLE`, `GS_OPTIONS`, `GS_COMMAND` のインポートを削除。新定数群（`PDF_COMPRESS_MODES`, `GS_PRESETS`, `GS_DEFAULT_PRESET` 等）をインポート
15. **GUI 変数の変更**:
    - 削除: `self.gs_quality`, `self.pdf_quality_enabled`, `self.pdf_quality`
    - 追加:
      - `self.pdf_engine`（StringVar, 初期値 `'native'`）— エンジン選択
      - `self.pdf_mode`（StringVar, 初期値 `'both'`）— ネイティブ時のモード
      - `self.pdf_dpi`（IntVar）、`self.pdf_jpeg_quality`（IntVar）
      - `self.pdf_png_to_jpeg`（BooleanVar, 初期値 `False`）
      - `self.pdf_lossless_*`（各可逆オプション用 BooleanVar 群）
      - `self.gs_preset`（StringVar, 初期値 `'ebook'`）— GS プリセット
      - `self.gs_custom_dpi`（IntVar）— GS カスタム DPI
      - `self.gs_use_lossless`（BooleanVar）— GS 後に pikepdf 可逆を適用するか
16. **PDF セクション UI の再構築**（現在の ui_app.py L150–184 付近を全面置き換え）:
    - **エンジン選択ラジオボタン2個**（ネイティブ / GhostScript）
      - GS 未検出時は GS ラジオボタンを無効化し、ステータスラベルに「GS未検出」と表示
    - **ネイティブエンジンコントロール群**（エンジンがネイティブのとき表示）:
      - エンジンステータス → 「PyMuPDF + pikepdf」固定表示
      - 圧縮モードラジオボタン3個（非可逆 / 可逆 / 両方）
      - **非可逆コントロール群**（モードが非可逆 or 両方のとき有効化）:
        - DPI スライダー（36–600, 初期値150）
        - JPEG 品質スライダー（1–100, 初期値75）
        - ☐ PNG画像をJPEGに変換する チェックボックス
      - **可逆オプション群**（モードが可逆 or 両方のとき有効化）:
        - ☐ Linearize（Web最適化）
        - ☐ オブジェクトストリーム圧縮
        - ☐ メタデータ除去
        - ☐ Flate再圧縮
        - ☐ 孤立リソース削除
    - **GhostScript エンジンコントロール群**（エンジンが GS のとき表示）:
      - GS プリセットドロップダウン or ラジオボタン（screen / ebook / printer / prepress / default / custom）
      - カスタム DPI 入力（preset が custom のとき有効化）
      - ☐ pikepdf 構造最適化も適用する チェックボックス
      - ☐ 以下、可逆オプション群（共通ウィジェット）
17. **`_refresh_pdf_engine_status()` を更新** — PyMuPDF/pikepdf のインポート可否 + GS 検出状態を表示
18. **`_update_pdf_controls()` に書き換え** — エンジン選択 + モードラジオボタンの選択に応じてネイティブ/GS コントロール群を表示・非表示切替。さらに `png_to_jpeg` チェックがOFFのとき JPEG 品質スライダーの横に「※JPEG元画像にのみ適用」と補足
19. **`_toggle_pdf_slider()` を削除**、エンジン選択・モードラジオボタンの `command` で `_update_pdf_controls()` を呼ぶ
20. **`start_compress()` のエンジン判定ロジックを書き換え** — `pdf_engine` に応じて UI からパラメータを読み取り `compress_folder()` に渡す
21. **スレッド起動時の引数マッピング更新**

### Phase 5: クリーンアップと整合性

22. `compressor_launcher.spec` に PyMuPDF / pikepdf の hidden imports を追加
23. `Documentation/README.md` の PDF セクション更新 — GS 要件削除、新エンジン・PNG→JPEG変換オプションの説明追加
24. `Documentation/flow_sequence_and_class_diagrams.md` の Mermaid 図を更新

---

**Verification**

- **PNG→JPEG変換テスト**: PNG埋め込みPDFに対して `png_to_jpeg=True` / `False` の両方で圧縮し、True時はJPEGに変換されていること、False時はPNGのままリサイズのみされていることを確認
- **アルファチャンネルテスト**: 透過PNG埋め込みPDFで `png_to_jpeg=True` 時に白背景合成が正しく行われ、出力画像に不整合がないことを確認
- **JPEG元画像テスト**: JPEG埋め込みPDFでは `png_to_jpeg` 設定に関わらず常にJPEG品質で再圧縮されることを確認
- **可逆のみモードテスト**: 可逆モードでは画像の内容が一切変化しないことを確認
- **UIテスト**: モード切替時に非可逆/可逆コントロール群が正しく連動、`png_to_jpeg` OFF時にJPEG品質スライダーに補足が表示されることを確認
- **回帰テスト**: JPG/PNG単体画像圧縮・ZIP展開・CSV・クリーンアップに影響がないことを確認
- **単体テスト**: 画像のみの PDF、テキストのみの PDF、画像＋テキスト混合 PDF、暗号化 PDF をそれぞれ3モード（非可逆/可逆/両方）で圧縮し、出力が有効な PDF であること・サイズ変化が妥当であることを確認
- **エッジケース**: 埋め込み画像が 0 個の PDF でエラーにならないこと、巨大画像（数千px）を含む PDF で DPI ダウンサンプルが機能すること

---

**Decisions**

- **PNG→JPEGはデフォルトOFF**: ロスレス画像の品質を保つ安全側をデフォルトとし、容量削減を優先するユーザーがONにする設計
- **アルファ画像の白背景合成**: JPEG はアルファ非対応のため、PNG→JPEG 変換時はアルファを白背景で合成する（透過が意味を持つ PDF の場合にユーザーが判断できるようデフォルトOFF）
- **JPEG品質スライダーの適用範囲**: `png_to_jpeg=False` 時、JPEG品質は元々JPEG形式だった埋め込み画像にのみ適用。PNG画像にはDPIリサイズのみ適用
- **GS + pypdf の即時完全削除**: 段階的移行ではなく、このフェーズで pypdf/PyPDF2 関連コードを完全に削除する
- **GhostScript を第二エンジンとして残置**: PyMuPDF では不十分な場合（特殊なフォント埋め込み PDF、PostScript 由来の複雑な構造等）の代替手段として GS を利用可能にする。GS 未インストール環境では UI 上で無効化される
- **GS エンジン選択時も pikepdf 可逆を適用可能**: GS 再蒸留後に pikepdf 構造最適化を直列適用するオプションを提供
- **pikepdf を必須依存に**: pypdf/PyPDF2 フォールバックは廃止
- **2段パイプライン**: 「両方」モード時は lossy（画像圧縮）→ lossless（構造最適化）の順
- **全画像対象**: 閾値なしで全埋め込み画像を再圧縮（DPI スライダーで間接的に制御。元画像より小さくなる場合のみ差し替えるガード付き）
- **可逆オプション個別制御**: Linearize / オブジェクトストリーム / メタデータ除去 / 重複除去をチェックボックスで個別に ON/OFF
