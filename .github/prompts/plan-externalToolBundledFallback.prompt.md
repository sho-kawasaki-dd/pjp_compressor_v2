## Plan: Ghostscript / pngquant の system 優先 + bundled fallback 対応

system 優先、bundled 次点、未検出なら unavailable の共通 resolver を先に作り、その結果を capability 表示・Ghostscript 実行・pngquant 実行・PyInstaller 同梱定義へ流す形で進める。Ghostscript は実行失敗時に対象 PDF だけスキップ、pngquant は現状どおり Pillow fallback を維持する前提で固める。計画はセッション側にも保存済み。

bundled 配置はプロジェクトルート直下の `vendor/` を前提にし、その下へ `Ghostscript-windows/` と `pngquant-windows/` を置く。共通 resolver はこの `vendor/` 配下を優先探索し、開発実行と one-folder 配布の両方で同じ規約を使う。

## Steps

1. Phase 1: app-root 基準で `vendor/` を解決する共通 resolver を [shared/runtime_paths.py](shared/runtime_paths.py#L11) 起点で追加し、system / bundled / unavailable と実行パスを返せる形にする。bundled 側は `vendor/Ghostscript-windows/` と `vendor/pngquant-windows/` を前提にし、開発実行と one-folder 配布の両方で同じ規約を使う。
2. Phase 1: capability 契約を [backend/contracts.py](backend/contracts.py#L31) で拡張し、Ghostscript と pngquant の source を保持できるようにする。available 判定は後方互換を維持する。
3. Phase 1: 現在の重複検出を統一する。[backend/capabilities.py](backend/capabilities.py#L25) と [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L697) の Ghostscript 探索、[backend/core/image_utils.py](backend/core/image_utils.py#L139) と [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L266) の pngquant 探索を共通 resolver 利用へ寄せる。system 側に見つからない場合は `vendor/` 配下を探し、そこでも見つからない場合にのみ unavailable とする。
4. Phase 2: Ghostscript failure policy を [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L707) と [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L835) に実装し、検出済みでも subprocess 失敗時は対象 PDF のみスキップ扱いにする。job 全体は継続させる。
5. Phase 2: pngquant は通常 PNG と PDF 内 PNG の両方で、system / bundled のどちらを使ったかをメッセージへ出しつつ、失敗時は現行どおり Pillow fallback を維持する。[backend/core/image_utils.py](backend/core/image_utils.py#L125) と [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L259) が対象。
6. Phase 2: ログ導線を [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py#L260) に揃え、起動時に検出結果、処理時に bundled 採用・Ghostscript skip 理由・pngquant fallback 理由を出す。
7. Phase 3: UI 表示を source-aware に更新する。[frontend/ui_tkinter_controller.py](frontend/ui_tkinter_controller.py#L145) と必要に応じて [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py) で、Ghostscript と pngquant の状態を OK ではなく system / bundled / 未検出 で表示する。既存の enable/disable 制御は available ベースを維持しつつ、Ghostscript が system にも bundled にも無い場合は PDF 圧縮の GS タブを無効化する。
8. Phase 4: bundled 同梱を build へ反映する。[compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec#L8) に `vendor/` 同梱定義を追加し、[compressor_launcher.ps1](compressor_launcher.ps1) では `vendor/` 不在時に警告だけ出してビルド継続できるようにする。
9. Phase 4: README を bundled fallback 前提へ更新する。[Documentation/README.md](Documentation/README.md#L123) と [Documentation/README.md](Documentation/README.md#L149) を中心に、system 優先 / bundled fallback / unavailable 時の挙動、vendor 配置規約、ライセンス確認責務を明記する。
10. Phase 5: テストを拡張する。[tests/unit/test_capabilities.py](tests/unit/test_capabilities.py) に解決順序、[tests/unit/test_pdf_utils.py](tests/unit/test_pdf_utils.py) に Ghostscript skip と PDF 内 pngquant fallback、[tests/unit/test_image_utils.py](tests/unit/test_image_utils.py) に通常 PNG の bundled pngquant、[tests/integration/test_job_runner.py](tests/integration/test_job_runner.py#L223) に file-level 継続とログ確認を追加する。
11. Phase 5: vendor あり / なしの両条件で PyInstaller build と手動確認を行い、開発実行と dist 実行の双方で source 表示と fallback 挙動を検証する。

## Relevant files

- [shared/runtime_paths.py](shared/runtime_paths.py#L11) — app-root / frozen / resource の基準があり、vendor resolver の自然な追加先
- [backend/contracts.py](backend/contracts.py#L31) — CapabilityReport の source 表現と UI 契約の追加先
- [backend/capabilities.py](backend/capabilities.py#L25) — 現在の system PATH 検出を共通 resolver へ寄せる中心
- [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L259) — PDF 内 pngquant と Ghostscript 実行、skip/fallback 文言の中心
- [backend/core/image_utils.py](backend/core/image_utils.py#L125) — 通常 PNG の pngquant / Pillow fallback の中心
- [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py#L260) — file-level 継続とログの集約点
- [frontend/ui_tkinter_controller.py](frontend/ui_tkinter_controller.py#L145) — UI 表示更新の中心
- [compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec#L8) — vendor 同梱定義の追加先
- [Documentation/README.md](Documentation/README.md#L123) — 配布定義と運用説明の更新先

## Verification

1. unit で system 優先、bundled fallback、unavailable を固定する。
2. unit で Ghostscript が bundled path を使うこと、実行失敗時に skip 用メッセージを返すことを確認する。
3. unit で pngquant が bundled path を使い、失敗時は Pillow fallback を維持することを確認する。
4. integration で Ghostscript failure が job 全体を止めず、対象ファイルだけ skip または mirror copy されることを確認する。
5. vendor あり / なしの両条件で PyInstaller build を走らせ、vendor なしは警告のみ、vendor ありは dist に同梱されることを確認する。
6. 開発実行と dist 実行の両方で、UI が GS:system / GS:bundled / GS:未検出、pngquant:system / pngquant:bundled / pngquant:未検出 のいずれかを示し、起動時ログと処理ログに source が出ることを確認する。

## Decisions

- 探索順は system → bundled `vendor/` → unavailable。
- 開発実行と Windows one-folder 配布の両方でプロジェクトルート直下の `vendor/` を探索する。
- `vendor/` 配下のバイナリはリポジトリに含める。
- Ghostscript failure は native へ自動リトライせず、対象 PDF だけスキップする。
- pngquant failure は現状どおり Pillow fallback を維持する。
- UI には供給元まで表示し、起動時ログにも検出結果を出す。
- `vendor/` 不在時のビルドは失敗させず、警告だけ出して継続する。
