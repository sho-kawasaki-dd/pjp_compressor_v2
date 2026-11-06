## Plan: CMYK→RGB 変換の追加

PDF埋め込み画像と単体画像ファイルの両経路で、CMYK画像を安全にRGBへ変換する処理が欠落している。Pillow組み込みの `ImageCms` を使った ICC プロファイル優先変換ヘルパーを各モジュールに追加し、画像読み込み直後に適用する。新規依存なし。

---

### Phase 1: pdf_utils.py の修正

1. **`_convert_cmyk_to_rgb()` ヘルパー追加** — `_open_pdf_raster_image()` 付近に配置。ICC プロファイルがあれば `ImageCms.profileToProfile()` で変換、なければ `pil_img.convert('RGB')` にフォールバック
2. **`_load_pdf_raster_image_with_soft_mask()` に注入** (pdf_utils.py L155) — `_open_pdf_raster_image()` の直後で呼ぶ。これで PNG/JPEG 両経路を一括カバーし、soft mask 合成前に RGB 系モードへ統一される (*depends on 1*)
3. **`_normalize_pdf_png_source_image()` に明示的 CMYK 分岐** (pdf_utils.py L88-L105) — belt-and-suspenders として `CMYK` モードを明示ハンドル (*depends on 1*)
4. **`debug_stats` に `cmyk_converted` カウンター追加** — CMYK 画像の存在をデバッグ出力で把握可能にする (*depends on 2*)

### Phase 2: image_utils.py の修正 (*parallel with Phase 1*)

5. **`_convert_cmyk_to_rgb()` ヘルパー追加** (image_utils.py) — pdf_utils.py 側と同一ロジック
6. **`compress_image_pillow()` に注入** (image_utils.py L46) — `Image.open()` 直後 (*depends on 5*)
7. **`compress_png_pngquant()` のリサイズ前処理に注入** (image_utils.py L133) — pngquant 用の一時ファイル生成時 (*depends on 5*)

### Phase 3: テスト追加

8. **test_pdf_utils.py** — `_make_cmyk_jpeg_bytes()` ヘルパー追加、CMYK JPEG が JPEG/PNG 両経路で黒潰れせず変換されるテスト (*depends on Phase 1*)
9. **test_image_utils.py** — CMYK JPEG を生成し `compress_image_pillow()` / `compress_png_pngquant()` が正常処理することを検証 (*depends on Phase 2*)

---

**Relevant files**
- `backend/core/pdf_utils.py` — `_load_pdf_raster_image_with_soft_mask()` (L155), `_normalize_pdf_png_source_image()` (L88), `compress_pdf_lossy()` debug_stats
- `backend/core/image_utils.py` — `compress_image_pillow()` (L46), `compress_png_pngquant()` (L133)
- `tests/unit/test_pdf_utils.py` — CMYK テスト追加
- `tests/unit/test_image_utils.py` — CMYK テスト追加

**Verification**
1. `pytest tests/unit/test_pdf_utils.py -v` — 既存 + 新規 CMYK テストパス
2. `pytest tests/unit/test_image_utils.py -v` — 既存 + 新規 CMYK テストパス
3. `pytest tests/ -v` — 全テスト回帰なし
4. 手動: CMYK 画像含む PDF を DPI=100 で非可逆圧縮し黒潰れしないことを目視確認

**Decisions**
- numpy 不使用 — `ImageCms`（Pillow 内蔵）で完結
- ヘルパーは各モジュールに private 配置（既存 `_clamp_quality()` パターン踏襲）
- 変換は最上流（画像読み込み直後）で一括適用
- Ghostscript 経路は GS 自身が CMYK を処理するため対象外
