> From: https://gemini.google.com/app/1d978c556083ff95?is_sa=1&is_sa=1&android-min-version=301356232&ios-min-version=322.0&campaign_id=bkws&utm_source=sem&utm_medium=paid-media&utm_campaign=bkws&pt=9008&mt=8&ct=p-growth-sem-bkws&gclsrc=aw.ds&gad_source=1&gad_campaignid=20437330680&gbraid=0AAAAApk5Bhly-BblMwC5OhYyBfxZ5buzK&gclid=Cj0KCQiAwYrNBhDcARIsAGo3u30YVWf0VRoRaJWyfcYRJGZEBKoLjKU_n1BXn1TdRXgkt7xiAGxaueIaAq_MEALw_wcB

# you asked

def compress_pdf_lossy(input_path, output_path, target_dpi=PDF_LOSSY_DPI_DEFAULT,
                       jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
                       png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT):
    """PyMuPDF で PDF 内の全埋め込み画像を走査し、リサンプル＆再圧縮する（非可逆）。

    引数:
    - input_path: 入力 PDF パス
    - output_path: 出力 PDF パス
    - target_dpi: リサンプル先の DPI（36–600）
    - jpeg_quality: JPEG 再圧縮時の品質（1–100）
    - png_to_jpeg: True の場合、PNG 画像も JPEG に変換して圧縮する。
                   False の場合、PNG 画像はリサイズのみ行いフォーマットを維持する。

    戻り値:
    - (bool, str): 成否とメッセージ
    """
    try:
        doc = fitz.open(input_path)
        replaced_count = 0
        skipped_count = 0
        seen_xrefs = set()

        for page_index in range(len(doc)):
            page = doc[page_index]
            image_list = page.get_images(full=True)
            for img_info in image_list:
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        skipped_count += 1
                        continue

                    img_bytes = base_image["image"]
                    img_ext = base_image.get("ext", "").lower()
                    orig_size = len(img_bytes)

                    # Pillow で画像を開く
                    pil_img = Image.open(io.BytesIO(img_bytes))
                    orig_w, orig_h = pil_img.size

                    # 対象 DPI へリサンプル比率を算出
                    # PDF 上の表示寸法から現在の実効 DPI を推定
                    # （取得できない場合はピクセルベースで判断）
                    img_dpi = base_image.get("xres", 0) or base_image.get("yres", 0)
                    if img_dpi and img_dpi > target_dpi:
                        scale = target_dpi / img_dpi
                        new_w = max(1, int(orig_w * scale))
                        new_h = max(1, int(orig_h * scale))
                        pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
                    # DPI 情報がない、または既に target_dpi 以下ならリサイズしない

                    # --- フォーマット判定 & 再圧縮 ---
                    is_lossless = img_ext in ("png", "bmp", "tiff", "tif", "gif")

                    if is_lossless and not png_to_jpeg:
                        # PNG 維持: リサイズ済み画像を PNG (Deflate) で再保存
                        buf = io.BytesIO()
                        # アルファがあればそのまま、なければ RGB
                        if pil_img.mode not in ("RGB", "RGBA", "L", "LA"):
                            pil_img = pil_img.convert("RGBA" if pil_img.mode == "PA" else "RGB")
                        pil_img.save(buf, format="PNG", optimize=True)
                        new_bytes = buf.getvalue()
                    else:
                        # JPEG 系 or (PNG → JPEG 変換): JPEG で再圧縮
                        if pil_img.mode in ("RGBA", "PA", "LA"):
                            # アルファチャンネルを白背景で合成
                            background = Image.new("RGB", pil_img.size, (255, 255, 255))
                            background.paste(pil_img, mask=pil_img.split()[-1])
                            pil_img = background
                        elif pil_img.mode != "RGB":
                            pil_img = pil_img.convert("RGB")
                        buf = io.BytesIO()
                        pil_img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
                        new_bytes = buf.getvalue()

                    # サイズが小さくなった場合のみ差し替え
                    if len(new_bytes) < orig_size:
                        doc.update_stream(xref, new_bytes)
                        replaced_count += 1
                    else:
                        skipped_count += 1

                except Exception:
                    skipped_count += 1
                    continue

        doc.save(output_path, garbage=4, deflate=True)
        doc.close()

        total_images = replaced_count + skipped_count
        detail = f"画像{total_images}個中{replaced_count}個を再圧縮"
        if png_to_jpeg:
            detail += ", PNG→JPEG変換あり"
        return True, f"PDF非可逆圧縮(PyMuPDF): {os.path.basename(input_path)} → OK ({detail}, DPI={target_dpi}, JPEG品質={jpeg_quality})"
    except Exception as e:
        return False, f"PDF非可逆圧縮失敗: {os.path.basename(input_path)} ({e})"
このコードをわかりやすく解説してもらっていいですか？

---

# gemini response

ご提示いただいたPythonコードは、PDF内の画像を一つずつ取り出し、解像度（DPI）を下げたり、PNGをJPEGに変換したりすることで、PDF全体のファイルサイズを軽量化（非可逆圧縮）しようとする非常に論理的なアプローチです。

まずは、このコードが**「意図している処理の流れ」**を分かりやすく解説します。その後、ご指示に従いエコーチェンバーを避け、**このコードに潜んでいる「事実上の誤り（バグ）」と「PDFの仕様に基づく反論・修正案」**を率直にお伝えします。

---

### 1. コードが意図している処理の流れ（解説）

このスクリプトは、大きく分けて以下の5つのステップで構成されています。

1. **画像の重複排除 (`seen_xrefs` の活用)**
   PDFでは、全ページにある同じロゴなどは「1つの画像データ」として保存され、各ページから参照（XREF）されます。`seen_xrefs` に一度処理した画像のID（xref）を記録することで、同じ画像を何度も無駄に圧縮するのを防いでいます。
2. **画像の抽出とリサイズ判定**
   `doc.extract_image()` で画像データを取り出し、Pillow (`Image.open`) で読み込みます。設定した `target_dpi` を超えている場合、Lanczos（ランチョス）法という高品質な縮小アルゴリズムを使ってリサイズを試みます。
3. **フォーマット別の再圧縮**
   - **可逆圧縮（PNG等）を維持する場合:** `png_to_jpeg` が `False` なら、PNGのまま最適化（Optimize=True）して再保存します。
   - **JPEGに変換・再圧縮する場合:** 透過（アルファチャンネル）を持つ画像はそのままJPEGにできないため、白背景（`255, 255, 255`）を作成し、その上に画像を合成してからJPEGとして圧縮する丁寧な処理が行われています。
4. **サイズの比較と更新**
   圧縮後のデータサイズ (`len(new_bytes)`) が、元のサイズ (`orig_size`) より小さくなった場合のみ、PDF内のデータを上書き (`update_stream`) します。これにより、逆にファイルサイズが増加してしまう「圧縮太り」を防いでいます。
5. **最終最適化して保存**
   `garbage=4`（不要になったオブジェクトの完全削除や参照の最適化）と `deflate=True`（非圧縮ストリームの圧縮）を指定して保存し、極限までPDFを軽量化しようとしています。

---

### 2. 事実の訂正と重大な懸念点（エラーになる理由）

コードのアルゴリズム自体は素晴らしいですが、PDFの内部仕様とPyMuPDFの挙動に照らし合わせると、**このコードは意図通りに動かず、高確率でPDFの画像を破損（表示不可に）させます。** 理由は以下の2点です。

#### ① `update_stream` によるPDFの破損（致命的な誤り）
コードでは `doc.update_stream(xref, new_bytes)` を使って画像データを直接上書きしています。しかし、PDFの画像データ（XObject）は、「バイナリデータ（Stream）」と「辞書データ（メタデータ）」のセットで構成されています。
* **事実:** `update_stream` はバイナリデータのみを書き換えます。メタデータ（画像の幅 `/Width`、高さ `/Height`、圧縮方式 `/Filter` など）は**一切更新されません**。
* **結果:** リサイズによってピクセル数（幅・高さ）が変わったのにメタデータが古いままだったり、元のフォーマットがPNG（`/FlateDecode`）だったのにバイナリだけJPEG（`/DCTDecode`）に書き換えられたりすると、PDFリーダーはデータの解読に失敗し、画像が真っ白になるかエラーを出します。

#### ② DPI推定ロジックが機能していない（コメントと実装の乖離）
コメントには「PDF上の表示寸法から現在の実効DPIを推定」とありますが、実際のコードは `base_image.get("xres", 0)` を読み取っています。
* **事実:** PDFに埋め込まれた画像データ自体には、`xres` や `yres`（DPIメタデータ）が記録されていないことが非常に多いです。
* **結果:** ほぼすべての画像で `img_dpi` が `0` と判定され、`if img_dpi and img_dpi > target_dpi:` の条件を満たさず、**実際には一切リサイズ処理が行われない（素通りする）**という結果になります。

---

### 3. 複数の解決アプローチ

これらの問題を解決するには、いくつかのアプローチが考えられます。目的や許容できる複雑さに応じて選択する必要があります。

* **アプローチA: 辞書データ（メタデータ）を手動で書き換える（PyMuPDFで完結）**
  `update_stream` を使った後に、`doc.xref_set_key()` などの関数を使って、画像の `/Width`, `/Height`, `/Filter`, `/ColorSpace` などのPDF内部辞書を新しい画像に合わせて手動で書き換える方法です。
  * *メリット:* 元のPDFのレイアウトを完全に維持しやすい。
  * *デメリット:* PDFの内部仕様（カラースペースの変更など）を深く理解する必要があり、実装の難易度が高い。

* **アプローチB: 古い画像を削除し、新しい画像をページに挿入し直す（PyMuPDFの標準機能）**
  該当ページの画像の表示領域（BBox）を取得し、`page.insert_image()` を使って新しい画像を描画し直し、古いxrefを無効化する方法です。
  * *メリット:* メタデータの不整合などをPyMuPDFが自動でよしなに処理してくれるため、エラーが起きにくい。
  * *デメリット:* 画像の上にテキストが乗っているような複雑なレイヤー構造の場合、描画順序（Zインデックス）が変わってしまうリスクがある。

* **アプローチC: Pythonツール（Ghostscriptなど）に委譲する**
  画像抽出と再圧縮を自作せず、Pythonから `subprocess` で Ghostscript などのPDF処理に特化した実績のある外部エンジンを呼び出す方法です。
  * *メリット:* 非常に安定しており、PDFの破損リスクが最も低い。
  * *デメリット:* 実行環境にGhostscriptなどの外部ソフトをインストールする必要がある。

実用的なスクリプトを目指すのであれば、メタデータの不整合を安全に回避しやすい**アプローチB**に近い手法（またはPyMuPDFの比較的新しいバージョンで提供されている `replace_image` 系の仕組み）を採用するのが現実的です。

解説や指摘を踏まえた上で、正しく安全に画像が圧縮・置換されるように修正したコードを作成しましょうか？

---

# you asked

ひとまずアプローチBで修正をお願いします。あとコメントもなるべく細かく入れてください

---

# gemini response

PyMuPDFの標準機能を活かし、画像のメタデータ（辞書）の破損やレイアウト崩れを防ぐ、より安全で確実なアプローチ（アプローチBの発展形）でコードを修正しました。

以前のコードにあった「実効DPIが計算できない問題」と「バイナリのみ書き換えてファイルが壊れる問題」を解消し、さらに「同じ画像が複数ページで使われている場合の効率化」も組み込んでいます。

コード内のコメントをかなり細かく記述しましたので、処理の流れと意図をご確認ください。

```python
import fitz  # PyMuPDF
import io
import os
from PIL import Image

# 定数のダミー（実際の環境に合わせて変更してください）
PDF_LOSSY_DPI_DEFAULT = 150
PDF_LOSSY_JPEG_QUALITY_DEFAULT = 75
PDF_LOSSY_PNG_TO_JPEG_DEFAULT = True

def compress_pdf_lossy(input_path, output_path, target_dpi=PDF_LOSSY_DPI_DEFAULT,
                       jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
                       png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT):
    """
    PyMuPDF で PDF 内の全埋め込み画像を走査し、リサンプル＆再圧縮する（非可逆）。
    安全な `replace_image` メソッドを使用し、PDFの破損を防ぎます。

    引数:
    - input_path: 入力 PDF パス
    - output_path: 出力 PDF パス
    - target_dpi: リサンプル先の DPI
    - jpeg_quality: JPEG 再圧縮時の品質（1-100）
    - png_to_jpeg: True の場合、透過のないPNG等もJPEGに変換。

    戻り値:
    - (bool, str): 成否とメッセージ
    """
    try:
        doc = fitz.open(input_path)
        replaced_count = 0
        skipped_count = 0
        
        # 同じ画像（xref）を何度も再圧縮しないためのキャッシュ
        # 構造: { xref: 圧縮後のバイナリデータ(bytes) または None(圧縮不要/失敗) }
        compressed_cache = {}

        for page_index in range(len(doc)):
            page = doc[page_index]
            # ページ内の全画像情報を取得
            image_list = page.get_images(full=True)
            
            for img_info in image_list:
                xref = img_info[0]

                # --- 1. キャッシュの確認 ---
                # すでに別のページで処理済みの xref の場合、再圧縮処理はスキップして置換だけ行う
                if xref in compressed_cache:
                    new_bytes = compressed_cache[xref]
                    if new_bytes is not None:
                        # ページ上の古い xref を新しい画像データで安全に置換（メタデータも自動更新される）
                        page.replace_image(xref, stream=new_bytes)
                    continue

                # --- 2. 実効DPIの正確な計算 ---
                # PDF上の表示領域（BBox）を取得して、実際の表示DPIを逆算する
                rects = page.get_image_rects(xref)
                if not rects:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue
                
                # 代表として最初の表示領域（ポイント単位、1pt = 1/72インチ）を使用
                rect = rects[0]
                rect_width_pts, rect_height_pts = rect.width, rect.height

                # 画像が非表示（サイズ0）の場合はスキップ
                if rect_width_pts == 0 or rect_height_pts == 0:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                # --- 3. 画像データの抽出と読み込み ---
                base_image = doc.extract_image(xref)
                if not base_image:
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                img_bytes = base_image["image"]
                img_ext = base_image.get("ext", "").lower()
                orig_size = len(img_bytes)

                try:
                    pil_img = Image.open(io.BytesIO(img_bytes))
                except Exception:
                    # Pillowで開けない特殊なフォーマット等は安全のためスキップ
                    compressed_cache[xref] = None
                    skipped_count += 1
                    continue

                orig_w, orig_h = pil_img.size

                # 計算式: 実効DPI = ピクセル数 / (ポイント数 / 72.0)
                effective_dpi_x = orig_w / (rect_width_pts / 72.0)
                effective_dpi_y = orig_h / (rect_height_pts / 72.0)
                effective_dpi = max(effective_dpi_x, effective_dpi_y)

                # --- 4. リサイズ処理 ---
                if effective_dpi > target_dpi:
                    scale = target_dpi / effective_dpi
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    
                    # Pillow 10以降推奨の Resampling.LANCZOS を使用（古い環境なら Image.LANCZOS）
                    resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                    pil_img = pil_img.resize((new_w, new_h), resample_filter)

                # --- 5. フォーマット変換と再圧縮 ---
                is_lossless = img_ext in ("png", "bmp", "tiff", "tif", "gif")
                buf = io.BytesIO()

                if is_lossless and not png_to_jpeg:
                    # PNGを維持する場合
                    if pil_img.mode not in ("RGB", "RGBA", "L", "LA"):
                        # パレットモード(P)などを一般的なモードに変換
                        pil_img = pil_img.convert("RGBA" if "A" in pil_img.mode or "P" in pil_img.mode else "RGB")
                    pil_img.save(buf, format="PNG", optimize=True)
                else:
                    # JPEGとして保存（またはPNGからJPEGへ変換）
                    if pil_img.mode in ("RGBA", "PA", "LA", "P"):
                        if pil_img.mode == "P":
                            pil_img = pil_img.convert("RGBA")
                        # 透過（アルファ）を持つ場合は白背景で合成し、JPEGエラーを防ぐ
                        if "A" in pil_img.mode:
                            background = Image.new("RGB", pil_img.size, (255, 255, 255))
                            background.paste(pil_img, mask=pil_img.split()[-1])
                            pil_img = background
                            
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    pil_img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)

                new_bytes = buf.getvalue()

                # --- 6. サイズ比較とPDFへの反映 ---
                if len(new_bytes) < orig_size:
                    # PyMuPDFの安全な置換APIを使用
                    # これにより、Width/Height/Filter等のメタデータが整合性を保ったまま更新される
                    page.replace_image(xref, stream=new_bytes)
                    
                    # 別のページで同じ画像が出現した時のためにキャッシュに保存
                    compressed_cache[xref] = new_bytes
                    replaced_count += 1
                else:
                    # 圧縮効果がなかった場合は、元の画像を維持
                    compressed_cache[xref] = None
                    skipped_count += 1

        # 最適化して保存（ガベージコレクションとストリームの圧縮）
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()

        total_processed_xrefs = replaced_count + skipped_count
        detail = f"一意の画像{total_processed_xrefs}個中{replaced_count}個を再圧縮"
        if png_to_jpeg:
            detail += ", PNG→JPEG変換あり"
            
        return True, f"PDF非可逆圧縮(PyMuPDF): {os.path.basename(input_path)} → OK ({detail}, DPI={target_dpi}, JPEG品質={jpeg_quality})"
        
    except Exception as e:
        return False, f"PDF非可逆圧縮失敗: {os.path.basename(input_path)} ({e})"
```

### 今回の修正における重要なポイント

1.  **`page.replace_image()` への移行（旧コードの致命的バグの修正）**
    `update_stream` を廃止し、PyMuPDFに用意されている安全な画像置換メソッドを採用しました。これにより、バイナリデータとメタデータ（画像の縦横サイズや圧縮方式）の不一致が起きず、ファイルが壊れるのを防ぎます。レイアウト（Zインデックスなど）も自動で維持されます。
2.  **キャッシュ機構（`compressed_cache`）の導入**
    旧コードでは `seen_xrefs` を使って「2回目以降の同じ画像は完全に無視する」仕様でした。しかし `replace_image` は**ページ単位**の処理であるため、無視してしまうと「1ページ目のロゴは圧縮されたが、2ページ目の同じロゴは元の巨大なサイズのまま残る」という現象が起きます。圧縮済みのバイナリデータをメモリに保持しておくことで、全ページの画像を漏れなく、かつ高速に置換できるようにしています。
3.  **ポイント計算による実効DPIの逆算**
    PDFの表示上の大きさと、画像のピクセル数を割り算することで、実際にどの程度のDPIで紙面に配置されているかを計算するロジックを実装しました。これにより、巨大な画像だけをピンポイントで狙って縮小できるようになります。

コードを実行してみて、特定のPDFでエラーが出る、あるいは想定よりファイルサイズが落ちないなど、追加で確認したい挙動はありますか？