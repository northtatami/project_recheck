# Re:Check v0.1 Exec Plan

## 0. 目的
本ドキュメントは、`docs/specs/recheck_v0.1.md` に基づいて Re:Check v0.1 を実装するための実行計画書である。  
実装時のブレを防ぎ、Codex や他の実装担当者が **何を作るか / 何を作らないか / どの順で進めるか** を明確にすることを目的とする。

---

## 1. 実装方針

### 1.1 基本方針
- 仕様書準拠で実装する
- v0.1 は **動く最小完成版** を優先する
- 機能を広げすぎない
- GUI は Windows ローカル向けの 3 ペイン構成を軸にする
- 「比較」「確認」「保存」に集中し、判定や運用機能は入れない

### 1.2 優先順位
以下の順で価値を出す。

1. プロジェクト作成・保存・切替
2. Base / Compare 比較
3. Scope 選択（全体 / 選択 / 複数）
4. 差分一覧表示
5. Preview 表示
6. スナップショット保存・比較ログ保存
7. 履歴パネル
8. UI の磨き込み

### 1.3 非目標
v0.1 では実装しない。

- 判定
- 重要度
- ラベル
- コメント運用
- 差し戻し管理
- 同期
- マージ
- 自動修正
- ルールエンジン
- 高度な内容差分解析

---

## 2. 想定技術構成

### 2.1 推奨
- Python
- PySide6

### 2.2 想定モジュール分割
以下は推奨構成であり、既存リポジトリ構成があればそれに従う。

```text
src/
  recheck/
    app.py
    ui/
      main_window.py
      setup_dialog.py
      history_panel.py
      models/
    core/
      project_store.py
      snapshot_store.py
      compare_service.py
      preview_service.py
      file_scanner.py
    utils/
      path_utils.py
      open_external.py
      filetype_utils.py
    resources/
```

---

## 3. 実装フェーズ

## Phase 0: 事前確認
### 目的
既存リポジトリの構成を確認し、Re:Check の置き場所と実装方式を決める。

### 作業
- リポジトリを確認
- 既存の GUI / app / tools / src 構成があるか確認
- Re:Check を既存構成に載せるか、新規に最小構成を作るか決定
- 実行方法（例: `python -m ...`）を決める

### 完了条件
- Re:Check の配置先が決まっている
- 起動エントリーポイント方針が決まっている

---

## Phase 1: プロジェクト管理と初回設定
### 目的
アプリ起動時に最低限のプロジェクト概念を成立させる。

### 作業
- 初回設定ダイアログ作成
- プロジェクト保存形式を決める
- 以下の保存項目を実装
  - プロジェクト名
  - ルートフォルダ
  - スナップショット保存先
  - 除外ルール
  - 最後に使った Base / Compare
- プロジェクト作成 / 保存 / 読込 / 切替を実装
- 上部 `Project` セレクタと `...` メニューの骨組みを実装

### 完了条件
- 初回起動時にセットアップできる
- 保存済みプロジェクトを再読込できる
- プロジェクト切替ができる

---

## Phase 2: スナップショット保存と比較基盤
### 目的
比較に必要なデータ基盤を作る。

### 作業
- ファイルスキャン処理実装
- スナップショット保存形式を決める
- スナップショット保存を実装
- Base / Compare の読込を実装
- 比較処理を実装
  - relative path
  - file name
  - size
  - modified time
- 差分種別を実装
  - added
  - removed
  - modified
  - unchanged
- 比較ログ保存形式を決める
- 比較ログ自動保存を実装

### 完了条件
- 2 つのスナップショットを比較できる
- added / removed / modified / unchanged を返せる
- 比較ログが保存される

---

## Phase 3: メイン画面の骨組み
### 目的
3 ペイン UI を成立させる。

### 作業
- メイン画面作成
- 上部ヘッダー配置
- 左: Scope ペイン
- 中央: Diff Results ペイン
- 右: Preview ペイン
- `履歴` ボタン配置
- `⚙` ボタン配置
- `Ctrl+K` の入口だけ先に置いてもよい

### 完了条件
- 3 ペイン構成で画面が成立する
- 主要ボタンが配置される

---

## Phase 4: Scope ペイン
### 目的
比較対象範囲をユーザーが選べるようにする。

### 作業
- 比較範囲モード実装
  - 全体
  - 選択
  - 複数
- フォルダツリー表示
- 展開 / 折りたたみ
- チェックボックス選択
- 選択状態の保持
- 可能であれば差分件数バッジ表示

### 完了条件
- 全体 / 単一 / 複数フォルダ比較が切り替えられる
- 選んだ範囲が中央結果に反映される

---

## Phase 5: Diff Results ペイン
### 目的
差分を一覧として確認できるようにする。

### 作業
- Path 表示
- サマリーカード表示
  - 追加
  - 削除
  - 更新
  - 同一
- サマリーカード押下でフィルタ
- 検索ボックス
- 差分一覧テーブル
- 基本列実装
  - 種別
  - ファイル名
  - 相対パス
  - 前回更新日時
  - 今回更新日時
  - 前回サイズ
  - 今回サイズ
- 行選択で Preview 連動
- 同一の初期非表示は実装できるなら入れる

### 完了条件
- 差分一覧が見える
- 追加 / 削除 / 更新 / 同一で絞れる
- 検索できる
- 行選択で右ペイン更新する

---

## Phase 6: Preview ペイン
### 目的
前回 / 今回の内容を並べて確認できるようにする。

### 作業
- 基本情報表示
  - ファイル名
  - 種別
  - 相対パス
- 左右 2 カラム比較領域
  - 左 = Base
  - 右 = Compare
- 差分状態による `なし` 表示
- 初期対応プレビュー実装
  - 画像
  - テキスト
  - PDF
  - 音声
- 音声プレビュー実装
  - 再生 / 一時停止
  - シーク
  - 再生時間
  - 可能なら簡易波形
- Office 系は外部起動ボタンのみ実装
- 動画は簡易実装できるなら追加

### 完了条件
- 画像 / テキスト / PDF / 音声を左右比較できる
- 追加 / 削除時に片側 `なし` が表示される
- 外部起動ができる

---

## Phase 7: 履歴パネル
### 目的
保存済みスナップショットと比較結果を必要時だけ開けるようにする。

### 作業
- `履歴` ボタン押下で履歴パネル表示
- Snapshots 一覧表示
- Saved Compares 一覧表示
- 操作実装
  - Base に設定
  - Compare に設定
  - 結果を開く
  - 閉じる

### 完了条件
- 履歴が常時表示されない
- 必要時に開ける
- 過去スナップショットを Base / Compare に再利用できる

---

## Phase 8: UI 調整
### 目的
やわらかモダン寄りの見た目に整える。

### 作業
- 余白調整
- 角丸調整
- ボタン配置整理
- `Project [▼] [⋯]` と `⚙` の役割整理
- 3 ペインの見出しを明確化
- サマリーカードの視認性向上
- フォルダツリーと差分一覧の視線導線調整

### 完了条件
- 画面役割が直感的に分かる
- 左 = 範囲、中 = 差分、右 = 比較 の理解がしやすい

---

## 4. MVP 完了条件
v0.1 MVP は以下を満たしたら完了とする。

1. 初回設定でプロジェクト作成できる
2. 保存済みプロジェクトを切替できる
3. Base / Compare を選んで比較できる
4. 全体 / 単一 / 複数フォルダ比較ができる
5. 追加 / 削除 / 更新 / 同一 を一覧表示できる
6. サマリーカードで絞り込みできる
7. 差分一覧選択で Preview が更新される
8. 画像 / テキスト / PDF / 音声を左右表示できる
9. Office ファイルを外部起動できる
10. 比較実行時に比較ログが保存される
11. 履歴から Base / Compare を再設定できる

---

## 5. 保留項目
以下は v0.1 では保留として扱う。

- 動画の本格対応
- 高精度波形表示
- ハッシュ比較
- ルールエンジン
- ラベル / メモ / コメント
- HTML レポート強化
- コマンドパレット強化
- Everything 連携

---

## 6. 実装時の注意

### 6.1 やりすぎ防止
以下は勝手に拡張しない。

- 自動判断ロジック
- 差し戻しワークフロー
- 同期 / マージ
- 高度なメディア解析

### 6.2 音声優先
プレビューでは音声対応を優先する。  
動画は簡易対応できる場合のみ追加する。

### 6.3 UI 方針
- 左 = どこを比較するか
- 中 = 何が変わったか
- 右 = 前回と今回を見比べる
- 履歴は常時見せない

---

## 7. 最終成果物
実装完了時には以下を揃える。

- ソースコード
- 必要な設定 / サンプルファイル
- 実行方法ドキュメント
- 実装完了レポート
  - changed files
  - アーキテクチャ概要
  - 実行方法
  - 実装済み範囲
  - 保留項目

---

## 8. 一文要約

**Re:Check v0.1 は、プロジェクト単位でフォルダ差分を保存・比較し、範囲選択と左右プレビューで確認するための最小完成版を作る計画である。**

---

## 実装デルタメモ（v0.1 改修）

既存 v0.1 計画に対する実装上の補強ポイント。

- Snapshot は軽量メタデータ保存に寄せ、プレビュー用実ファイルは別キャッシュ管理へ分離
- Preview cache 設定をアプリ設定へ追加
  - 最大世代数
  - 最大総容量
  - 対象拡張子
- Base / Compare はプロジェクト内スナップショット選択を主軸にし、外部フォルダ取込は Project メニュー配下に配置
- ヘッダーを 2 行構成へ再設計し、`比較実行` を主要アクションとして明確化
- 音声プレビューを簡易波形付きへ強化
- PDF は先頭ページ表示を安定経路として実装し、外部起動フォールバックを維持
- 言語設定（日本語 / English）を導入し i18n 拡張しやすい構造へ整理
- 比較実行時は未保存状態を検知した場合に確認ダイアログを出し、`保存して比較 / 保存せず比較 / キャンセル` を選択可能にする
- 3 ペイン構成を維持したまま Preview ペインの表示/非表示切替を追加

## v0.1 delta note (2026-03-11)
- Hardened project-switch/new-project reset so Base/Compare/results/preview state does not leak across projects.
- Added non-modal post-create guidance that no snapshot exists yet.
- Compare now explicitly requires sufficient snapshot context before execution.
- Fixed preview pipeline classification by using original path context rather than cache blob filename.
- Moved preview collapse UX to pane-local header control.
- Standardized visible diff-table timestamps to `YYYY-MM-DD HH:MM:SS`.
- Clarified Base/Compare role labels as previous/current snapshot flow.

## v0.1 delta note (2026-03-11, polish-2)
- Refined header composition for dense use: compact project row plus clear Base/Compare selector area with directional hint.
- Increased diff-table density and kept filename rendering single-line for scanability.
- Changed relative path rendering to show parent folder only, with explicit root marker for root-level files.
- Added app-level text size setting and keyboard controls (`Ctrl+0`, `Ctrl+=`, `Ctrl+-`).
- Added automatic CSV export on compare execution under `compare_exports` with datetime naming.
- Added project-menu action to open compare CSV export folder quickly.
- Added lightweight productivity shortcuts (`Ctrl+Enter`, `Ctrl+S`, `Ctrl+H`, `Ctrl+F`, `Esc`).
- Added subtle scope tree cues for changed folders (added/modified) while preserving calm UI.

## v0.1 delta note (2026-03-11, polish-3)
- Added snapshot-action scope-tree refresh hook so project folder structure updates are reflected after `Save Snapshot` and `Save and Compare`.
- Applied compact two-line Base/Compare timestamp/size headers in diff table for faster scanning.
- Tuned Base/Compare relation hint alignment to sit with selector row context.
- Rebalanced project selector width for readability without overtaking Base/Compare selector prominence.
- Added lightweight embedded video preview path in existing preview pane, with environment fallback to external-open guidance.
- Kept compare status model unchanged (no move/rename detection introduced).

## v0.1 delta note (2026-03-11, polish-4)
- Hardened create-project flow to enforce clean reset before loading the created project, preventing stale Base/Compare and result carryover.
- Updated post-create status guidance to include explicit next step (save snapshot before compare).
- Rebalanced default diff-table column widths so core review columns remain visible first.
- Strengthened compare CSV discoverability with save-path status message and quick-open action for latest compare CSV.

## v0.1 delta note (2026-03-11, polish-5)
- Scope control is consolidated to `whole` vs `selected` only; selected mode now supports multi-folder checks directly.
- Compare filtering now strictly respects checked scope folders in selected mode and no longer degrades to whole-project output when none are checked.
- Scope tree refresh keeps checked-folder intent when folders still exist, while incorporating newly added folders.
- Timestamp presentation is converted to JST for practical JP-facing UI/CSV readability without changing stored source timestamps.
- Default splitter balance shifts width from Scope to Diff Results, and settings menu includes a simple layout reset action.

## v0.1 delta note (2026-03-11, polish-6)
- Added lightweight separators in project menu for clearer action grouping.
- Enforced scope-visual semantics by mode: whole mode hides tree checkboxes; selected mode shows checkboxes for filtering.
- Added mode-coupled scope path label updates to reduce ambiguity of active compare scope.

## v0.1 delta note (2026-03-11, polish-7)
- Finalized whole-mode scope semantics by removing visible checkbox indicators entirely in whole mode.
- Preserved selected-mode checked-state intent across mode/refresh transitions where practical.
- Applied subtle separator margin styling in project menu to improve section readability.

## v0.1 delta note (2026-03-11, polish-8)
- Extended selected-mode scope handling to include project-root node selection.
- Connected root-node selection to whole-project filtering semantics in compare scope evaluation.
- Ensured whole-mode remains fully view-only with no root or child checkbox indicators visible.

## v0.1 delta note (2026-03-11, polish-9)
- Compare execution now builds and retains the full diff dataset for the current Base/Compare pair.
- Scope mode switches and checkbox changes now re-filter the current in-memory dataset immediately without requiring another Compare execution.
- Preview selection is refreshed against the filtered visible rows so stale preview content is cleared or replaced when the current row falls out of scope.

## v0.1 delta note (2026-03-11, polish-10)
- Shifted heavy IO/compute operations to background tasks to improve responsiveness for large projects (project load, snapshot save, compare run, history load, scope scan).
- Added explicit busy/progress feedback during long-running operations.
- Switched scope-tree refresh to background scan + chunked UI rendering to reduce blocking during large folder trees.
- History panel now loads lazily/on-demand, reducing eager startup/project-switch work.

## v0.1 delta note (2026-03-11, polish-11)
- Optimized large-result table rendering by chunked/staged row application instead of one heavy bind pass.
- Added explicit result-render progress messaging during staged table population.
- Added debounced search-triggered re-filter/rebind to avoid excessive repeated table rebuilds on large datasets.

## v0.1 delta note (2026-03-11, polish-12)
- Added modal progress UX for snapshot-save operations so save-in-progress states are explicit and interaction is safely blocked during save.
- Added post-create onboarding prompt for initial snapshot save to reduce first-project confusion.
- Reduced scope-tree up-front rendering cost by switching to shallow-first materialization with deferred child-node loading on expand.
- Reduced filter-switch overhead by caching scope/status result groups per compare dataset and reusing them during UI filtering.

## v0.1 delta note (2026-03-12, phase1-diff-modelview)
- Migrated Diff Results table layer to model/view (`QTableView` with a dedicated read-only table model and filter proxy).
- Kept compare computation unchanged; filter switching and search now update proxy/view state over already prepared result data.
- Applied first-display default visibility of added/removed/modified rows with unchanged hidden, while preserving `all` to include unchanged rows.

## v0.1 delta note (2026-03-12, quick-guide)
- Added first-run quick-guide onboarding as a lightweight spotlight overlay that points users to key v0.1 actions (settings, project setup, snapshot save, Base/Compare selection and compare execution).
- Implemented persistent completion state in app settings so the guide auto-runs only for users who have not completed/skipped it.
- Added a manual quick-guide reopen action in the settings menu for optional re-run.

## v0.1 delta note (2026-03-12, quick-guide-refine)
- Adjusted setup dialog wording for first-time clarity (`比較対象フォルダ` label and concise purpose/help text).
- Split quick-guide final action into two steps (snapshot selection vs compare execution) to reduce ambiguity.
- Tightened spotlight targeting to the exact controls for selection and compare execution.

## v0.1 delta note (2026-03-12, onboarding-refine-2)
- In brand-new project setup, comparison target folder input now starts empty (no auto-filled user home path).
- Added clearer target-folder placeholder text and validation wording for missing/invalid target folders.

## v0.1 delta note (2026-03-12, pre-distribution-hardening)
- Added built-in default directory exclusions during snapshot scanning and scope-tree path scanning: `node_modules`, `.git`, `.venv`, `venv`, `__pycache__`.
- Hardened snapshot persistence to atomic write for `manifest.json` and snapshot `index.json` (`.tmp` write + replace).
- Added safe stale-temp cleanup/ignore path for snapshot temp files so incomplete temp artifacts are not treated as valid snapshot data.
