# 打包

給要做成安裝程式的維護者。一般使用請跑 `scripts\run_local.bat`。

## EXE

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

會安裝 PyInstaller，並把 `assets/` 打進 `dist\VeoLocalStudio.exe`。

## Inno Setup

1. 先完成上一節，確認 `dist\VeoLocalStudio.exe` 存在。
2. 用 Inno Setup 開啟 `installer/VeoLocalStudio.iss` 並 Build。
3. 安裝檔寫到 `installer/output/`（已 gitignore）。

## 開發用捷徑

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
```

捷徑建在桌面，指向 `scripts\run_local.bat`。`*.lnk` 不會進版控。

## 說明用擷圖

`scripts\capture_docs.py` 會用一次性資料目錄啟動桌面（不讀你的真實金鑰），把主畫面、設定與用量寫進 `docs/assets/`。需要 Pillow（不在執行期依賴裡）。
