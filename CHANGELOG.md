# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-09-19

第一個以桌面為唯一產品面的展示版本。倉名對齊 **veo-local-studio**。

### Added

- 根目錄繁中 README（Hero、徽章、繁中／英文切換、示範實拍）與 `docs/README.en.md`。
- `docs/discord.md`、`docs/packaging.md`、`CONTRIBUTING.md`、MIT `LICENSE`。
- `app/paths.py`：可用 `VEO_STUDIO_DATA`／`VEO_STUDIO_OUTPUTS` 指到拋棄式目錄（說明擷圖用）。
- `scripts/capture_docs.py`：不讀真實金鑰的視窗擷圖。

### Changed

- 視窗標題與捷徑名稱改為 Veo Local Studio。
- Discord 完成文案改為中性的預估費用，不再寫個人錢包。
- 桌面頂列改兩行，左右欄固定寬度，避免歷史欄被按鈕擠掉。
- 教學與說明改以 `/veo3` 為準。
- Inno Setup 與 PyInstaller 改帶 `assets/`，不再複製瀏覽器靜態頁。
- `requirements.txt` 只留桌面與 Bot 真正用到的套件，並鎖定 `tkinterdnd2==0.4.3`。

### Removed

- 瀏覽器介面（`static/*.html`、`app.js`、`styles.css`）與 FastAPI 入口 `app/main.py`。
- Docker 網頁進口（`Dockerfile`、`docker-compose.yml`、`scripts/run_docker.bat`）。
- 內部重建提示詞 `AI_REBUILD_PROMPT_ANALYSIS.txt` 與已追蹤的 `.lnk`。

### Fixed

- `_load_logo_assets` 在早退之後無法載入 logo 的死碼。
- `.gitignore` 補上 `.env`、`*.lnk`、`installer/output/`。

### Security

- 設定與用量仍只寫本機 `data/`；公開說明改為明確寫「不要對公網暴露」。

[Unreleased]: https://github.com/Lrniey666/veo-local-studio/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Lrniey666/veo-local-studio/releases/tag/v1.0.0
