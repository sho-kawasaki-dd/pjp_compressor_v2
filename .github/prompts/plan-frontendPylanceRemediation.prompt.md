frontend 配下の Pylance 警告を、設計を壊さず段階的に減らしてください。主な原因は次の 4 点です。

1. mixin 間の `self` 契約が暗黙になっている
2. [frontend/ui_tkinter_mapper.py](frontend/ui_tkinter_mapper.py#L3) で `Any` を使っている
3. [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py#L15) で widget 属性と Tk 前提が型として見えていない
4. `tkinterdnd2` の型情報が弱い

段階的な対応順は次のとおりです。

1. 型契約の土台を追加する
2. state の Tk 変数を型付けする
3. view の `self` 前提と widget 属性を明示する
4. controller の依存関係を整理する
5. `tkinterdnd2` 由来の残警告を隔離する

各 Phase は単独で実行し、変更後は Pylance 診断差分を確認してください。不要な設計変更、機能変更、UI 変更は行わないでください。

## Phase 1: 型契約の土台

```text
frontend 配下について、Pylance 警告を減らすための最小変更の型基盤を追加してください。

目的:
- mixin 間で暗黙になっている `self` 契約を型として表現する
- `frontend/ui_tkinter_mapper.py` の `app: Any` をやめる
- 実行時挙動は変えない

対象:
- frontend/ui_tkinter_mapper.py
- frontend/ui_tkinter.py
- 必要なら frontend/ui_contracts.py を追加してよい
- frontend 以外は触らない

実装方針:
- `Protocol` または型付き基底のうち、変更量が少ない方を採用する
- mapper が使う属性・メソッドを最初に型として定義する
- 過剰な suppress は避ける
- 既存スタイルを維持する

完了条件:
- `ui_tkinter_mapper.py` から `Any` を除去している
- frontend の診断を確認し、mapper 関連警告の差分を報告している
- 変更ファイルと残る警告の種類を簡潔にまとめている
```

## Phase 2: state の型明示化

```text
frontend の Pylance 警告を段階的に減らしています。今回は state 層だけを対象に、Tk 変数群の型を明示してください。

目的:
- `frontend/ui_tkinter_state.py` の `StringVar` / `IntVar` / `BooleanVar` を明示的に型付けする
- view / controller から参照される状態を読みやすくする
- 挙動は変えない

対象:
- frontend/ui_tkinter_state.py
- 必要なら Phase 1 で作成した契約ファイル
- 他ファイルのロジック変更は禁止

実装方針:
- `initialize_ui_state` 内の各属性に型注釈を付ける
- どの属性が UI 状態か分かるように整える
- 無意味なコメントは追加しない

完了条件:
- Tk 変数群に明示的な型が付いている
- frontend の診断を確認し、state 起因の警告差分を報告している
- 変更点を state の型注釈に限定して要約している
```

## Phase 3: view の `self` 契約と widget 属性の明示化

```text
frontend の Pylance 警告を段階的に減らしています。今回は `frontend/ui_tkinter_view.py` を対象に、`self` の前提と widget 属性を型として明示してください。全面的な設計変更は禁止です。

目的:
- `TkUiViewMixin` が前提にしている `self` の契約を明示する
- widget 属性の型を Pylance が追えるようにする
- 実行時挙動は変えない

対象:
- frontend/ui_tkinter_view.py
- 必要なら Phase 1 の契約ファイル
- 必要最小限で frontend/ui_tkinter.py

実装方針:
- Tk 系メソッドを使う前提が Pylance に伝わるようにする
- state / controller 由来の属性やメソッド依存を、`Protocol` かクラス属性注釈で明示する
- `main_canvas`, `main_container`, `log_text`, `notebook`, 各種 `StringVar` / `IntVar` / `BooleanVar`, 主要なボタン・スケール類を型で説明する
- `tkinterdnd2` の `drop_target_register` と `dnd_bind` は局所的な型補助で扱う
- レイアウトや機能は変えない

完了条件:
- `ui_tkinter_view.py` の主要な attribute-access 警告が減っている
- 診断差分を確認し、減った警告の種類を報告している
- 残件があれば理由を短く分類している
```

## Phase 4: controller の整理

```text
frontend の Pylance 警告を段階的に減らしています。今回は `frontend/ui_tkinter_controller.py` を対象に、型の見通しと保守性を上げるための整理を行ってください。大規模な全面書き換えは禁止です。

目的:
- controller が依存している state / view の要素を型として表せるようにする
- 大きい `self` 依存の塊を少し整理して読みやすくする
- 実行時挙動は変えない

対象:
- frontend/ui_tkinter_controller.py
- 必要なら frontend/ui_contracts.py
- 必要最小限で frontend/ui_tkinter.py

実装方針:
- `_update_pdf_controls`, `_update_resize_controls`, `start_compress` 周辺の依存を型で追えるようにする
- 補助メソッドや小さな型分離は可
- suppress を増やして黙らせるのではなく、型で説明する方向を優先する
- UI と機能は変えない

完了条件:
- controller 起因の警告が減っている
- frontend 全体の診断差分を報告している
- 責務の切り方を短く説明している
```

## Phase 5: `tkinterdnd2` の残警告隔離

```text
frontend の Pylance 警告を段階的に減らしています。今回は `tkinterdnd2` 由来の残警告だけを対象に、局所的に隔離・整理してください。機能変更は禁止です。

目的:
- `tkinterdnd2` の型不足に起因する警告を局所化する
- view の可読性を上げる
- 実行時挙動は変えない

対象:
- frontend/ui_tkinter_view.py
- frontend/ui_tkinter.py
- 必要なら frontend/dnd_adapter.py を追加してよい

実装方針:
- `drop_target_register` と `dnd_bind` の扱いを、局所的な adapter / cast / Protocol のいずれかで整理する
- `DND_FILES` と `dnd_available` の扱いも読みやすくする
- 広域の `type: ignore` は避ける
- DnD 未導入時の既存分岐は維持する

完了条件:
- DnD 由来の警告が減っている
- frontend 全体の診断差分を報告している
- DnD 周辺の残リスクがあれば短くまとめている
```

## 実行ルール

```text
- 各 Phase は単独で実行する
- 変更範囲はその Phase の対象ファイルにできるだけ限定する
- 実行時挙動を変えない
- 不要なリファクタや命名変更をしない
- 各 Phase の最後に診断差分を確認する
- 残警告は無理に suppress せず、理由を分類して報告する
```

## 補足

現時点で最も警告が集中しているのは、[frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py#L24), [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py#L87), [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py#L157), [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py#L370), [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py#L464) 付近です。ここは Tk 本体、state、controller、DnD 拡張にまたがる前提が一度に現れているため、Phase 3 で重点的に扱ってください。
