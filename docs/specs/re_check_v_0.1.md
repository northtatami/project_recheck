# Re:Check — Diff Review for folders 仕様書 v0.1

## 1. 概要

### 1.1 目的
Re:Check は、**前回と今回のフォルダ差分を、範囲選択・履歴保存・左右プレビュー付きで確認するためのローカルGUIツール**である。  
主目的は、提出物・納品物・素材群・ドキュメント群などの差分を、**人が見て判断しやすい形で一覧表示すること**にある。

### 1.2 コンセプト
本ツールは以下に特化する。

- どこを比較するか選べる
- 何が変わったか一覧で見える
- 前回と今回を並べて確認できる
- 比較結果とスナップショットを保存して後で振り返れる

### 1.3 非目的
v0.1 では以下を目的にしない。

- 差分の自動判定
- 重要度付け
- ラベル付け
- 差し戻し管理
- 同期
- マージ
- 自動修正
- ルール違反の自動評価

---

## 2. 想定ユーザー

- フォルダ単位で提出物・納品物を確認する担当者
- 前回版と今回版の差分を見比べたいユーザー
- 音声・画像・テキスト・PDFなどの素材差分を確認したいユーザー
- プロジェクトごとに比較履歴を残して追いたいユーザー

特に以下の用途を想定する。

- 納品物の差分確認
- 修正版の確認
- サブフォルダ単位での変更確認
- 音声ファイル差分の再生比較
- 履歴から過去比較を再表示

---

## 3. 対応環境

### 3.1 対象環境
- Windows デスクトップ環境
- ローカルファイルアクセス可能であること

### 3.2 実装前提（推奨）
- Python ベースのデスクトップアプリ
- GUI フレームワークは PySide6 を想定

※ 実装方式は変更可能だが、v0.1 では Windows ローカルGUIアプリであることを優先する。

---

## 4. 用語定義

### 4.1 プロジェクト
Re:Check 内で保存される比較単位。以下を保持する。

- プロジェクト名
- ルートフォルダ
- スナップショット保存先
- 除外設定
- 直近の比較設定

### 4.2 スナップショット
ある時点のフォルダ状態を保存したもの。  
比較対象の一覧情報として使用する。

### 4.3 比較ログ
Base と Compare の比較結果を保存したもの。  
再表示や振り返りに使用する。

### 4.4 Base
比較元。

### 4.5 Compare
比較先。

### 4.6 スコープ
比較範囲。以下のモードを持つ。

- 全体
- 選択
- 複数

---

## 5. 画面構成

メイン画面は以下で構成する。

- 上部ヘッダー
- 左ペイン：Scope
- 中央ペイン：Diff Results
- 右ペイン：Preview
- 履歴パネル（通常非表示、履歴ボタン押下時に表示）

### 5.1 全体レイアウト方針
- 3ペイン構成を基本とする
- 左＝どこを見るか
- 中＝何が違うか
- 右＝前回と今回を見比べる
- 履歴は常時表示せず、必要時のみ表示

---

## 6. 上部ヘッダー仕様

### 6.1 タイトル表示
- 表示名：`Re:Check`
- サブタイトル：`Diff Review for folders`

### 6.2 プロジェクト関連
- `Project セレクタ`
  - 保存済みプロジェクトを切り替える
- `⋯` ボタン
  - プロジェクト単位のメニューを開く

#### `⋯` メニュー項目
- プロジェクト設定
- プロジェクト名を変更
- ルートフォルダを変更
- 比較対象フォルダを編集
- 除外ルールを編集
- 保存先を開く
- プロジェクトを書き出す

### 6.3 比較対象セレクタ
- `Base セレクタ`
- `Compare セレクタ`

両者は保存済みスナップショットを選択可能とする。

### 6.4 アクションボタン
- `比較実行`
- `スナップショット保存`
- `履歴`
- `日付で比較`
- `Ctrl+K`（コマンドパレット）
- `⚙`（アプリ設定）

### 6.5 アプリ設定（⚙）
- 外観
- テーマ
- 既定保存先
- プレビュー設定
- ショートカット
- バージョン情報

---

## 7. 左ペイン：Scope

### 7.1 目的
比較対象の場所・範囲を選ぶ。

### 7.2 表示要素
- 見出し：`Scope`
- 補助文：`比較対象を選ぶ`

### 7.3 比較範囲モード
以下を表示する。

- 全体
- 選択
- 複数

#### 動作
- 全体：プロジェクト全体を比較
- 選択：単一フォルダのみ比較
- 複数：複数フォルダを比較

### 7.4 フォルダツリー
- ルートフォルダ表示
- サブフォルダのツリー表示
- 展開 / 折りたたみ
- チェックボックスによる対象選択
- 現在の選択対象を強調表示
- フォルダごとの差分件数バッジ表示

#### 差分件数バッジ例
- `final [8]`
- `preview [4]`
- `assets [3]`

### 7.5 要件
- サブフォルダ単位で確認できること
- 複数フォルダを選んで比較できること
- 選択結果が中央ペインの差分一覧に反映されること

---

## 8. 中央ペイン：Diff Results

### 8.1 目的
差分を一覧で確認する。

### 8.2 表示要素
- 見出し：`Diff Results`
- 補助文：`差分を確認する`
- 現在位置表示（Path）

#### Path 表示例
`案件A / deliverables / final`

### 8.3 サマリーカード
以下を表示する。

- 追加
- 削除
- 更新
- 同一

#### 表示例
- `追加 12`
- `削除 3`
- `更新 8`
- `同一 152`

#### 動作
- カード押下で一覧フィルタとして機能する

### 8.4 検索・フィルタ
- 検索ボックス
- 追加フィルタ
- 削除フィルタ
- 更新フィルタ
- 同一フィルタ

#### 検索対象
- ファイル名
- 相対パス

### 8.5 差分一覧
基本列は以下とする。

- 種別
- ファイル名
- 相対パス
- 前回更新日時
- 今回更新日時
- 前回サイズ
- 今回サイズ

### 8.6 種別定義
- 追加：Compare にのみ存在
- 削除：Base にのみ存在
- 更新：Base / Compare の両方に存在し、内容または状態が異なる
- 同一：差分なし

### 8.7 差分一覧の動作
- 行選択で右ペイン更新
- 列ソート
- スクロール表示
- 同一は初期非表示でもよい

---

## 9. 右ペイン：Preview

### 9.1 目的
選択中ファイルについて、前回と今回を並べて確認する。

### 9.2 表示要素
- 見出し：`Preview`
- 補助文：`前回 / 今回を見る`

### 9.3 基本情報
- ファイル名
- 種別
- 相対パス

### 9.4 比較エリア
左右2カラム固定。

- 左：前回
- 右：今回

それぞれ以下を表示する。

- プレビュー領域
- ファイルサイズ
- 更新日時

### 9.5 差分状態による表示
#### 追加
- 前回：`なし`
- 今回：プレビュー表示

#### 削除
- 前回：プレビュー表示
- 今回：`なし`

#### 更新
- 前回 / 今回 両方表示

#### 同一
- 前回 / 今回 両方表示

### 9.6 初期対応プレビュー形式
#### 正式対応
- 画像
- テキスト
- PDF
- 音声

#### 動画
- 可能なら簡易対応
- v0.1 では必須ではないが、実装可能なら入れる

#### Office系
- Excel
- Word
- PowerPoint

これらは v0.1 では**外部アプリで開くのみ**とする。

### 9.7 各形式の仕様
#### 画像
- 画像表示

#### テキスト
- 内容表示

#### PDF
- 先頭ページまたは簡易ビュー表示

#### 音声
- 再生 / 一時停止
- シークバー
- 再生時間表示
- 簡易波形表示

#### 動画
- 簡易再生、またはサムネイル + 開く

### 9.8 操作ボタン
- 前回を開く
- 今回を開く
- Explorerで表示

---

## 10. 履歴パネル

### 10.1 表示方式
- 通常は非表示
- `履歴` ボタン押下で表示
- 再度押下または閉じる操作で非表示

### 10.2 表示形式
- 下から表示されるパネルを想定

### 10.3 表示内容
#### Snapshots
- 保存済みスナップショット一覧
- 日付
- 名前

#### Saved Compares
- 保存済み比較結果一覧
- 例：`初版→修正版`

### 10.4 操作
- Base に設定
- Compare に設定
- 結果を開く
- 閉じる

---

## 11. 初回設定ダイアログ

### 11.1 表示タイミング
- 初回起動時
- 新規プロジェクト作成時

### 11.2 入力項目
- プロジェクト名
- ルートフォルダ
- スナップショット保存先
- 除外ルール

### 11.3 ボタン
- 保存して開始
- キャンセル

---

## 12. 比較仕様

### 12.1 比較単位
- プロジェクト全体
- 単一サブフォルダ
- 複数サブフォルダ

### 12.2 比較対象情報
最低限、以下を比較対象とする。

- 相対パス
- ファイル名
- サイズ
- 更新日時

### 12.3 比較結果の分類
- 追加
- 削除
- 更新
- 同一

### 12.4 比較実行時の動作
`比較実行` 押下時に以下を行う。

1. Base と Compare を比較
2. 差分一覧を生成
3. 画面に反映
4. 比較ログを自動保存
5. 現時点のスナップショットを必要に応じて保存

### 12.5 日付比較
- 保存済みスナップショットを日付から選択可能とする
- Base / Compare へ設定できること

---

## 13. 保存仕様

### 13.1 保存対象
v0.1 では以下を保存する。

- プロジェクト設定
- スナップショット
- 比較ログ

### 13.2 プロジェクト設定保存項目
- プロジェクト名
- ルートフォルダ
- スナップショット保存先
- 除外ルール
- 前回使用した Base / Compare

### 13.3 スナップショット保存項目
- 相対パス
- ファイルサイズ
- 更新日時
- 保存日時

### 13.4 比較ログ保存項目
- 比較日時
- Base ID
- Compare ID
- 差分件数
- 差分一覧

---

## 14. 状態表示

### 14.1 空状態
- プロジェクト未設定
- 比較結果なし
- プレビュー対象未選択

### 14.2 処理中状態
- 比較中
- スナップショット保存中
- 履歴読み込み中

### 14.3 エラー状態
- フォルダ未存在
- 保存先エラー
- 読み込み不可ファイル
- プレビュー非対応形式

---

## 15. v0.1 に含める機能

### 15.1 必須
- プロジェクト保存 / 切替
- 初回設定ダイアログ
- フォルダツリー表示
- スコープ切替（全体 / 選択 / 複数）
- Base / Compare 比較
- サマリーカード
- 差分一覧
- 検索 / フィルタ
- 比較実行時の自動ログ保存
- 履歴パネル
- 画像プレビュー
- テキストプレビュー
- PDFプレビュー
- 音声プレビュー
- Office系の外部起動

### 15.2 可能なら含める
- 動画の簡易プレビュー

---

## 16. v0.1 に含めない機能

- 判定
- 重要度
- ラベル
- コメント運用
- 差し戻しステータス
- 自動修正
- 同期
- マージ
- 内容差分の高度解析
- ルールエンジン

---

## 17. 受け入れ条件

以下を満たした場合、v0.1 として成立とみなす。

1. プロジェクトを作成・保存・切替できる
2. プロジェクト全体 / サブフォルダ単位 / 複数フォルダ単位で比較できる
3. 追加 / 削除 / 更新 / 同一 を一覧表示できる
4. サマリーカード押下で一覧フィルタがかかる
5. 差分行選択で右ペインが更新される
6. 画像 / テキスト / PDF / 音声を前回 / 今回で表示できる
7. Office系ファイルを外部起動できる
8. 比較実行時に比較ログが保存される
9. 履歴ボタンからスナップショット / 保存済み比較結果を参照できる
10. 過去スナップショットを Base / Compare に再設定できる

---

## 18. 将来拡張候補（v0.2 以降）

- 動画プレビュー正式対応
- 高速比較の最適化
- ハッシュ比較
- ルールエンジン
- ラベル・メモ機能
- 比較レポートのHTML出力強化
- 波形表示改善
- Everything連携

---

## 19. 一文要約

**Re:Check は、前回と今回のフォルダ差分を、スコープ選択・履歴保存・左右プレビュー付きで確認するためのローカルGUIレビューUIである。**

---

## 実装デルタメモ（v0.1 実運用向け）

以下は v0.1 の範囲内で、実運用性向上のために明確化した実装メモ。

- スナップショット保存は軽量メタデータ中心（相対パス、サイズ、更新日時、保存日時）
- プレビュー用実ファイルは独立した `preview cache` で管理
- プレビューキャッシュは世代数と総サイズ上限で自動削除
- Base / Compare はスナップショット選択に加え、直接フォルダ選択から即時スナップショット化に対応
- 上部ヘッダーは 2 段構成（行1: タイトル＋主要操作、行2: Project/Base/Compare/保存系）
- 音声プレビューは再生・シーク・時間表示に加え簡易波形を表示
- PDF は安定優先で先頭ページ表示を基本とし、常に外部起動フォールバックを維持
- 言語設定（日本語 / English）をアプリ設定に追加
- 比較実行時、未保存の現状態がある場合は `保存して比較 / 保存せず比較 / キャンセル` の確認ダイアログを表示
- Preview ペインは 3 ペイン構成を維持したまま表示/非表示を切替可能
- Base/Compare の直接フォルダ選択はメインヘッダーから外し、必要時は Project メニューから外部フォルダをスナップショットとして取り込む

## v0.1 delta note (2026-03-11)
- New project creation now clears Base/Compare selections, diff results, and preview state.
- After project creation, a non-modal guidance message is shown: no snapshot has been saved yet.
- Compare execution now guides clearly when snapshots are insufficient (at least two distinct snapshots are required).
- Preview type classification uses original relative-path extension context, independent from cache-blob filenames.
- Preview pane collapse/expand is controlled from the preview pane header (pane-local interaction).
- Diff table timestamps are displayed as `YYYY-MM-DD HH:MM:SS` in main cells.
- Base/Compare labels are clarified as previous/current snapshot roles.

## v0.1 delta note (2026-03-11, polish-2)
- Header layout is refined into a compact title row and a clearer Base/Compare two-line selector block with directional cue.
- Diff list rows are denser for daily review, while keeping filename as a single-line primary column.
- Relative path column now displays parent folder path only; root-level files show `(root)` / `（ルート）`.
- App settings now include UI text size (`Small`, `Medium`, `Large`) with shortcut control.
- Compare execution now auto-saves CSV exports to `compare_exports` with timestamped filenames.
- Project menu includes quick access to open the compare CSV export folder.
- Lightweight shortcuts are standardized: `Ctrl+Enter`, `Ctrl+S`, `Ctrl+H`, `Ctrl+F`, `Esc`, `Ctrl+0`, `Ctrl+=`, `Ctrl+-`.
- Scope tree adds subtle added/modified folder cues without changing the 3-pane interaction model.

## v0.1 delta note (2026-03-11, polish-3)
- Scope tree now refreshes from current project root after snapshot save and after `Save and Compare`, in addition to project load/switch refresh.
- Diff table Base/Compare modified/size headers now use compact two-line labels for readability.
- Base/Compare directional hint placement is aligned to selector row relation instead of floating mid-block.
- Project selector width is slightly widened while keeping Base/Compare selectors visually dominant.
- Added simple in-pane video preview support (embedded when available) with clean external-open fallback when unavailable.
- Move/rename detection remains intentionally deferred; relocation-only changes are still treated as added/removed.

## v0.1 delta note (2026-03-11, polish-4)
- New project creation path now force-resets view state (Base/Compare selectors, diff results, preview, compare-log context) and then rebinds to the created project only.
- Post-create guidance message is clarified to explicitly prompt snapshot save before comparison.
- Diff table default column widths are rebalanced to prioritize `kind / filename / relative path` visibility ahead of timestamp/size metadata.
- Compare completion status now shows concrete CSV save location path, and project menu adds quick-open for the latest compare CSV.
