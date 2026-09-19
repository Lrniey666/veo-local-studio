# 貢獻指南

語言：[繁體中文](CONTRIBUTING.md) · [English](docs/CONTRIBUTING.en.md)

這是本機 Windows 桌面的 Veo 工作室。歡迎修 bug、補文件、改桌面操作；請先對齊現況再動手。

## 動工前

1. 讀根目錄 [`README.md`](README.md) 的架構表。
2. 桌面行為以 `app/desktop.py` 與 `app/services/` 為準，不要從已刪除的瀏覽器頁推回去。
3. Discord 流程以 `app/services/discord_bot.py` 與 [`docs/discord.md`](docs/discord.md) 為準。指令名稱是 `/veo3`。

衝突時以程式碼為準，然後回頭改正文件。

## 慣例

| 項目 | 約定 |
| --- | --- |
| 使用者看得見的字串 | 繁體中文 |
| 對外 README | 繁中在根目錄；英文在 `docs/README.en.md` |
| 變數／函式 | `snake_case` |
| 類別 | `PascalCase` |
| 日期 | `YYYY-MM-DD`，台北時間 |

## 請不要

- 把金鑰、Token、絕對機器路徑寫進程式或文件
- 提交 `data/`、`outputs/`、`.env`、`*.lnk`
- 把瀏覽器介面或 Docker 網頁入口加回來，除非先改架構說明
- 把 Discord 成功訊息寫成個人錢包調侃
- 默默吞掉 Google API 的原始錯誤

不可逆的動作（push、Reset Token、會花錢的真實生成）請先問。

## 改完必做

1. 行為有變 → 同步 README 與對應的 `docs/` 分冊
2. 把 notable 變更寫進 `CHANGELOG.md` 的 `## [Unreleased]`（Added／Changed／Deprecated／Removed／Fixed／Security）
3. 動到桌面版面時，用 `scripts\capture_docs.py` 重擷示範圖（腳本使用拋棄式資料目錄，不會讀你的真實設定）

對外說明寫在 [`README.md`](README.md)；打包寫在 [`docs/packaging.md`](docs/packaging.md)。
