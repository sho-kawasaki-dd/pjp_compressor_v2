# FFmpeg 配布物の調査記録

調査日: 2026-11-01

## 結論

この記録は配布準備の技術的な調査結果であり、ライセンス適合性の法的判断ではありません。
採用候補の実行ファイルとビルド設定、およびFFmpeg本体ソースの版一致は確認できました。一方、外部ライブラリの対応ソース一式・ライセンス確認、ビルド固有のパッチやスクリプト、AGPL-3.0 の本体との配布上の互換性確認は未完了です。**同梱バイナリの再配布は引き続き保留です。**

## ローカルで確認したもの

対象ディレクトリは [`vendor/ffmpeg-windows/`](../vendor/ffmpeg-windows/) です。

| ファイル | サイズ | SHA256 |
|---|---:|---|
| `bin/ffmpeg.exe` | 227,823,104 bytes | `589e50b766d251afdf181dd664d40bd94407e200b019989fd7468c7d118a28d0` |
| `bin/ffprobe.exe` | 227,621,376 bytes | `02264dfa4f56baaa31e443ece8aa16d397f6b008200e7fd184d22b9009e75fd3` |
| `LICENSE` | 35,147 bytes | `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` |
| `README.txt` | 45,523 bytes | `e7db34704804ed8844e837714eebbf843ca0a499555541df9e47fa2cc033dcb1` |

バイナリ自身の `-version`、`-buildconf`、`-L` を実行して確認しました。

- FFmpeg は `9.0.2-full_build-www.gyan.dev`、静的ビルド、GCC 16.2.0 と表示されます。
- 設定には `--enable-gpl`、`--enable-version3`、`--enable-static` があり、`--enable-nonfree` はありません。
- `-L` は GNU GPL version 3 を表示します。
- 有効な外部ライブラリは多数あります。パッケージ付属 README にはその一覧と多くのバージョンが記載されていますが、一覧はソース一式ではありません。

これらのハッシュは**配置済みファイル**の値です。入手した元アーカイブのハッシュとの照合はできていません。調査時にリポジトリ内で一致するソースアーカイブを確認できず、`git ls-files vendor/ffmpeg-windows` にも追跡対象はありませんでした。したがって、ローカルのバイナリとこのリポジトリのコミットだけでは、配布物の来歴を再現できません。

## 提供された FFmpeg ソースとの照合

`Downloads/FFmpeg-n9.0.2/FFmpeg-n9.0.2/` にある展開済みソースを確認しました。`RELEASE` は `9.0.2` で、`configure`、FFmpeg のソース各ディレクトリ、`LICENSE.md`、`COPYING.GPLv3`、`COPYING.LGPLv2.1`、`COPYING.LGPLv3` などを含みます。確認時の展開内容は 10,424 ファイル、90,361,647 bytes でした。Git履歴（`.git`）は含まれていません。

GitHub の `n9.0.2` タグ参照先は `946fcce07b6dcd0331c8cc609192aeff5e1924f8` で、同梱バイナリの `README.txt` が示すソースコミット `946fcce07b` と完全一致します。また、展開済みツリーの主要ファイル4点のSHA256はGitHubタグ上の同じファイルと一致しました。

| ファイル | SHA256 |
|---|---|
| `RELEASE` | `cb59c54a0c419202b393c39beebcdbef094e480bdea5c82290050c265a1f7508` |
| `LICENSE.md` | `2e1d16c72fd74e12063776371da757322f8b77589386532f4fd8634bde7de1af` |
| `configure` | `5b281b249ad5ad859030b4da0a24ec105b5abff7b3d87a65b302df8bf5fd9833` |
| `COPYING.GPLv3` | `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` |

したがって、FFmpeg本体の版・参照コミットの一致と主要ファイルの内容は確認できています。ただしGit履歴と元ZIPがないため、展開ツリー全体の来歴・完全性までは独立に証明していません。また、これはFFmpeg本体部分の確認であり、バイナリ全体の対応ソースをそろえたことの証明ではありません。

### FFmpeg のライセンス説明と有効設定の照合

`LICENSE.md` の対象リビジョンと、実行ファイルの `-buildconf` を照合した結果です。

| FFmpeg のライセンス説明 | バイナリで確認した有効設定 | 確認事項 |
|---|---|---|
| GPLv2 の外部ライブラリは `--enable-gpl` が必要 | `avisynth`, `frei0r`, `libcdio`, `libdavs2`, `librubberband`, `libvidstab`, `libx264`, `libx265`, `libxavs2`, `libxvid` が有効 | 設定上、GPL 部分を有効化しています。 |
| LGPLv3 の外部ライブラリには `--enable-version3` が必要 | `gmp`, `libaribb24`, `liblensfun` が有効 | `--enable-version3` が有効です。 |
| Apache-2.0 の一部ライブラリには version 3 が必要 | `libvmaf`, `libopencore-amrnb`, `libopencore-amrwb` が有効 | FFmpeg の `LICENSE.md` は VMAF / OpenCORE を Apache-2.0 と説明しています。各実バージョンのライセンス文も別途確認が必要です。 |
| FDK AAC / OpenSSL は GPLv2/v3 と非互換と記載 | `--enable-libfdk-aac` / `--enable-openssl` は見当たらない | この2つの有効化は確認されませんでした。 |
| `--enable-nonfree` は配布不能なビルドにする | `--enable-nonfree` は見当たらない | FFmpeg設定上の `nonfree` 指定はありません。これだけで全依存関係・第三者権利の確認が完了するわけではありません。 |

上表は、FFmpeg の `LICENSE.md` が明示するカテゴリと設定上の有効化を突き合わせたものです。その他の有効ライブラリも多数あり、各依存先の**正確なビルド版のライセンス、例外、著作権表示**の確認が別途必要です。`vendor/ffmpeg-windows/README.txt` は外部ライブラリ名と多くの版を列挙していますが、ライセンス文やソースアーカイブ、全依存のソースハッシュは含みません。

FFmpeg の `LICENSE.md` は、`libavcodec/jfdctfst.c`、`libavcodec/jfdctint_template.c`、`libavcodec/jrevdct.c` の IJG 由来コードについて、実行ファイルのみを配布する場合の IJG クレジットと変更内容の説明にも言及しています。最終配布資料でこの表示要件を確認してください。

## アプリの機能要件から見た外部ライブラリ候補

アプリの動画実装（`backend/settings.py`、`backend/core/video_utils.py`、`backend/capabilities.py`）と実FFmpeg統合テストを確認しました。動画機能が使うのはローカル入力を ffprobe で解析し、映像を MP4 に再エンコードして、出力を再解析・検証する経路です。

| アプリ機能 | 実装で必要な機能 | 外部ライブラリ候補 |
|---|---|---|
| H.264 出力 | `libx264` エンコーダ | `x264` |
| H.265 出力（任意選択） | `libx265` エンコーダ | `x265` |
| AAC 変換 | FFmpegの組み込み `aac` エンコーダ | 外部AACライブラリは不要 |
| 既定でコピーする音声 | MP3 / AC-3 / E-AC-3 / ALAC / FLAC のデマルチプレクス・MP4格納 | FFmpeg組み込み機能で扱う。`VIDEO_MP4_AUDIO_COPY_CODECS` が対象を定義 |
| `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.wmv`, `.m4v` の入力 | FFmpegのデマルチプレクサと必要なデコーダ | 通常の対応はFFmpeg本体側。実ファイル受入テストで確認 |
| スケーリング、ピクセル形式変換、MP4出力、ffprobe JSON | `scale`、`yuv420p`、MP4 muxer、format/stream/chapter probe | FFmpeg本体の機能 |

したがって、現在の H.264 / H.265 の両方を維持する場合、**明示的に必要と見込まれる外部ライブラリは x264 と x265 が中心**です。`aac` は実装上必須ですが、外部ライブラリではありません。gyan.dev full build の他の多数の外部ライブラリ（AV1群、字幕描画、音声処理、ネットワーク、ハードウェア連携等）は、現行の動画処理コードからは直接要求されていません。

H.265 を製品機能として維持しない判断なら、x265を省いてx264だけにできます。ただし現在の設定/UIは `libx265` を選択可能にしており、機能を残すならx265もビルド・ソース・ライセンス確認の対象です。x264 / x265の上流説明はGPLを示しますが、採用する正確なソースリビジョンの `COPYING` を取得して確認してください。特に `--enable-version3` のビルドに組み込む前に、両ライブラリの当該版がGPLv2-or-laterであることをソース上で確認し、選択するGPLv3との条件を記録します。

### 小さく再ビルドする場合の設計案（未実行）

FFmpeg `n9.0.2` ソースの `configure` には `--disable-autodetect`、`--disable-ffplay`、`--enable-libx264`、`--enable-libx265` があります。最初の試作では、FFmpegの既定の内部codec/demuxer/muxer/filterを不用意に削る `--disable-everything` は使わず、自動検出される任意ライブラリを切り、必要な外部エンコーダだけを明示的に有効化する方針が安全です。

両コーデックを維持する場合の**configure設計の骨子**（実ビルドコマンドではなく、クロスコンパイル環境や依存の `--extra-*` 指定は未確定）:

```text
--disable-autodetect
--disable-ffplay
--enable-gpl
--enable-version3
--enable-libx264
--enable-libx265
```

静的配布にするか、ツールチェーンやx264/x265のビルドをどのように固定するかは別途設計・検証が必要です。`--disable-autodetect` を入れた後、ビルド設定・`-encoders`・`-demuxers`・`-decoders`・`-muxers`・`-filters` の出力を検査し、受入ファイルで実動作を確認します。外部ライブラリをx264/x265に絞ることと、FFmpeg内部codecの対応形式を狭めることを混同しないでください。

この再ビルドでは、現行full buildの外部依存一式を確保する代わりに、FFmpegソースに加えて、採用したx264/x265の正確なソース、ライセンス文、ビルド手順・パッチを確保することになります。ビルド後に実際の設定と実行機能を監査し、表示されるライセンスやバイナリが想定どおりの範囲に収まったことを確認するまで、ソース提供義務や配布可否を確定しません。

## 上流配布物の確認

- [gyan.dev の Windows builds](https://www.gyan.dev/ffmpeg/builds/) はビルド配布ページで、FFmpeg のソースコードそのものの配布元ではありません。
- [GyanD/codexffmpeg の 9.0.2 リリース](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2) の GitHub API で確認できる6つのアセットは、essentials / full / full-shared の `.7z` または `.zip` バイナリアーカイブです。外部ライブラリを含む対応ソース一式やビルドスクリプトのアーカイブは見つかりませんでした。
- リリースリポジトリの README は、Releases が gyan.dev 上のビルドのミラーであると説明しています。
- FFmpeg 本体は上記のとおり、バイナリ README のソースコミットと `n9.0.2` タグの一致を確認しました。それでも、静的リンクされた外部ライブラリのソース、適用パッチ、gyan.dev のビルドスクリプト、再現に必要なツールチェーン情報はそろっていません。

## 配布前に残る作業

1. ビルド提供者から、有効な外部ライブラリすべての対応ソース、正確なリビジョン、適用パッチ（またはパッチなしの確認）、ビルドスクリプトと環境情報を取得する。提供されないものは、各依存元から同じリビジョンのソースとライセンス文を確保する。
2. 取得物をFFmpeg本体ソースとともにバイナリから独立して保管し、ソース・ライセンス・バイナリのチェックサムと対応関係を記録する。現状の vendor README の版一覧だけで、外部ソース確保済みとは扱わない。
3. 実際に有効な機能・外部ライブラリごとにライセンス・例外・表示条件を確認し、`--enable-gpl` / `--enable-version3` を含む構成の配布条件を評価する。FFmpeg 本体のGPL表示だけで全依存関係の確認を代替しない。
4. 本体 AGPL-3.0 と静的 FFmpeg 実行ファイルを同一インストーラーで配布する構成を、法務に詳しい専門家を含めて確認する。別プロセスで呼び出している事実だけで互換性を断定しない。互換性の確認と FFmpeg 対応ソース提供義務の履行は、別々の完了条件とする。
5. バイナリと対応ソースの提供場所・取得方法を決め、配布 README / ダウンロード案内 / インストーラー資料へ記載する。利用者が実際にソース一式を取得できることと、必要な著作権表示が含まれることをリリース前に確認する。

対応ソースを確保できない、または配布条件を満たすと確認できない場合は、このビルドを再配布しないでください。ソース一式を適切に確保・提供できる別のビルドを選ぶことも検討してください。
