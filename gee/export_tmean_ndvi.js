/*******************************************************************************
 * 鄉鎮年平均氣溫（ERA5-Land）與年平均 NDVI（MODIS MOD13Q1），2016–2025
 * 臺灣本島 349 鄉鎮 → 匯出一個 CSV 到 Google Drive
 *
 * 用法：
 *   1. 依 README / 回報說明把 town_master_4326.zip 上傳成 asset
 *   2. 修改下面的 TOWNS_ASSET 為你的 asset 路徑
 *   3. 貼到 https://code.earthengine.google.com 按 Run
 *   4. 右側 Tasks 分頁按 RUN 啟動匯出；完成後到 Google Drive 下載 CSV
 *   5. 把 CSV 放到 repo 的 data/raw/gee/，再執行 python src/04_gee_clean.py
 *
 * 匯出欄位（缺值的組合由 src/04_gee_clean.py 依 CLAUDE.md 規則挑選並標旗標）：
 *   towncode, year
 *   tmean        鄉鎮多邊形平均氣溫 °C（scale 1000）
 *   tmean_buf    鄉鎮重心 1 km buffer 平均氣溫 °C（多邊形回傳空值時的替代）
 *   tmean_nn     空值網格以周圍 20 km 內陸地網格平均補上後的多邊形平均（buffer 仍空時的替代）
 *   ndvi_g       只用 SummaryQA = 0（good）像元的年平均 NDVI（scale 250）
 *   ndvi_gm      SummaryQA = 0 或 1（good + marginal）的年平均 NDVI
 *   ndvi_g_buf   重心 1 km buffer，good
 *   ndvi_gm_buf  重心 1 km buffer，good + marginal
 ******************************************************************************/

// ======== 要修改的地方 ========
var TOWNS_ASSET = 'projects/deft-crawler-423708-b1/assets/town_master_4326';  // ← 你的 asset 路徑
var DRIVE_FOLDER = 'gee_exports';          // Google Drive 資料夾名稱（不存在會自動建立）
var FILE_NAME = 'tmean_ndvi_2016_2025';    // 匯出檔名（.csv）
// ==============================

var START_YEAR = 2016;
var END_YEAR = 2025;
var BUFFER_M = 1000;      // 重心 buffer 半徑（公尺）
var NN_RADIUS_M = 20000;  // 氣溫空值網格以此半徑內陸地網格平均補值（公尺）

// ---- 鄉鎮邊界與重心 buffer ----
var towns = ee.FeatureCollection(TOWNS_ASSET).select(['towncode']);
var townBuf = towns.map(function (f) {
  return ee.Feature(f.geometry().centroid(10).buffer(BUFFER_M), {towncode: f.get('towncode')});
});
print('鄉鎮數（應為 349）', towns.size());

// ---- 氣溫：ERA5-Land 月資料，12 個月平均，K → °C ----
var era5 = ee.ImageCollection('ECMWF/ERA5_LAND/MONTHLY_AGGR').select('temperature_2m');
// year 可能是 ee.Number（伺服器端），不能用 year + 1，改用日期 advance
function yearRange(year) {
  var start = ee.Date.fromYMD(year, 1, 1);
  return [start, start.advance(1, 'year')];
}

function tmeanImage(year) {
  var r = yearRange(year);
  var ic = era5.filterDate(r[0], r[1]);
  return ic.mean().subtract(273.15).rename('tmean').set('n_months', ic.size());
}

// ---- NDVI：MOD13Q1 16 天合成，SummaryQA 去雲，× 0.0001，年平均 ----
// SummaryQA：0 = good，1 = marginal，2 = snow/ice，3 = cloudy
var mod13 = ee.ImageCollection('MODIS/061/MOD13Q1');
function ndviImage(year, maxQA, name) {
  var r = yearRange(year);
  var ic = mod13.filterDate(r[0], r[1])
    .map(function (img) {
      var qa = img.select('SummaryQA');
      return img.select('NDVI').multiply(0.0001).updateMask(qa.lte(maxQA));
    });
  return ic.mean().rename(name);  // 每個像元：當年有效合成期的平均
}

// ---- 逐年計算 ----
var years = ee.List.sequence(START_YEAR, END_YEAR);

var table = ee.FeatureCollection(years.map(function (y) {
  y = ee.Number(y).int();
  var t = tmeanImage(y);
  var nd = ndviImage(y, 0, 'ndvi_g').addBands(ndviImage(y, 1, 'ndvi_gm'));

  // 鄉鎮多邊形
  var tPoly = t.reduceRegions({collection: towns, reducer: ee.Reducer.mean().setOutputs(['tmean']),
                               scale: 1000, tileScale: 4});
  var nPoly = nd.reduceRegions({collection: towns, reducer: ee.Reducer.mean(), scale: 250, tileScale: 4});
  // 重心 1 km buffer
  var tBuf = t.reduceRegions({collection: townBuf, reducer: ee.Reducer.mean().setOutputs(['tmean_buf']),
                              scale: 1000, tileScale: 4});
  // 最近陸地網格：ERA5-Land 海洋格為空值，沿海小鄉鎮（高雄市區等）多邊形與 buffer 都取不到值
  // → 空值網格以周圍 NN_RADIUS_M 內有值網格的平均補上（使用者確認，2026-11-28）
  var tNN = t.unmask(t.focalMean({radius: NN_RADIUS_M, units: 'meters'}))
    .reduceRegions({collection: towns, reducer: ee.Reducer.mean().setOutputs(['tmean_nn']),
                    scale: 1000, tileScale: 4});
  var nBuf = nd.rename(['ndvi_g_buf', 'ndvi_gm_buf'])
    .reduceRegions({collection: townBuf, reducer: ee.Reducer.mean(), scale: 250, tileScale: 4});

  // 以 towncode 合併四組結果
  var join = function (a, b) {
    var j = ee.Join.inner().apply(a, b, ee.Filter.equals({leftField: 'towncode', rightField: 'towncode'}));
    return j.map(function (p) {
      return ee.Feature(null, ee.Feature(p.get('primary')).toDictionary())
        .copyProperties(ee.Feature(p.get('secondary')));
    });
  };
  var merged = join(join(join(join(tPoly, nPoly), tBuf), tNN), nBuf);
  return merged.map(function (f) { return f.set('year', y); });
})).flatten();

// 預覽需要先算完整年 349 鄉鎮，互動模式常超過 5 分鐘逾時；需要時再取消註解
// print('前 5 筆預覽', table.limit(5));

// ---- 匯出到 Google Drive（不含幾何）----
Export.table.toDrive({
  collection: table,
  description: FILE_NAME,
  folder: DRIVE_FOLDER,
  fileNamePrefix: FILE_NAME,
  fileFormat: 'CSV',
  selectors: ['towncode', 'year', 'tmean', 'tmean_buf', 'tmean_nn', 'ndvi_g', 'ndvi_gm', 'ndvi_g_buf', 'ndvi_gm_buf']
});

// ---- 視覺檢查（可選）----
Map.centerObject(towns, 7);
Map.addLayer(tmeanImage(2025).clip(towns), {min: 5, max: 27, palette: ['blue', 'white', 'red']}, 'tmean 2025');
Map.addLayer(ndviImage(2025, 1, 'ndvi').clip(towns), {min: 0, max: 0.9, palette: ['white', 'green']}, 'NDVI 2025', false);
Map.addLayer(towns.style({color: '444444', fillColor: '00000000', width: 0.5}), {}, '鄉鎮界');
