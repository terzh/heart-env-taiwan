"""整理 GEE 匯出的氣溫與 NDVI：檢查筆數、缺值、數值範圍，依 CLAUDE.md 規則挑選替代值並標旗標。

從 repo 根目錄執行：python src/04_gee_clean.py
輸入：data/raw/gee/*.csv（gee/export_tmean_ndvi.js 匯出）
      data/interim/town_master.gpkg（核對 349 鄉鎮）
輸出：data/interim/climate_ndvi.csv  towncode, year, tmean, ndvi, f_tmean, f_ndvi

旗標規則（CLAUDE.md）：
- tmean：多邊形平均 → 0；空值改用重心 1 km buffer → 1；仍空（ERA5-Land 海洋格）改用周圍 20 km
         陸地網格平均補值後的多邊形平均 → 1；仍空 → NaN, 2
- ndvi ：多邊形 good → 0；good 空值時依序改用 多邊形 good+marginal、buffer good、buffer good+marginal → 1；
         全部為空 → NaN, 2
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

RAW = Path("data/raw/gee")
INTERIM = Path("data/interim")
YEARS = list(range(2016, 2026))
TMEAN_RANGE = (5, 27)    # °C，臺灣鄉鎮年均合理範圍
NDVI_RANGE = (-1, 1)


def pick(df, cols):
    """依序取第一個非空欄位；回傳值與來源序號（-1 = 全空）。"""
    val = pd.Series(np.nan, index=df.index)
    src = pd.Series(-1, index=df.index)
    for i, c in enumerate(cols):
        m = val.isna() & df[c].notna()
        val[m], src[m] = df.loc[m, c], i
    return val, src


def main():
    files = sorted(RAW.glob("*.csv"))
    if not files:
        sys.exit("data/raw/gee/ 沒有 CSV，請先在 GEE 執行 gee/export_tmean_ndvi.js 並下載匯出檔")
    g = pd.concat(pd.read_csv(f, dtype={"towncode": str}) for f in files)
    print(f"讀入 {len(files)} 個檔，{len(g)} 列")

    towns = gpd.read_file(INTERIM / "town_master.gpkg", layer="town_master")["towncode"]
    # ---- 筆數與鍵檢查 ----
    problems = []
    if g.duplicated(["towncode", "year"]).any():
        problems.append(f"重複 (towncode, year)：{int(g.duplicated(['towncode', 'year']).sum())}")
    miss_years = sorted(set(YEARS) - set(g["year"]))
    if miss_years:
        problems.append(f"整年缺資料：{miss_years}")
    extra = sorted(set(g["towncode"]) - set(towns))
    lost = sorted(set(towns) - set(g["towncode"]))
    if extra:
        problems.append(f"不在主表的 towncode：{extra[:10]}")
    if lost:
        problems.append(f"主表鄉鎮沒有資料：{lost[:10]}（共 {len(lost)}）")
    if problems:
        print("!! 停止，請回報：")
        print("\n".join("  - " + p for p in problems))
        sys.exit(1)

    full = pd.MultiIndex.from_product([sorted(towns), YEARS], names=["towncode", "year"]).to_frame(index=False)
    g = full.merge(g, on=["towncode", "year"], how="left")

    # ---- 挑選與旗標 ----
    g["tmean_v"], s = pick(g, ["tmean", "tmean_buf", "tmean_nn"])
    g["f_tmean"] = np.select([s == 0, s > 0], [0, 1], 2)
    g["tmean_src"] = s.map({0: "poly", 1: "buf_1km", 2: "nearest_land_20km", -1: "NaN"})
    g["ndvi_v"], s = pick(g, ["ndvi_g", "ndvi_gm", "ndvi_g_buf", "ndvi_gm_buf"])
    g["f_ndvi"] = np.select([s == 0, s > 0], [0, 1], 2)
    g["ndvi_src"] = s.map({0: "poly_good", 1: "poly_good+marginal", 2: "buf_good", 3: "buf_good+marginal", -1: "NaN"})

    out = g.rename(columns={"tmean_v": "tmean", "ndvi_v": "ndvi", "tmean": "tmean_poly"})[
        ["towncode", "year", "tmean", "ndvi", "f_tmean", "f_ndvi"]
    ]
    assert len(out) == 349 * len(YEARS)

    # ---- 範圍檢查 ----
    bad_t = out[(out["tmean"] < TMEAN_RANGE[0]) | (out["tmean"] > TMEAN_RANGE[1])]
    bad_n = out[(out["ndvi"] < NDVI_RANGE[0]) | (out["ndvi"] > NDVI_RANGE[1])]
    out.to_csv(INTERIM / "climate_ndvi.csv", index=False, encoding="utf-8-sig")

    print(f"輸出 {len(out)} 列 → data/interim/climate_ndvi.csv")
    print("\n各年摘要：")
    print(out.groupby("year").agg(tmean_mean=("tmean", "mean"), tmean_min=("tmean", "min"), tmean_max=("tmean", "max"),
                                  ndvi_mean=("ndvi", "mean"), ndvi_min=("ndvi", "min"), ndvi_max=("ndvi", "max"),
                                  f_tmean1=("f_tmean", lambda s: (s == 1).sum()), f_tmean2=("f_tmean", lambda s: (s == 2).sum()),
                                  f_ndvi1=("f_ndvi", lambda s: (s == 1).sum()), f_ndvi2=("f_ndvi", lambda s: (s == 2).sum()),
                                  ).round(3).to_string())
    print("\ntmean 來源：", g["tmean_src"].value_counts().to_dict())
    print("NDVI 來源：", g["ndvi_src"].value_counts().to_dict())
    flagged = g[(g["f_tmean"] > 0) | (g["f_ndvi"] > 0)][["towncode", "year", "f_tmean", "f_ndvi", "tmean_src", "ndvi_src"]]
    if len(flagged):
        print("\n旗標 1/2 的鄉鎮-年：")
        print(flagged.to_string(index=False))
    print(f"\ntmean 超出 {TMEAN_RANGE}：{len(bad_t)} 筆；ndvi 超出 {NDVI_RANGE}：{len(bad_n)} 筆")
    if len(bad_t):
        print(bad_t.to_string(index=False))


if __name__ == "__main__":
    main()
