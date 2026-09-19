# Discord `/veo3`

語言：[繁體中文](discord.md) · 產品總覽見 [README](../README.md)

Bot 是桌面程式的選用入口，不是第二套產品。啟用後與桌面共用 `veo_client`、SQLite 與用量紀錄。

## 流程

1. 在頻道輸入 `/veo3`。
2. 選單調整片長、比例、畫質、生成類型。不合法組合會被自動修正並提示。
3. Bot 在頻道請你直接打提示詞；需要素材的類型一併附加檔案。
4. 確認卡片核對後按下開始生成。
5. 成功則上傳影片並寫入花費；失敗顯示 API 原文與重試。

Discord Modal 不能上傳檔案，所以素材走「頻道訊息 + `wait_for`」，不是 slash 參數。

## 開發者後台

- Privileged Gateway Intent：**Message Content Intent** 必須打開，否則讀不到提示詞。
- 邀請權限：Send Messages、Attach Files、Read Message History、Use Slash Commands。
- Bot 畫質選項到 2K 為止，不提供 4K，以免超過上傳上限。

## 指令同步

設定頁的「指令同步伺服器 ID」可填多個，逗號分隔。

| 填法 | 行為 |
| --- | --- |
| 有 guild ID | 同步到那些伺服器（通常立即可見），並清掉全域指令以免重複 |
| 留空 | 全域同步，Discord 傳播最多約 1 小時 |

切換策略後若看到兩個 `/veo3`，重啟一次並確認只走其中一種。

## 安全

Token 等同密碼。不要把 `data/app_config.json` 提交或傳給別人。懷疑外洩就到 Developer Portal Reset Token。
