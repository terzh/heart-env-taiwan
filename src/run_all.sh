#!/usr/bin/env bash
# 從頭到尾重跑 01–05（從 repo 根目錄執行：bash src/run_all.sh）
#
# 前置條件：
#   1. conda env create -f environment.yml && conda activate heart-env-taiwan
#   2. data/raw/ 已有原始資料（可用 src/00_download_raw.py、src/00_download_pm25.py 下載；
#      後者需要 MOENV_API_KEY 環境變數）
#   3. data/raw/gee/ 已有 GEE 匯出的 CSV（gee/export_tmean_ndvi.js，需在 GEE Code Editor 手動執行）
set -euo pipefail
cd "$(dirname "$0")/.."

run() { echo; echo "===== $1 ====="; python "$1"; }

run src/01_town_master.py   # 鄉鎮主表 349 + 中文名稱對照
run src/02_mortality.py     # 心臟疾病死亡率
run src/03_pm25.py          # PM2.5 測站 → IDW / Kriging → 鄉鎮
run src/04_gee_prep.py      # GEE 上傳用 shapefile（若鄉鎮界改變才需重新上傳並重跑 GEE）

if compgen -G "data/raw/gee/*.csv" > /dev/null; then
  run src/04_gee_clean.py   # 氣溫、NDVI
else
  echo "!! data/raw/gee/ 沒有 CSV：請先在 GEE 執行 gee/export_tmean_ndvi.js 並下載匯出檔" >&2
  exit 1
fi

run src/05_merge.py         # 合併 + 交付檔 + QA 圖
echo; echo "完成。交付檔在 data/processed/，QA 圖在 figures/qa/"
