# CLAUDE.md — 專案規格（Claude Code 每次開啟都會讀這份）

## 專案
數據分析期末報告：**環境因子與心臟疾病死亡率之時空關聯分析——以臺灣本島為例**
本 repo 的任務只有一件事：把四份原始資料整理成「下一棒同學（統計／空間分析）拿了就能用」的乾淨資料集。
不做迴歸、不做 Moran's I——那是下一棒的工作。

## 資料規格（不可更動）
- 時間：民國 105–114 年（西元 2016–2025），年資料
- 空間單元：鄉鎮市區，**臺灣本島 349 個**
  - 排除：澎湖縣、金門縣、連江縣全部，以及屏東縣琉球鄉、臺東縣綠島鄉、臺東縣蘭嶼鄉
  - 若篩完不是 349，停下來列出差異給我看，不要自己猜
- 目標筆數：349 × 10 = 3,490 列（long format，一列 = 一個鄉鎮 × 一年）
- 合併鍵：`towncode`（內政部 8 碼鄉鎮代碼，字串型態，保留前導 0）。**不要用中文名稱 join**（臺/台、異體字會出錯）
- 座標系：空間運算一律用 TWD97 / TM2 (EPSG:3826)；輸出的 GeoPackage 用 EPSG:3826

## 四個變數
| 欄位 | 內容 | 來源 | 處理方式 |
|---|---|---|---|
| `asmr_heart` | 心臟疾病（高血壓性疾病除外）年齡標準化死亡率，每十萬人 | 衛福部統計處死因統計「縣市及鄉鎮統計表」 | 見下方「死亡率注意事項」 |
| `pm25` | PM2.5 年平均濃度 μg/m³ | 環境部空氣品質監測站歷史資料 | 測站年均 → IDW（主）／Ordinary Kriging（比較用）內插 1 km 網格 → 鄉鎮 zonal mean |
| `tmean` | 年平均氣溫 °C | ERA5-Land monthly（GEE: `ECMWF/ERA5_LAND/MONTHLY_AGGR`, `temperature_2m`, K→°C） | GEE reduceRegions 到鄉鎮，月→年平均 |
| `ndvi` | 年平均 NDVI | MODIS（GEE: `MODIS/061/MOD13Q1`, band `NDVI` × 0.0001） | GEE reduceRegions 到鄉鎮，年平均；用 `SummaryQA` 去雲 |

## 死亡率注意事項（重要）
1. **108 年起死因選取準則改為 WHO 2016 版 ICD-10**。105–107 年原發布值與 108 年後不可直接比較。
   衛福部有提供「轉換比值」（例：全國 105 年心臟疾病死亡人數原發布 20,812 人，轉換後 18,948 人）。
   - 先找原始檔或年報裡有沒有轉換比值；有的話新增 `asmr_adj` 欄位，並保留原始值 `asmr_raw`
   - 找不到就新增 `rule_chg` 虛擬變數（105–107 = 0，108–114 = 1），並在 README 寫明
2. 先確認鄉鎮層級的表格是否**直接提供標準化死亡率**。如果只有死亡人數／粗死亡率：
   - 回報給我，不要自己決定
   - 備案 A：若有鄉鎮 × 年齡層死亡數，用 WHO 2000 世界標準人口 + 內政部鄉鎮年齡別人口自己算 ASMR
   - 備案 B：退而使用粗死亡率 `cmr_heart`，在 README 標明限制
3. 一併保留 `deaths`（死亡人數）與 `pop`（年中人口），小鄉鎮死亡數很少時比率不穩，下一棒可能要用。

## 缺值處理規則
**總原則：最終檔案保留 NaN，絕不填 0、不填平均、不做時間內插。** 下一棒要不要補值、怎麼補，由他們決定。
每個變數另加一個旗標欄：`f_asmr`, `f_pm25`, `f_tmean`, `f_ndvi`，代碼為：
`0` = 正常取得，`1` = 用替代方法取得（見下表），`2` = 缺值（NaN）

| 變數 | 情況 | 處理方式 | 旗標 |
|---|---|---|---|
| 死亡率 | 某鄉鎮某年**死亡數為 0** | `asmr_heart = 0` 是真實值，**不是缺值**，保留 0 | 0 |
| 死亡率 | 原始表沒有該鄉鎮／被遮蔽（如「-」「…」「*」） | NaN；把原始符號記在 processing_log | 2 |
| 死亡率 | 死亡數很少（< 5） | 照原值保留，不改；README 提醒比率不穩，下一棒可用 `deaths`、`pop` 自行處理 | 0 |
| PM2.5 | 測站某年有效日 < 75% | 該測站-年不參與內插（測站層級剔除，不影響鄉鎮筆數） | — |
| PM2.5 | 鄉鎮 zonal mean 為 NaN（太小、沒有網格中心落在裡面） | 先改 `all_touched=True`；仍 NaN 就取鄉鎮重心所在網格值 | 1 |
| 氣溫／NDVI | GEE reduceRegions 回傳空值（鄉鎮太小） | 改用鄉鎮重心 1 km buffer 重算 | 1 |
| NDVI | 整年有效像元不足（雲遮蔽） | 先放寬為 good + marginal；仍為空 → NaN | 2 |
| 任何變數 | 整年缺資料（例如某年原始檔不存在） | 停下來回報，不要用相鄰年份代替 | — |

`05_merge.py` 結束時要輸出 `docs/missing_summary.csv`（變數 × 年份的缺值數與旗標 1 的筆數），並放進 README。

## 輸出（data/processed/）
- `panel_long.csv`：3,490 列，UTF-8 with BOM（Excel 開才不會亂碼）
- `town_mean_105_114.csv`：349 列，各變數 10 年平均（給 Moran's I、熱點分析、GWR 用的橫斷面）
- `town_panel.gpkg`：鄉鎮多邊形 + 10 年平均值，EPSG:3826（GeoDa／QGIS／ArcGIS／geopandas 都能開）
- `town_panel_shp/`：同上的 Shapefile 版（給 ArcGIS 熱點分析／GWR 用；欄名 ≤ 10 字元、全英文）
- `data_dictionary.csv`：欄名、中文說明、單位、來源、處理方式

## 欄名（全英文小寫、≤ 10 字元，Shapefile 才不會被截斷）
`towncode, county, town, year, roc_year, asmr_heart, deaths, pop, pm25, tmean, ndvi, f_asmr, f_pm25, f_tmean, f_ndvi`（必要時加 `asmr_raw`, `asmr_adj`, `rule_chg`, `pm25_krig`）

## GitHub
- 帳號：`terzh`（repo 建在這個帳號底下；不確定就以 `gh auth status` 顯示的帳號為準，先問我確認）
- Repo 名稱：`heart-env-taiwan`，private
- 推之前先跑 `gh auth status` 確認登入的是上面這個帳號；不是的話停下來告訴我

## 資料夾結構
```
data/raw/          # 原始下載檔，進 git（2026-11-28 改：整個 data/ 都推上 GitHub）
data/interim/      # 中間產物（各變數各自整理好的 csv），進 git
data/processed/    # 最終交付，要進 git
gee/               # GEE JavaScript 腳本
src/               # Python 處理腳本，依序編號 01_ 02_ ...
figures/qa/        # 檢查用地圖與圖表
README.md
```

## 環境
- Linux + conda。建立 `environment.yml`（python 3.11, pandas, geopandas, rasterio, rasterstats, shapely, pyproj, scipy, pykrige, matplotlib, openpyxl）
- 每支腳本都要能從 repo 根目錄 `python src/0X_xxx.py` 重跑，路徑用相對路徑

## 工作原則
- 每個階段完成後停下來，給我：做了什麼、產出檔案、筆數、缺值、發現的問題。等我說 OK 才進下一階段
- 遇到原始資料和規格不符（欄位不存在、鄉鎮數不對、年份缺）就回報，**不要自己補值或編造**
- 任何內插、補值、排除都要記錄在 `docs/processing_log.md`
