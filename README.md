# aff-hub

**全SNS bio から飛ばす集約アフィリンクハブ**

linktree/lit.link 代替の自前GitHub Pages。完全コントロール・無料・SEO可・親不要。

## 構成

```
GitHub Pages (静的)
├── index.html          ... bio link 一発目（profile + 厳選10商品 + SNS列）
├── daily/{date}.html   ... 毎日更新の推し商品ページ
└── feed.json           ... 各SNS bot がここを読んで「今日のリンク」自動取得
```

## なぜこれが重要

| SNS | bio に貼れるリンク数 | 今やってる事 | aff-hub導入後 |
|---|---|---|---|
| Threads | 1 | linktree |  aff-hub |
| Pinterest | 1 | （未設定） | aff-hub |
| Bluesky | 1 | （未設定） | aff-hub |
| Misskey | 1 | （未設定） | aff-hub |
| Telegram | 1 | （未設定） | aff-hub |
| YouTube概要欄 | 無制限 | 個別貼り | aff-hub経由 |
| はてなブログサイドバー | 1 | （未設定） | aff-hub |

**全SNSのbioを1つに統一**。商品入れ替えはaff-hub側で更新するだけで全SNS反映。

## パイプライン

```
~/MONETIZATION_IDS.json (楽天/もしも/Amazon/忍者)
   +
~/Desktop/pin-money/data/products/{date}.json (今日の売れ筋)
   ↓ src/build_hub.py (claude -p で紹介文整形)
public/index.html, public/daily/{date}.html, public/feed.json
   ↓ git push (GitHub Pages自動デプロイ)
https://<github_id>.github.io/aff-hub/
```

## 必要なもの
- GitHub アカウント (既存 nayo126 でOK)
- GitHub Pagesリポジトリ作成権限
- pin-moneyが先に稼働してること（商品データを借りる）

## 自動運転
launchd 毎日 06:00 JST で `build_hub.py` → `git push` 自動化。
