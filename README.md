# Veo 3.1 Local Studio

本專案提供可在本機執行的 Veo 3.1 視窗應用程式（Desktop App）：

- 多對話管理（聊天式側欄）
- 圖片 + 文字輸入
- 可拖放圖片/素材到命令頁
- 影片輸出選項（時間、畫面比例、畫質）
- 歷史命令紀錄與「載入修改再生成」
- 影片固定輸出到 `outputs/videos`
- UI 內保存 API 設定
- Theme Switching（暗色 Discord 風、明色 Apple 風）
- Discord Bot 指令觸發生成
- 設定頁面（模型 / API / Discord Token / 成本模型）
- 備用 AI API 設定（主 API 失敗時自動切換）
- 用量與花費頁面（API 使用量統計 + 預估成本）
- 主頁使用教學頁與一鍵重啟按鈕
- Docker 部署
- Windows EXE 打包與桌面捷徑腳本

## 1) 本機快速啟動（Python）

```bat
scripts\run_local.bat
```

啟動後會直接開啟桌面視窗，不需瀏覽器。

## 2) Docker（僅後端服務模式）

```bat
scripts\run_docker.bat
```

說明：Docker 主要用於後端服務流程，桌面視窗 UI 請使用本機 Python 啟動。

## 3) API 設定

在桌面視窗的設定區填入：

- API Base URL（系統會呼叫 `POST {API_BASE}/generate`）
- API Key（Bearer Token）
- 模型名稱（預設 `veo-3.1`）
- 最大圖片輸入數量

### API 回應格式（支援其一）

- `video_base64` + `mime_type`
- `video_url`

## 4) Discord Bot

1. 在桌面視窗勾選「啟用 Discord Bot」並輸入 Bot Token，儲存
2. 重啟服務
3. 在 Discord 使用 `/veo` 指令
4. 若需要完整新手流程，請在桌面程式上方按「Discord 教學」

## 5) 輸出資料夾

- `outputs/inputs`：每次請求上傳圖片副本
- `outputs/videos`：生成影片檔案（固定）
- `data/veo_app.db`：歷史與對話資料庫
- `data/app_config.json`：本機設定（含 API key）

## 6) EXE 安裝與捷徑

### 先打包 EXE

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

### 建立 Inno Setup 安裝檔

1. 安裝 Inno Setup
2. 開啟 `installer/VeoLocalStudio.iss`
3. 按 Build 產生安裝程式 `.exe`

### 建立桌面捷徑（開發模式）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
```

## 7) 縮圖替換

目前專案統一使用 `static/assets/oeu4f-vstm7-001.ico` 作為視窗與縮圖圖標來源。
