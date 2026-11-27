# 環境因子與心臟疾病死亡率之時空關聯分析——以臺灣本島為例（資料整理）

把衛福部死因統計、環境部 PM2.5 測站、ERA5-Land 氣溫與 MODIS NDVI 整理成**鄉鎮 × 年**的乾淨資料集，給下一棒做統計檢定、Moran's I、熱點分析與 GWR。本 repo 只做資料整理，不做迴歸或空間自相關。

| 項目 | 範圍 |
|---|---|
| 時間 | 民國 105–114 年（西元 2016–2025），年資料 |
| 空間單元 | 臺灣本島 **349** 個鄉鎮市區（排除澎湖、金門、連江全部，以及琉球鄉、綠島鄉、蘭嶼鄉） |
| 筆數 | 349 × 10 = **3,490** 列（long format，一列 = 一個鄉鎮 × 一年） |
| 合併鍵 | `towncode`：內政部 8 碼鄉鎮代碼，**字串** |
| 座標系 | TWD97 / TM2（EPSG:3826） |

---

## 我只想拿資料

所有交付檔都在 [`data/processed/`](data/processed/)：

| 檔案 | 內容 | 適合做 |
|---|---|---|
| [`panel_long.csv`](data/processed/panel_long.csv) | 3,490 列，鄉鎮 × 年，含旗標欄 | 時間趨勢、假設檢定、panel 迴歸 |
| [`town_mean_105_114.csv`](data/processed/town_mean_105_114.csv) | 349 列，各變數 10 年平均 | 橫斷面分析 |
| [`town_panel.gpkg`](data/processed/town_panel.gpkg) | 鄉鎮多邊形 + 10 年平均（EPSG:3826） | Moran's I、熱點分析、GWR（GeoDa／QGIS／geopandas／R sf） |
| [`town_panel_shp/`](data/processed/town_panel_shp/) | 同上的 Shapefile 版（欄名 ≤ 10 字元） | ArcGIS 熱點分析、GWR |
| [`data_dictionary.csv`](data/processed/data_dictionary.csv) | 欄名、中文說明、單位、來源、處理方式 | 查欄位 |

CSV 都是 UTF-8 with BOM，Excel 直接開不會亂碼。

**Python**
```python
import pandas as pd, geopandas as gpd
panel = pd.read_csv("data/processed/panel_long.csv", dtype={"towncode": str})
towns = gpd.read_file("data/processed/town_panel.gpkg", layer="town_panel")
towns = towns.merge(panel[panel.year == 2025], on="towncode", suffixes=("", "_2025"))  # 例：接上某一年
```

**R**
```r
library(sf); library(readr)
panel <- read_csv("data/processed/panel_long.csv", col_types = cols(towncode = col_character()))
towns <- st_read("data/processed/town_panel.gpkg", layer = "town_panel")
towns <- merge(towns, subset(panel, year == 2025), by = "towncode")  # 例：接上某一年
```

> ⚠️ `towncode` 一定要用字串讀，不要讓它變成數字。

---

## 欄位說明

| 欄位 | 說明 | 單位 | 出現在 |
|---|---|---|---|
| `towncode` | 鄉鎮市區代碼（內政部 8 碼，字串，保留前導 0） |  | panel_long; town_mean; gpkg/shp |
| `county` | 縣市名稱 |  | panel_long; town_mean; gpkg/shp |
| `town` | 鄉鎮市區名稱 |  | panel_long; town_mean; gpkg/shp |
| `year` | 西元年 | 年 | panel_long |
| `roc_year` | 民國年 | 年 | panel_long |
| `asmr_heart` | 心臟疾病（高血壓性疾病除外）年齡標準化死亡率，**主要分析變數**（= asmr_adj） | 每十萬人口 | panel_long; town_mean; gpkg/shp |
| `asmr_raw` | 原發布年齡標準化死亡率（未經 108 年準則轉換） | 每十萬人口 | panel_long; town_mean; gpkg/shp |
| `asmr_adj` | 經轉換比值調整後年齡標準化死亡率 | 每十萬人口 | panel_long |
| `cmr_heart` | 心臟疾病粗死亡率（自行計算） | 每十萬人口 | panel_long; town_mean; gpkg/shp |
| `deaths` | 心臟疾病死亡人數（原發布，未乘轉換比值） | 人 | panel_long; town_mean; gpkg/shp |
| `deaths_sum` | 心臟疾病 10 年死亡人數合計 | 人 | town_mean; gpkg/shp |
| `pop` | 年中人口 | 人 | panel_long; town_mean; gpkg/shp |
| `n_asmr` | 有 asmr_heart 值的年數 | 年 | town_mean; gpkg/shp |
| `pm25` | PM2.5 年平均濃度（IDW 內插，**主要**） | μg/m³ | panel_long; town_mean; gpkg/shp |
| `pm25_krig` | PM2.5 年平均濃度（Ordinary Kriging，比較用） | μg/m³ | panel_long; town_mean; gpkg/shp |
| `tmean` | 年平均氣溫 | °C | panel_long; town_mean; gpkg/shp |
| `ndvi` | 年平均 NDVI | 無單位（−1～1） | panel_long; town_mean; gpkg/shp |
| `f_asmr` | asmr_heart 旗標：0 正常、2 缺值（112 年起遮蔽「*」） | 代碼 | panel_long |
| `f_pm25` | pm25 旗標：0 正常、1 替代方法（all_touched／重心網格）、2 缺值 | 代碼 | panel_long |
| `f_tmean` | tmean 旗標：0 正常、1 替代方法（buffer／最近陸地網格）、2 缺值 | 代碼 | panel_long |
| `f_ndvi` | ndvi 旗標：0 正常、1 替代方法（good+marginal／buffer）、2 缺值 | 代碼 | panel_long |
| `n_flag1` | 10 年中 pm25、tmean、ndvi 旗標為 1 的筆數合計 | 筆 | town_mean; gpkg/shp |

`town_mean_105_114` 與 gpkg／shp 的數值欄是 10 年中**有值年份**的平均（`deaths` 為年平均、`deaths_sum` 為合計）。

---

## 資料來源與處理方式

逐步細節（每個排除、補值、決策與日期）見 [`docs/processing_log.md`](docs/processing_log.md)。

### 鄉鎮界
- 來源：內政部國土測繪中心「鄉(鎮、市、區)界線(TWD97經緯度)」114/03/18 版，[政府資料開放平臺 dataset 7441](https://data.gov.tw/dataset/7441)。
- 篩出本島 349 個，轉 EPSG:3826。
- 移除距臺灣本島 > 5 km 的島嶼部分（高雄市旗津區的東沙島與南沙太平島、宜蘭縣頭城鎮的龜山島與釣魚臺列嶼、基隆市中正區的彭佳嶼等、恆春鎮外礁），否則旗津區重心會落在南海。這些島沒有一般戶籍人口，不影響死亡資料。官方完整界線保留在 `data/interim/town_master.gpkg` 的 `town_master_official` 圖層。
- 死因表只有中文名稱，以 `data/interim/town_name_lookup.csv` 對應 towncode；106 年表仍用舊名「員林鎮」「頭份鎮」（104 年升格為市），以改名對照處理。

### 心臟疾病死亡率（`asmr_heart`, `deaths`, `pop`, `cmr_heart`）
- 來源：衛生福利部統計處[死因統計](https://dep.mohw.gov.tw/DOS/lp-5069-113.html)「縣市及鄉鎮統計表」105–114 年，各鄉鎮「主要死亡原因」工作表的「心臟疾病（高血壓性疾病除外）」列（ICD-10：I01-I02.0, I05-I09, I20-I25, I27, I30-I52）。
- 鄉鎮表**直接提供標準化死亡率**；年中人口取自工作表附註。
- **核對**：368 鄉鎮死亡數加總與衛福部公布的全國值（105、108–114 年）完全一致。
- **108 年死因選取準則轉換**：108 年起改採 WHO 2016 年版 ICD-10 選取準則。衛福部只提供全國轉換比值，心臟疾病標準化死亡率為 **0.9162**（108–114 年死因統計結果分析附表 1）。`asmr_adj` = 105–107 年 × 0.9162，108–114 年不變；`asmr_heart` = `asmr_adj`。`deaths` 維持原發布整數。
- `cmr_heart` = `deaths` / `pop` × 10⁵，所有年份自行計算。

### PM2.5（`pm25`, `pm25_krig`）
- 來源：環境部環境資料開放平臺 [空氣品質監測日平均值 AQX_P_19](https://data.moenv.gov.tw/dataset/detail/AQX_P_19)、[測站基本資料 AQX_P_07](https://data.moenv.gov.tw/dataset/detail/AQX_P_07)。萬里站（114/5/1 停止監測）不在現行測站資料中，座標依使用者提供（新北市萬里區瑪鋉路 221 號）。
- 測站年均：無效值 `x` 不計；一年有效日 ≥ 75% 才參與內插；排除離島測站（馬祖、金門、馬公）。每年 73–75 站。
- 內插：1 km 網格（EPSG:3826），**IDW（power = 2）為主**，Ordinary Kriging（spherical variogram）為比較。
- 鄉鎮值：網格中心落在鄉鎮內的平均（rasterstats zonal mean），349 鄉鎮全部取得值。
- **LOOCV RMSE**（μg/m³）：IDW 2.25–3.80，Kriging 1.59–2.90，**Kriging 每年都較低**。依專案規劃仍以 IDW 為主，`pm25_krig` 可做敏感度分析。兩者鄉鎮值相關 0.953。

### 年平均氣溫（`tmean`）
- 來源：ERA5-Land monthly（GEE `ECMWF/ERA5_LAND/MONTHLY_AGGR`，`temperature_2m`），每年 12 個月平均，K → °C；鄉鎮多邊形平均（scale 1 km）。
- ERA5-Land 只有陸地資料，被判為海洋的網格是空值。9 個沿海鄉鎮（高雄市鹽埕、新興、前金、苓雅、前鎮、旗津、林園，宜蘭縣羅東鎮，新竹縣新豐鄉）的多邊形與重心 1 km buffer 都取不到值，改以周圍 20 km 內陸地網格平均補上（`f_tmean` = 1），與相鄰鄉鎮差 0.04–0.30 °C。
- GEE 腳本：[`gee/export_tmean_ndvi.js`](gee/export_tmean_ndvi.js)。

### 年平均 NDVI（`ndvi`）
- 來源：MODIS MOD13Q1 v061（GEE `MODIS/061/MOD13Q1`，`NDVI` × 0.0001），16 天合成。
- 依 `SummaryQA` 只保留 good 像元，逐像元年平均，再取鄉鎮多邊形平均（scale 250 m）。整年沒有 good 像元的鄉鎮放寬為 good + marginal（`f_ndvi` = 1，59 筆，集中在都市區）。

---

## 缺值說明

**總原則：保留 NaN，沒有填 0、填平均或時間內插。** 要不要補、怎麼補，由分析者決定。

| 旗標值 | 意思 |
|---|---|
| `0` | 正常取得 |
| `1` | 用替代方法取得（方法見欄位說明與 processing_log） |
| `2` | 缺值（NaN） |

死亡數為 0 是真實值，`asmr_heart` = 0、旗標 0（只有 112 年高雄市茂林區 1 筆）。

以下表格來自 [`docs/missing_summary.csv`](docs/missing_summary.csv)（每年 349 個鄉鎮）：

**缺值 NaN**
| 變數 | 105 | 106 | 107 | 108 | 109 | 110 | 111 | 112 | 113 | 114 |
|---|---|---|---|---|---|---|---|---|---|---|
| `asmr_heart` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 78 | 77 | 74 |
| `pm25` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `tmean` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ndvi` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**旗標 1（替代方法）**
| 變數 | 105 | 106 | 107 | 108 | 109 | 110 | 111 | 112 | 113 | 114 |
|---|---|---|---|---|---|---|---|---|---|---|
| `asmr_heart` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `pm25` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `tmean` | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 |
| `ndvi` | 7 | 7 | 5 | 5 | 6 | 6 | 5 | 5 | 6 | 7 |

`asmr_heart` 的 229 個缺值：衛福部從 112 年起，死亡人數未滿 20 人的鄉鎮不公布死亡率（以「*」呈現），死亡人數仍有公布。逐筆清單見 [`docs/mortality_masked.csv`](docs/mortality_masked.csv)。

---

## ⚠️ 限制與注意事項

1. **108 年死因選取準則改變**：105–107 年已乘全國轉換比值 0.9162，但同一個全國值套用到所有鄉鎮，等於假設各地受準則改變的影響相同。可用 `asmr_raw` 搭配年份虛擬變數做敏感度分析。
2. **112–114 年缺值不是隨機的**：被遮蔽的全是死亡數少的小鄉鎮（多為山區、原住民鄉鎮，ASMR 通常偏高），直接算這三年的平均會偏低。`town_mean` 中有 97 個鄉鎮的 ASMR 平均只用 7–9 年（看 `n_asmr`）。建議用 `cmr_heart`（10 年都有值）或 `deaths`、`pop` 自行建模做對照。
3. **小鄉鎮死亡率不穩定**：deaths < 20 有 796 筆、< 5 有 70 筆，都照原值保留。例：臺東縣延平鄉 111 年 15 人死亡，ASMR 285.5。可考慮以 `deaths` 為結果變數、`pop` 為 offset 的 Poisson／負二項模型，或 Empirical Bayes 平滑。
4. **PM2.5 是內插值，不是實測**：測站集中在平地與都市，中央山脈與東部山區幾乎沒有測站，那裡是外插結果，誤差可能大於 LOOCV RMSE。Kriging 的 LOOCV 比 IDW 好，可用 `pm25_krig` 做敏感度分析。
5. **ERA5-Land 解析度約 9–11 km**：小鄉鎮常與鄰近鄉鎮落在同一格，鄉鎮間氣溫差異被平滑；9 個沿海鄉鎮是補值。
6. **瑪家鄉三和村飛地**：三和村居民的死亡數算在瑪家鄉，但其地理範圍（約 5.3 km²）在界線檔中屬長治、內埔、鹽埔，環境變數算在那三鄉。
7. **生態謬誤**：這是鄉鎮層級的聚合資料，鄉鎮間的關聯不等於個人層級的因果關係（Robinson, 1950）。

---

## 資料夾結構

```
data/raw/          原始下載檔（死因 xls/ods/pdf、PM2.5 日資料、鄉鎮界、GEE 匯出 CSV）
data/interim/      中間產物（鄉鎮主表、各變數整理後 csv、PM2.5 測站年均／variogram／LOOCV）
data/processed/    最終交付
docs/              processing_log.md、missing_summary.csv、mortality_masked.csv
figures/qa/        檢查用地圖與圖表
gee/               GEE JavaScript 腳本
src/               Python 處理腳本（依編號執行）
```

`data/raw/` 是下載當時（2026-11-27～28）的原始檔，全部收錄在 repo 中，不需重新下載就能重跑。

---

## 如何重跑

```bash
conda env create -f environment.yml
conda activate heart-env-taiwan
bash src/run_all.sh          # 依序執行 01 → 05
```

| 腳本 | 做什麼 |
|---|---|
| `src/00_download_raw.py` | （選用）重新下載死因統計與鄉鎮界 |
| `src/00_download_pm25.py` | （選用）重新下載 PM2.5，需環境變數 `MOENV_API_KEY`（[環境資料開放平臺](https://data.moenv.gov.tw/)免費申請） |
| `src/01_town_master.py` | 鄉鎮主表 349 個 + 中文名稱對照 |
| `src/02_mortality.py` | 心臟疾病死亡率 |
| `src/03_pm25.py` | PM2.5 測站年均 → IDW／Kriging → 鄉鎮 |
| `src/04_gee_prep.py` | 產生上傳 GEE 用的鄉鎮界 shapefile zip |
| `gee/export_tmean_ndvi.js` | 在 [GEE Code Editor](https://code.earthengine.google.com) 手動執行，匯出 CSV 放到 `data/raw/gee/` |
| `src/04_gee_clean.py` | 氣溫、NDVI 檢查與旗標 |
| `src/05_merge.py` | 合併、交付檔、QA 圖、缺值摘要 |

---

## 參考資料

Ahmad, O. B., Boschi-Pinto, C., Lopez, A. D., Murray, C. J. L., Lozano, R., & Inoue, M. (2001). *Age standardization of rates: A new WHO standard* (GPE Discussion Paper Series No. 31). World Health Organization.

Didan, K. (2021). *MODIS/Terra vegetation indices 16-day L3 global 250m SIN grid V061* [Data set]. NASA EOSDIS Land Processes Distributed Active Archive Center. https://doi.org/10.5067/MODIS/MOD13Q1.061

Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., & Moore, R. (2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. *Remote Sensing of Environment, 202*, 18–27. https://doi.org/10.1016/j.rse.2017.06.031

Muñoz Sabater, J. (2019). *ERA5-Land monthly averaged data from 1950 to present* [Data set]. Copernicus Climate Change Service (C3S) Climate Data Store. https://doi.org/10.24381/cds.68d2bb30

Robinson, W. S. (1950). Ecological correlations and the behavior of individuals. *American Sociological Review, 15*(3), 351–357. https://doi.org/10.2307/2087176

內政部國土測繪中心（2025）。*鄉(鎮、市、區)界線(TWD97經緯度)*［資料集］。政府資料開放平臺。https://data.gov.tw/dataset/7441

環境部（2026）。*空氣品質監測日平均值（一般污染物）*（AQX_P_19）［資料集］。環境資料開放平臺。https://data.moenv.gov.tw/dataset/detail/AQX_P_19

環境部（2026）。*空氣品質監測站基本資料*（AQX_P_07）［資料集］。環境資料開放平臺。https://data.moenv.gov.tw/dataset/detail/AQX_P_07

衛生福利部統計處（2017–2026）。*105–114年死因統計：縣市及鄉鎮統計表、死因統計年報、死因統計結果分析*［資料集］。https://dep.mohw.gov.tw/DOS/lp-5069-113.html

資料授權：政府資料依[政府資料開放授權條款－第1版](https://data.gov.tw/license)使用；ERA5-Land 依 Copernicus License；MODIS 為 NASA 公開資料。
