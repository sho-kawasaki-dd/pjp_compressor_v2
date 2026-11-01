# FFmpeg 配布物の調査記録

調査日: 2026-11-01

## 結論

この記録は配布準備の技術的な調査結果であり、ライセンス適合性の法的判断ではありません。
採用候補の実行ファイルとビルド設定、およびFFmpeg本体ソースの版一致は確認できました。一方、外部ライブラリの対応ソース一式・ライセンス確認、ビルド固有のパッチやスクリプト、AGPL-3.0 の本体との配布上の互換性確認は未完了です。**同梱バイナリの再配布は引き続き保留です。**

## 現行の製品方針

アプリは H.265/HEVC のエンコード・デコードを行いません。HEVC映像streamを含む入力は ffprobe のstream metadataで検出し、ffmpegを起動せず元ファイルをコピーします。未監査の `vendor/ffmpeg-windows/` gyan.dev full build は実行時fallbackと凍結版・`vendor.zip`の梱包対象から除外しました。動画機能は現在 PATH 上の system `ffmpeg` / `ffprobe` に依存します。

これは一時的な安全側の配布・実行方針です。Windows向けx264-only再ビルドは下記のとおり作成・動作検証しましたが、配布上の条件確認は未完了です。同梱fallbackと梱包除外はそのまま維持し、新バイナリも自動で同梱版へ差し替えていません。

## x264限定のWindowsビルド（2026-11-01）

成果物は [`build/ffmpeg-x264-only/package/bin/`](../build/ffmpeg-x264-only/package/bin/) に保存しています。FFmpeg内部の一般的なcodec・filter・コンテナ機能は残したため、「全機能を絞った最小サイズ」ではなく、**任意の外部メディアライブラリをx264だけに限定した静的ビルド**です。

実行ファイル・ライセンス表示・対応ソースアーカイブ・ビルドと検証の記録をまとめた[保管用ZIP](../build/ffmpeg-x264-only/ffmpeg-x264-only.zip)も作成しました。公開配布を承認したものではありません。

| 実行ファイル | サイズ | SHA256 |
|---|---:|---|
| `ffmpeg.exe` | 31,188,992 bytes | `dd8bb87fbd05be31c17c37ce2fa2e8b910ceacd4ed5bccdccb8f43e4fd8bfa7d` |
| `ffprobe.exe` | 30,968,320 bytes | `df293436b81eda08b3b4101a9d18a2659f50d8d0bf7c8f1637e5765c378e1a89` |

- 入力ソース: 提供されたFFmpeg `n9.0.2` と `x264-master`。x264のAPI番号は164、ビルド上の版表示は `0.164.x` です。Git履歴がなく、x264の上流コミットは未特定のため、使用ツリーをソースアーカイブとSHA256で固定しました。ソースへのパッチは適用していません。
- ツール: MinGW GCC 14.2.0（`x86_64-w64-mingw32`）、GNU Make 4.4.1、NASM 3.02、pkg-config 3.0.10。並列数は4。不足していたMSYS2のmake・nasm・diffutilsを追加しました。
- 構成: `--target-os=mingw32 --arch=x86_64 --enable-static --disable-shared --disable-autodetect --enable-gpl --enable-version3 --enable-libx264 --extra-ldflags=-static` を使用。ffplay・network・avdevice・hardware accelerationは無効化しました。
- HEVCの全encoder・decoder・parserに加え、HEVC専用BSF・raw demuxer/muxerと `dovi_split` を明示的に無効化しました。生成設定の `CONFIG_HEVCPARSE` も0です。MP4/MOV/MKVなどのコンテナからHEVCというcodec識別情報を読むことは可能です。
- `libx264` / `libx264rgb` と組み込みAACが有効で、x265は含まれません。`-L` の表示はGPL version 3 or laterです。x264のヘッダーとencoderソースにGPLv2-or-laterの許諾を確認しました。
- WindowsのDLL importは両実行ファイルとも `bcrypt.dll`、`KERNEL32.dll`、`msvcrt.dll`、`SHELL32.dll` のみです。MSYS2やx264のDLLを別途置かなくても起動します。
- アプリの全テストを新FFmpeg/ffprobeで実行し、314件成功・Tk初期化理由で1件スキップでした。GUI回帰を新しいPythonプロセスで再実行し、11件すべて成功しました。テスト入力の生成だけは旧full buildを使い、アプリの実処理には新ビルドを使用しました。
- HEVCのMP4、MKV、H.264主映像＋HEVC追加映像のMKVについて、新ffprobeで検知し、ffmpegのエンコード実行が0回、コピー元とコピー先のSHA256一致を確認しました。
- [監査資料](../build/ffmpeg-x264-only/audit/) にconfigure引数・生成設定・ソースアーカイブ・ライセンス・ツール情報・DLL import・テスト結果を保存しています。ソースアーカイブのSHA256は `ffmpeg-source.tar.gz`: `bfbb1d6c80bf4519449438a5992d2e683436236a78441fd9f1626278ed4fb647`、`x264-source.tar.gz`: `936243796617b86f7d6ced919c3485891a866945923b3ae07091bf688a7768f0` です。

### 再ビルド

[ビルドスクリプト](../scripts/build_ffmpeg_x264.sh) はMSYS2 Bashで実行します。`PATH` にMinGW GCC・pkg-config・MSYS2のmake/NASM等を配置し、ソース2つと未使用の出力ディレクトリを引数に指定してください。入力ソースはコピーして使用し、原本を変更しません。

```bash
export PATH=/c/mingw64/bin:/ucrt64/bin:/usr/bin
bash scripts/build_ffmpeg_x264.sh \
  'C:\Users\tohbo\Downloads\FFmpeg-n9.0.2\FFmpeg-n9.0.2' \
  'C:\Users\tohbo\Downloads\x264-master\x264-master' \
  'C:\Users\tohbo\python_programs\pjp_compressor_v2\build\ffmpeg-x264-new'
```

同じソース・ツールチェーンで中断したビルドを再開する場合だけ `RESUME=1` を設定します。コピー元との内容一致を確認して続行します。出力先はGit管理対象外なので、配布に採用する前に成果物と対応ソースの保管場所・提供方法を別途確定してください。

**ビルド成功は再配布の法的承認ではありません。** GCC/MinGWランタイムを含む表示条件・本体との配布構成・対応ソース提供方法・H.264等の特許上の条件は引き続き確認が必要です。

## 旧full buildについてローカルで確認したもの

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
| AAC 変換 | FFmpegの組み込み `aac` エンコーダ | 外部AACライブラリは不要 |
| 既定でコピーする音声 | MP3 / AC-3 / E-AC-3 / ALAC / FLAC のデマルチプレクス・MP4格納 | FFmpeg組み込み機能で扱う。`VIDEO_MP4_AUDIO_COPY_CODECS` が対象を定義 |
| `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.wmv`, `.m4v` の入力 | FFmpegのデマルチプレクサと必要なデコーダ | 通常の対応はFFmpeg本体側。実ファイル受入テストで確認 |
| スケーリング、ピクセル形式変換、MP4出力、ffprobe JSON | `scale`、`yuv420p`、MP4 muxer、format/stream/chapter probe | FFmpeg本体の機能 |

したがって、現行方針で外部ライブラリとして必要と見込まれるのは x264 です。`aac` は実装上必須ですが、外部ライブラリではありません。gyan.dev full build の他の多数の外部ライブラリ（AV1群、字幕描画、音声処理、ネットワーク、ハードウェア連携等）は、現行の動画処理コードからは直接要求されていません。

このアプリではH.265を使用しない方針のためx265は対象外です。x264のライセンスは採用する正確なソースリビジョンの `COPYING` で確認してください。特に `--enable-version3` のビルドに組み込む場合は、x264側のライセンス条件との整合を記録します。

### 初期の再ビルド設計案（上記のWindowsビルドで具体化）

FFmpeg `n9.0.2` ソースの `configure` には `--disable-autodetect`、`--disable-ffplay`、`--enable-libx264`、`--enable-libx265` があります。最初の試作では、FFmpegの既定の内部codec/demuxer/muxer/filterを不用意に削る `--disable-everything` は使わず、自動検出される任意ライブラリを切り、必要な外部エンコーダだけを明示的に有効化する方針が安全です。

H.264専用の**configure設計の骨子**（実際に使った全引数は上記ビルドの監査資料に保存）:

```text
--disable-autodetect
--disable-ffplay
--enable-gpl
--enable-version3
--enable-libx264
```

静的配布にするか、ツールチェーンやx264のビルドをどのように固定するかは別途設計・検証が必要です。`--disable-autodetect` を入れた後、ビルド設定・`-encoders`・`-decoders` と生成された `config_components.h` を検査し、HEVC encoder/decoder/parserが有効でないことと、受入ファイルの実動作を確認します。FFmpeg CLIには `-parsers` 一覧オプションがないため、parserは生成設定とビルド記録で確認します。外部ライブラリをx264に絞ることと、FFmpeg内部codecの対応形式を狭めることを混同しないでください。

この再ビルドでは、FFmpegソースに加えて採用したx264の正確なソース、ライセンス文、ビルド手順・パッチを確保することになります。ビルド後に実際の設定と実行機能を監査し、表示されるライセンスやバイナリが想定どおりの範囲に収まったことを確認するまで、ソース提供義務や配布可否を確定しません。

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
