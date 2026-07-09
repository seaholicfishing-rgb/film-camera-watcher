# 中古フィルムカメラ 新着検知 → Chatwork通知

全国の中古フィルムカメラ店の「新着商品」を検知し、Chatworkへ自動通知するアプリ。
GitHub Actions（無料・クラウド常時稼働）で動くので、自分のPCの電源とは無関係に動きます。

## 何をするか
- 対象店の在庫を **毎時00分・JST 10:00〜22:00（1日13回）** チェック
- フィルム関連のみ・価格足切りのフィルタを通す
- **前回から増えた新着（差分）だけ**をまとめて1通、Chatworkへ通知
- 通知済み商品は `state.json` に記録 → **重複通知ゼロ・取りこぼしゼロ**
- 初回はサイレント記録（既存在庫を一気に通知しない）

## 現在の通知ルール（`config.json` で変更可）
- フィルムカメラ本体：**3万円超**のみ（デジタル本体は除外）
- レンズ：**MF・中判大判のみ／3万円超**（AFレンズ・デジタル専用マウントは除外）
- アクセサリー：**2万円以上**のみ
- カテゴリ判別不能な商品：取りこぼし防止で「⚠️要確認」付きで通知

---

## セットアップ手順（PCにgit不要・ぜんぶWeb画面でOK）

### 0. 【重要】Chatworkトークンを再発行する
過去にチャットへ貼ったトークンは漏洩前提で無効化します。
Chatwork → 右上アイコン → サービス連携 → API Token → **再発行**。
表示された **新しいトークン文字列**をコピー（手順4で使う）。

### 1. GitHubアカウントを作る（無料）
https://github.com/signup

### 2. 新しいリポジトリを作る
- 右上「＋」→ New repository
- 名前：例 `film-camera-watcher`
- **Private（非公開）** を選択 → Create repository

### 3. ファイルをアップロード
このフォルダ内の次のファイルをアップロードします（`state.json` は不要・自動生成）：
- `watcher.py`
- `config.json`
- `README.md`
- `.gitignore`
- `.github/workflows/watch.yml` ← フォルダ階層に注意

> Web画面でのコツ：「Add file → Create new file」で、ファイル名の欄に
> `.github/workflows/watch.yml` と入力すると階層フォルダごと作れます。
> 中身は手元の `watch.yml` をコピペ。残りのファイルは「Add file → Upload files」でドラッグ＆ドロップでOK。

### 4. トークンを安全に登録（Secrets）
- リポジトリの Settings → Secrets and variables → Actions → **New repository secret**
- Name：`CHATWORK_TOKEN`
- Secret：手順0でコピーした**新しいトークン**を貼り付け → Add secret

> これでトークンはGitHubの金庫に入り、コードにもチャットにも露出しません。

### 5. 動かす（初回サイレント記録）
- 上部 **Actions** タブ → 初回は「I understand my workflows, enable them」をクリックして有効化
- 左の **film-camera-watcher** → **Run workflow**（手動実行）
- これで現在の在庫を記録します（**初回は通知なし**＝正常）

### 6. 完了
以降は**毎時00分・10〜22時に自動実行**。新着が出ると専用ルームに通知が届きます。

---

## 設定の変え方（`config.json` を編集するだけ）
GitHub上で `config.json` を開く → 鉛筆アイコンで編集 → Commit。

- **価格の足切り**：各 `min_price` の数字
- **稼働時間**：`active_hours` の `start` / `end`（JST）
- **通知先ルーム**：`chatwork.room_id`
- **対象店の追加**：`shops` 配列に追記（Shopify店なら `type:"shopify"` と `url` を足すだけ）

### 時間帯を変えたら cron も合わせる
`active_hours` を変えたら `.github/workflows/watch.yml` の cron も直してください。
cronは **UTC** です（JST−9時間）。例：JST10〜22時 → UTC1〜13時 → `0 1-13 * * *`。

---

## 注意点（正直なところ）
- **実行時刻は数分ズレることがあります**（GitHubの仕様で混雑時は遅延）。新着検知には実害なし。厳密な「00分ちょうど」が必須なら有料cronサービス等へ移行可能。
- **60日間リポジトリを操作しないと、スケジュールが自動停止**することがあります（GitHubの仕様）。たまに何か編集すれば回避できます。
- 無料のActions実行枠（Private리포で月2000分）内に収まります（本アプリは月約400分）。

## 今後の拡張メモ
- 次の追加候補：三宝カメラ・富士越カメラ（カラーミー系＝別アダプタが必要）、フジヤカメラ、カメラコレクション 等
- マップカメラはbot対策が強く、別途工夫が必要
