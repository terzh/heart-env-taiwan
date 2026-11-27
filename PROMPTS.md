# Claude Code 資料整理 Prompt 指南

> 用法：在 SSH 主機上建一個空資料夾，把 `CLAUDE.md` 放進去，開 `claude`，然後**依序**貼下面的 prompt。
> 每一階段結束 Claude Code 會停下來回報，你確認沒問題再貼下一段。
> `CLAUDE.md` 已經寫好所有規格，所以 prompt 不用重複規格，只講「這一步要做什麼」。

---

## 第 0 步：你要先手動下載的東西（Claude Code 的主機可能連不到政府網站）

| # | 資料 | 去哪裡 | 放到 |
|---|---|---|---|
| 1 | 死因統計 105–114 年「縣市及鄉鎮統計表」(zip) ×10 | 衛福部統計處死因統計頁，每年一頁（例：`https://dep.mohw.gov.tw/DOS/lp-5069-113-xCat-y105.html`，把 y105 改成 y106…y114） | `data/raw/mortality/` |
| 2 | 同一頁的「死因統計年報」或「結果分析」（找 108 年準則轉換比值） | 同上 | `data/raw/mortality/` |
| 3 | PM2.5 測站歷史資料 105–114 年 | https://airtw.moenv.gov.tw/cht/Query/His_Data.aspx （本島所有一般／交通／工業測站） | `data/raw/pm25/` |
| 4 | 測站座標（測站基本資料） | 環境部環境資料開放平臺搜尋「空氣品質監測站基本資料」 | `data/raw/pm25/` |
| 5 | 鄉鎮市區界線 Shapefile | 政府資料開放平臺搜尋「鄉鎮市區界線(TWD97經緯度)」 | `data/raw/boundary/` |
| 6 | （備案才需要）鄉鎮年齡別人口 | 內政部戶政司人口統計資料 | `data/raw/population/` |

ERA5 溫度和 NDVI 不用自己下載，第 5 步會讓 Claude Code 寫 GEE 腳本，你貼到 GEE Code Editor 跑完匯出 CSV 即可。

> 小提醒：airtw 歷史資料通常要一站一年下載，很花時間。先貼第 1 步給 Claude Code，請它看看環境部開放資料有沒有 API 可以批次抓 PM2.5 日均值；有的話你在自己電腦跑它寫的下載腳本就好。

---

## 第 1 步：建好 repo 骨架、看一下原始資料

```
請讀 CLAUDE.md。這一步只做準備工作：
1. 依照 CLAUDE.md 建立資料夾結構、environment.yml、.gitignore（data/raw 和 data/interim 不進 git）、空的 docs/processing_log.md
2. 列出 data/raw/ 底下每個檔案（大小、格式），zip 檔先解壓到原地
3. 每一類原始資料各打開一個檔案，告訴我：有哪些工作表／欄位、用什麼編碼、是否有鄉鎮代碼
4. 另外看一下環境部開放資料有沒有可以批次下載 PM2.5 測站日均值或月均值的 API，有的話寫一支 src/00_download_pm25.py 給我（我會自己在本機跑）
做完先停下來回報，不要開始清資料。
```

---

## 第 2 步：鄉鎮主表（349 個鄉鎮，之後所有資料都 join 這張表）

```
做 src/01_town_master.py：
- 讀 data/raw/boundary 的鄉鎮界 Shapefile，轉成 EPSG:3826
- 依 CLAUDE.md 篩出本島 349 個鄉鎮，輸出 data/interim/town_master.gpkg（towncode, county, town, geometry）
- 檢查 105–114 年之間有沒有鄉鎮改名或代碼異動（例如縣市名稱「臺／台」寫法不同），整理一張中文名稱 → towncode 的對照表 data/interim/town_name_lookup.csv，之後死亡率資料用中文名稱對應時就查這張表
- 畫一張 349 個鄉鎮的地圖存到 figures/qa/town_master.png
回報鄉鎮數、被排除的鄉鎮清單。
```

---

## 第 3 步：心臟疾病死亡率（最容易出問題，慢慢來）

```
做 src/02_mortality.py，但先不要寫完整程式，先做檢查並回報：
1. 105–114 年每一年的鄉鎮統計表裡，心臟疾病（高血壓性疾病除外）有哪些欄位？有沒有「鄉鎮層級的標準化死亡率」？還是只有死亡人數和粗死亡率？
2. 各年的表格格式是否一致（工作表名稱、欄位位置、死因分類名稱）？
3. 年報或結果分析裡有沒有 108 年死因選取準則的「轉換比值」？是全國一個值，還是分縣市／分死因？
4. 每一年能對到 town_master 的鄉鎮有幾個？列出對不到的
等我確認處理方式之後，再輸出 data/interim/mortality.csv（towncode, year, roc_year, asmr_heart, deaths, pop，以及 CLAUDE.md 提到的 raw/adj 欄位）。
```

> 看到它的回報後，可能的回覆：
> - 「有鄉鎮標準化死亡率 → 直接用；轉換比值只有全國值 → 105–107 乘上全國心臟疾病轉換比值，原始值另存一欄」
> - 「沒有鄉鎮標準化死亡率 → 用 CLAUDE.md 備案 A，我已經把人口資料放到 data/raw/population」

---

## 第 4 步：PM2.5（測站 → 內插 → 鄉鎮）

```
做 src/03_pm25.py：
1. 整理測站資料成「測站 × 年」的 PM2.5 年平均。資料為環境部日均值（aqx_p_19），值為 x 視為無效日；一年至少 75% 有效日，達不到的測站-年剔除。剔除了哪些寫進 processing_log
2. 只用本島測站。輸出 data/interim/pm25_station_annual.csv（站名、經緯度、TWD97 X/Y、年份、年均值、有效日數）
3. 每一年各做一次內插，網格 1 km、範圍是本島外框：
   - 主要方法：IDW（power = 2）
   - 比較用：Ordinary Kriging（pykrige，variogram 用 spherical，順便把 variogram 參數記下來）
4. 用 rasterstats 算每個鄉鎮的網格平均（zonal mean），輸出 data/interim/pm25.csv（towncode, year, pm25, pm25_krig）
5. QA：做 leave-one-out 交叉驗證，比較 IDW 和 Kriging 的 RMSE；畫 105 年和 114 年的 PM2.5 鄉鎮地圖存到 figures/qa/
回報：每年可用測站數、LOOCV RMSE、有沒有鄉鎮是 NaN（山區小鄉鎮 1 km 網格可能沒有落在裡面，請用 all_touched=True 或改用鄉鎮重心取值處理）。
```

---

## 第 5 步：溫度 + NDVI（GEE）

```
寫一支 GEE JavaScript 腳本 gee/export_tmean_ndvi.js，讓我貼到 GEE Code Editor 執行：
- 鄉鎮邊界：假設我已經把 data/interim/town_master 上傳成 asset，路徑寫成變數放在腳本最上面讓我改
- 溫度：ECMWF/ERA5_LAND/MONTHLY_AGGR 的 temperature_2m，2016–2025 每一年 12 個月平均，K 轉 °C
- NDVI：MODIS/061/MOD13Q1，用 SummaryQA 只留 good/marginal 像元，乘 0.0001，每一年平均
- 用 reduceRegions（mean）算到每個鄉鎮，scale：溫度 1000、NDVI 250
- 匯出一個 CSV 到 Google Drive：towncode, year, tmean, ndvi
- 腳本內加中文註解，並告訴我上傳 asset 的步驟（要先把 gpkg 轉成 shapefile zip 並轉回 EPSG:4326）
另外寫 src/04_gee_clean.py，讀我匯出後放到 data/raw/gee/ 的 CSV，檢查筆數、缺值、數值範圍（tmean 大約 5–27 °C，ndvi 介於 -1 到 1），輸出 data/interim/climate_ndvi.csv。
```

> ERA5-Land 解析度約 9 km，比 ERA5（約 28 km）細，小鄉鎮比較不會整片抓到同一格。如果組員堅持用 ERA5，把資料集改成 `ECMWF/ERA5/MONTHLY` 即可。

---

## 第 6 步：合併 + 品質檢查 + 交付檔

```
做 src/05_merge.py：
1. 以 town_master 為主表，把 mortality、pm25、climate_ndvi 依 (towncode, year) left join
2. 檢查：剛好 3,490 列？每個變數的缺值數、最小/最大/平均值？有沒有重複的 (towncode, year)？
   依 CLAUDE.md「缺值處理規則」加上 f_asmr / f_pm25 / f_tmean / f_ndvi 旗標欄，並輸出 docs/missing_summary.csv。
   特別確認：死亡數為 0 的鄉鎮-年是 0 不是 NaN；沒有任何 NaN 被填成 0 或平均值。
3. 輸出 CLAUDE.md 列的所有 processed 檔案（panel_long.csv、town_mean_105_114.csv、town_panel.gpkg、town_panel_shp/、data_dictionary.csv）
4. QA 圖存到 figures/qa/：四個變數 10 年平均的鄉鎮地圖（2×2）、四個變數的直方圖、全國平均隨年份變化的折線圖
5. 寫一支 src/run_all.sh，從頭到尾重跑 01–05
回報檢查結果，並把 QA 地圖給我看。
```

---

## 第 7 步：README + 推上 GitHub

```
1. 寫 README.md（繁體中文），內容包含：
   - 專案一句話介紹、資料範圍（105–114 年、本島 349 鄉鎮、3,490 筆）
   - 「我只想拿資料」區塊：直接下載 data/processed/ 的哪個檔案做什麼用
     （panel_long.csv → 時間趨勢、假設檢定；town_mean_105_114.csv / town_panel.gpkg → Moran's I、熱點分析、GWR）
   - Python 和 R 各一段 5 行內的讀檔範例（geopandas.read_file、sf::st_read），含 towncode 要用字串讀
   - 欄位說明表（從 data_dictionary.csv 生成）
   - 資料來源與處理方式（每個變數一小段，含網址）
   - 缺值說明：旗標欄 0/1/2 的意思，並貼上 docs/missing_summary.csv 的表格
   - ⚠️ 限制與注意事項：108 年死因準則改變、小鄉鎮死亡率不穩、PM2.5 是內插值不是實測、ERA5-Land 解析度、生態謬誤（鄉鎮層級關聯不等於個人層級因果）
   - 如何重跑（conda env create → bash src/run_all.sh）
   - 參考資料（APA 格式，報告第七章可以直接複製）
2. 確認 .gitignore 正確、data/processed 每個檔案 < 50 MB
3. 先跑 gh auth status，確認登入帳號和 CLAUDE.md「GitHub」段落寫的一致；不一致就停下來
4. git init、commit，用 gh 在該帳號下建 private repo heart-env-taiwan 並推上去
```

---

## 卡住時可以用的 prompt

- **結果怪怪的**：「`<變數>` 在 `<某鄉鎮/某年>` 的值是 X，看起來不合理。請追溯這個值是從哪個原始檔、哪一列算出來的，不要直接改。」
- **要省時間**：「PM2.5 先只做 IDW，Kriging 之後有空再補，在 README 標明。」
- **組員要另一種格式**：「從 panel_long.csv 另外輸出一份 wide format（每個變數 × 年份一欄）給 Excel 使用者，檔名 panel_wide.xlsx。」
