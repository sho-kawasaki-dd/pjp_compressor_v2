## DRAFT: 改善アプローチ比較

- A 最小改修（[compressor_launcher_tkinter.py](compressor_launcher_tkinter.py#L1-L27)中心）
  - 利点: 変更差分が小さく、短時間で適用可能。
  - 欠点: [ui_tkinter.py](ui_tkinter.py#L81-L112) のインポート時副作用が残り、起動時の不確定性が残存。
- B 起動正規化レイヤー（推奨）
  - 利点: GUI描画後の音再生、トップレベル例外捕捉、実行位置基準パスを一貫して実現。ショートカット起動やexe運用に強い。
  - 欠点: [configs.py](configs.py#L77-L86) と起動周辺を中規模で整理する必要あり。
- C ブートストラップ全面分離
  - 利点: 監視性・保守性は最大。
  - 欠点: 今回要件に対して過剰で、回帰リスクと工数が大きい。

## Plan: Tkinter起動ハードニング

PyInstaller exeのダブルクリック運用を前提に、B案で進める。主眼は、1) 音声再生をGUI描画後に遅延実行、2) 起動全体をトップレベル例外ハンドリングで保護し、ログ保存＋messageboxのフェイルセーフを追加、3) 実行ファイル位置基準で資源パスを解決してCWD依存を排除、の3点。加えて、運用事故を避けるため起動ファイル名の参照不整合も同時に是正する。

**Steps**

1. エントリポイント整理: [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py#L1-L27) を main関数化し、インポートを保護下へ移して起動時例外を一括捕捉できる構造にする。
2. 音声タイミング修正: App生成後、mainloop開始前に直接鳴らす構造を廃止し、Tkの after 系で初回描画直後に再生予約する。
3. 例外フェイルセーフ: 起動失敗時にアプリ基準ディレクトリへクラッシュログを書き出し、messageboxでユーザー通知する。messagebox失敗時の最終退避も持たせる。
4. パス基準統一: [configs.py](configs.py#L77-L86) の相対ディレクトリ定義を、実行体基準の絶対解決へ寄せる。PyInstaller時の実体位置と通常実行時の両方を吸収する。
5. サウンド資源整合: [sound_utils.py](sound_utils.py#L74-L78) とランチャー側の受け渡し規約を統一し、バンドル内資源と実行位置資源の優先順位を固定する。
6. 参照不整合修正: [compressor_launcher.ps1](compressor_launcher.ps1#L1-L4) と [Documentation/README.md](Documentation/README.md#L6) の起動ファイル名を現行構成に合わせる。
7. インポート副作用の抑制点検: [ui_tkinter.py](ui_tkinter.py#L81-L112) の起動時副作用を最小化し、少なくとも起動失敗時にランチャー側で捕捉可能な順序へ調整する。

**Verification**

- スクリプト実行とexe実行の両方で、初期画面が先に表示されてから起動音が鳴ることを確認。
- ショートカットから作業ディレクトリをずらして起動し、入力/出力/サウンド参照が崩れないことを確認。
- 強制例外を注入して、ログ生成とmessagebox通知が機能することを確認。
- PS1起動とREADME手順で実ファイル参照が一致することを確認。

**Decisions**

- 配布形態: PyInstaller exeを最優先。
- エラー方針: ログ保存＋messagebox表示。
- パス方針: 実行ファイルまたはスクリプト位置基準に統一。
- 適用範囲: ランチャー本体に加え、ps1/READMEの参照整合まで実施。
