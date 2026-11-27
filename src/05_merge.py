"""合併四個變數 → 交付檔（panel long、10 年平均橫斷面、GeoPackage、Shapefile、資料字典）+ QA。

從 repo 根目錄執行：python src/05_merge.py
輸入：data/interim/town_master.gpkg（layer town_master）
      data/interim/mortality.csv, pm25.csv, climate_ndvi.csv
輸出：data/processed/panel_long.csv            3,490 列（UTF-8 with BOM）
      data/processed/town_mean_105_114.csv     349 列，各變數 10 年平均
      data/processed/town_panel.gpkg           鄉鎮多邊形 + 10 年平均（EPSG:3826）
      data/processed/town_panel_shp/           同上 Shapefile 版
      data/processed/data_dictionary.csv
      docs/missing_summary.csv                 變數 × 年份的缺值數與旗標 1 筆數
      figures/qa/map_mean_2x2.png, hist_4vars.png, trend_national.png
總原則：保留 NaN，不填 0、不填平均、不做時間內插。
"""
import shutil
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK TC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

INTERIM = Path("data/interim")
OUT = Path("data/processed")
DOCS = Path("docs")
QA = Path("figures/qa")
N_TOWN, YEARS = 349, list(range(2016, 2026))

PANEL_COLS = ["towncode", "county", "town", "year", "roc_year",
              "asmr_heart", "deaths", "pop", "pm25", "tmean", "ndvi",
              "f_asmr", "f_pm25", "f_tmean", "f_ndvi",
              "asmr_raw", "asmr_adj", "cmr_heart", "cmr_adj", "rule_chg", "pm25_krig"]
VARS = [("asmr_heart", "f_asmr"), ("pm25", "f_pm25"), ("tmean", "f_tmean"), ("ndvi", "f_ndvi")]
LABEL = {"asmr_heart": "心臟疾病 ASMR（每十萬人）", "pm25": "PM2.5（μg/m³）",
         "tmean": "年均溫（°C）", "ndvi": "NDVI"}
CMAP = {"asmr_heart": "Reds", "pm25": "Oranges", "tmean": "Purples", "ndvi": "Greens"}  # 單一色相 sequential


def load():
    towns = gpd.read_file(INTERIM / "town_master.gpkg", layer="town_master")
    mort = pd.read_csv(INTERIM / "mortality.csv", dtype={"towncode": str})
    pm = pd.read_csv(INTERIM / "pm25.csv", dtype={"towncode": str})
    cl = pd.read_csv(INTERIM / "climate_ndvi.csv", dtype={"towncode": str})
    return towns, mort, pm, cl


def merge(towns, mort, pm, cl):
    base = pd.MultiIndex.from_product([towns["towncode"], YEARS], names=["towncode", "year"]).to_frame(index=False)
    base = base.merge(towns[["towncode", "county", "town"]], on="towncode")
    base["roc_year"] = base["year"] - 1911
    p = (base.merge(mort.drop(columns="roc_year"), on=["towncode", "year"], how="left", validate="1:1")
             .merge(pm, on=["towncode", "year"], how="left", validate="1:1")
             .merge(cl, on=["towncode", "year"], how="left", validate="1:1"))
    p["deaths"] = p["deaths"].astype("Int64")
    for f in ["f_asmr", "f_pm25", "f_tmean", "f_ndvi"]:
        p[f] = p[f].astype("Int64")
    return p[PANEL_COLS].sort_values(["towncode", "year"]).reset_index(drop=True), (mort, pm, cl)


def checks(p, sources):
    mort, pm, cl = sources
    errs = []
    if len(p) != N_TOWN * len(YEARS):
        errs.append(f"列數 {len(p)} ≠ 3490")
    if p.duplicated(["towncode", "year"]).any():
        errs.append("有重複 (towncode, year)")
    # NaN 數必須與來源相同（沒有任何值被填補）
    for col, src in [("asmr_heart", mort), ("deaths", mort), ("pop", mort), ("cmr_heart", mort), ("cmr_adj", mort),
                     ("pm25", pm), ("pm25_krig", pm), ("tmean", cl), ("ndvi", cl)]:
        if p[col].isna().sum() != src[col].isna().sum():
            errs.append(f"{col} NaN 數與來源不同")
    # 旗標與 NaN 一致：旗標 2 ⇔ NaN
    for v, f in VARS:
        if not ((p[f] == 2) == p[v].isna()).all():
            errs.append(f"{f} = 2 與 {v} NaN 不一致")
    # 死亡數 0 → asmr 0（不是 NaN）
    z = p[p["deaths"] == 0]
    if z["asmr_heart"].isna().any() or (z["asmr_heart"] != 0).any():
        errs.append("deaths = 0 的列 asmr_heart 不是 0")
    if errs:
        print("!! 檢查失敗：\n  " + "\n  ".join(errs))
        sys.exit(1)
    return z


def missing_summary(p):
    rows = []
    for v, f in VARS:
        for y in YEARS:
            s = p[p["year"] == y]
            rows.append({"variable": v, "year": y, "roc_year": y - 1911, "n": len(s),
                         "n_missing": int(s[v].isna().sum()), "n_flag1": int((s[f] == 1).sum())})
    ms = pd.DataFrame(rows)
    ms.to_csv(DOCS / "missing_summary.csv", index=False, encoding="utf-8-sig")
    return ms


def town_means(p):
    g = p.groupby("towncode")
    m = g[["asmr_heart", "asmr_raw", "cmr_heart", "cmr_adj", "pop", "pm25", "pm25_krig", "tmean", "ndvi"]].mean()
    m["deaths"] = g["deaths"].mean()
    m["deaths_sum"] = g["deaths"].sum().astype(int)
    m["n_asmr"] = g["asmr_heart"].count()  # 有 ASMR 的年數（112–114 遮蔽者 < 10）
    m["n_flag1"] = g[["f_pm25", "f_tmean", "f_ndvi"]].apply(lambda d: int((d == 1).sum().sum()))
    m = m.reset_index().merge(p[["towncode", "county", "town"]].drop_duplicates(), on="towncode")
    cols = ["towncode", "county", "town", "asmr_heart", "n_asmr", "asmr_raw", "cmr_heart", "cmr_adj", "deaths",
            "deaths_sum", "pop", "pm25", "pm25_krig", "tmean", "ndvi", "n_flag1"]
    m = m[cols].sort_values("towncode").reset_index(drop=True)
    assert all(len(c) <= 10 for c in m.columns)
    return m


DICT = [
    # col, 中文說明, 單位, 來源, 處理方式, 檔案
    ("towncode", "鄉鎮市區代碼（內政部 8 碼，字串，保留前導 0）", "", "國土測繪中心鄉鎮界 TOWN_MOI_1140318", "合併鍵", "all"),
    ("county", "縣市名稱", "", "同上", "", "all"),
    ("town", "鄉鎮市區名稱", "", "同上", "", "all"),
    ("year", "西元年", "年", "", "2016–2025", "panel"),
    ("roc_year", "民國年", "年", "", "105–114", "panel"),
    ("asmr_heart", "心臟疾病（高血壓性疾病除外）年齡標準化死亡率，主要分析變數（= asmr_adj）", "每十萬人口",
     "衛福部統計處 死因統計 縣市及鄉鎮統計表", "105–107 年 × 全國轉換比值 0.9162；112 年起死亡數 < 20 被遮蔽 → NaN；town_mean 為有值年份平均", "all"),
    ("asmr_raw", "原發布年齡標準化死亡率（未經 108 年準則轉換）", "每十萬人口", "同上", "原值", "all"),
    ("asmr_adj", "經轉換比值調整後年齡標準化死亡率", "每十萬人口", "同上；轉換比值見 108–114 年死因統計結果分析附表 1",
     "105–107 = asmr_raw × 0.9162；108–114 = asmr_raw", "panel"),
    ("cmr_heart", "心臟疾病粗死亡率（自行計算，未經 108 年準則轉換）", "每十萬人口", "同上",
     "deaths / pop × 10⁵；所有年份皆有值；105–107 與 108 年後不可直接比較", "all"),
    ("cmr_adj", "經轉換比值調整後心臟疾病粗死亡率", "每十萬人口", "同上；轉換比值見 108–114 年死因統計結果分析附表 1",
     "105–107 = cmr_heart × 0.9104；108–114 = cmr_heart；所有年份皆有值", "all"),
    ("rule_chg", "死因選取準則虛擬變數：0 = 舊準則（105–107）、1 = WHO 2016 版（108–114）", "0/1", "",
     "依年份產生", "panel"),
    ("deaths", "心臟疾病死亡人數（原發布，未乘轉換比值）", "人", "同上", "town_mean 為 10 年平均", "all"),
    ("deaths_sum", "心臟疾病 10 年死亡人數合計", "人", "同上", "", "mean"),
    ("pop", "年中人口", "人", "同上（工作表附註）", "town_mean 為 10 年平均", "all"),
    ("n_asmr", "有 asmr_heart 值的年數", "年", "", "10 減去被遮蔽年數", "mean"),
    ("pm25", "PM2.5 年平均濃度（IDW 內插，主要）", "μg/m³", "環境部 空氣品質監測日平均值 aqx_p_19",
     "測站有效日 ≥ 75% 才參與；1 km 網格 IDW (p=2) → 鄉鎮網格平均", "all"),
    ("pm25_krig", "PM2.5 年平均濃度（Ordinary Kriging，比較用）", "μg/m³", "同上",
     "spherical variogram；1 km 網格 → 鄉鎮網格平均；LOOCV RMSE 低於 IDW", "all"),
    ("tmean", "年平均氣溫", "°C", "ERA5-Land monthly（GEE ECMWF/ERA5_LAND/MONTHLY_AGGR, temperature_2m）",
     "12 個月平均，K → °C；reduceRegions mean scale 1 km；9 個沿海鄉鎮以 20 km 內陸地網格補值（f_tmean = 1）", "all"),
    ("ndvi", "年平均 NDVI", "無單位（−1～1）", "MODIS MOD13Q1 v061（GEE MODIS/061/MOD13Q1）",
     "× 0.0001；SummaryQA good 像元年平均，整年無 good 則放寬 good+marginal（f_ndvi = 1）；scale 250 m", "all"),
    ("f_asmr", "asmr_heart 旗標：0 正常、2 缺值（112 年起遮蔽「*」）", "代碼", "", "見 docs/processing_log.md", "panel"),
    ("f_pm25", "pm25 旗標：0 正常、1 替代方法（all_touched／重心網格）、2 缺值", "代碼", "", "", "panel"),
    ("f_tmean", "tmean 旗標：0 正常、1 替代方法（buffer／最近陸地網格）、2 缺值", "代碼", "", "", "panel"),
    ("f_ndvi", "ndvi 旗標：0 正常、1 替代方法（good+marginal／buffer）、2 缺值", "代碼", "", "", "panel"),
    ("n_flag1", "10 年中 pm25、tmean、ndvi 旗標為 1 的筆數合計", "筆", "", "", "mean"),
]


def write_outputs(p, m, towns):
    OUT.mkdir(parents=True, exist_ok=True)
    p.to_csv(OUT / "panel_long.csv", index=False, encoding="utf-8-sig")
    m.to_csv(OUT / "town_mean_105_114.csv", index=False, encoding="utf-8-sig")

    gm = towns[["towncode", "geometry"]].merge(m, on="towncode")
    gm = gpd.GeoDataFrame(gm, geometry="geometry", crs=towns.crs)
    assert gm.crs.to_epsg() == 3826 and len(gm) == N_TOWN
    gpkg = OUT / "town_panel.gpkg"
    gpkg.unlink(missing_ok=True)
    gm.to_file(gpkg, driver="GPKG", layer="town_panel")

    shp_dir = OUT / "town_panel_shp"
    shutil.rmtree(shp_dir, ignore_errors=True)
    shp_dir.mkdir()
    gm.to_file(shp_dir / "town_panel.shp", driver="ESRI Shapefile", encoding="UTF-8")

    d = pd.DataFrame(DICT, columns=["column", "description_zh", "unit", "source", "processing", "files"])
    d["files"] = d["files"].map({"all": "panel_long; town_mean; gpkg/shp", "panel": "panel_long",
                                 "mean": "town_mean; gpkg/shp"})
    assert set(p.columns) | set(m.columns) <= set(d["column"]), set(p.columns) | set(m.columns) - set(d["column"])
    d.to_csv(OUT / "data_dictionary.csv", index=False, encoding="utf-8-sig")
    return gm


# ---------------------------------------------------------------- QA 圖
def qa_maps(gm):
    fig, axes = plt.subplots(2, 2, figsize=(11, 14))
    for ax, (v, _) in zip(axes.ravel(), VARS):
        gm.plot(ax=ax, column=v, cmap=CMAP[v], legend=True, edgecolor="white", linewidth=0.1,
                missing_kwds={"color": "#d9d9d9", "label": "NaN"},
                legend_kwds={"shrink": 0.55, "label": LABEL[v]})
        ax.set_title(f"{LABEL[v]}　105–114 年平均", fontsize=11)
        ax.set_axis_off()
    fig.suptitle("臺灣本島 349 鄉鎮　各變數 10 年平均", fontsize=13)
    fig.tight_layout()
    fig.savefig(QA / "map_mean_2x2.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def qa_hist(p):
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    for ax, (v, _) in zip(axes.ravel(), VARS):
        s = p[v].dropna()
        ax.hist(s, bins=40, color=plt.get_cmap(CMAP[v])(0.65), edgecolor="white", linewidth=0.5)
        ax.set_title(f"{LABEL[v]}（n = {len(s):,}，NaN {p[v].isna().sum()}）", fontsize=10)
        ax.set_ylabel("鄉鎮-年數")
        ax.grid(axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("panel_long 各變數分布（鄉鎮 × 年，3,490 筆）", fontsize=12)
    fig.tight_layout()
    fig.savefig(QA / "hist_4vars.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def qa_trend(p):
    t = p.groupby("year")[["asmr_heart", "asmr_raw", "pm25", "tmean", "ndvi", "cmr_heart"]].mean()
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    ink, muted = "#333333", "#999999"
    for ax, (v, _) in zip(axes.ravel(), VARS):
        c = plt.get_cmap(CMAP[v])(0.75)
        ax.plot(t.index, t[v], "o-", color=c, lw=2, ms=6)
        if v == "asmr_heart":
            ax.plot(t.index, t["asmr_raw"], "s--", color=muted, lw=1.5, ms=5)
            ax.annotate("轉換後（asmr_heart）", (2016, t[v].iloc[0]), xytext=(4, -14),
                        textcoords="offset points", fontsize=8, color=ink)
            ax.annotate("原發布（asmr_raw）", (2016, t["asmr_raw"].iloc[0]), xytext=(4, 6),
                        textcoords="offset points", fontsize=8, color=ink)
            ax.axvspan(2022.5, 2025.5, color="#eeeeee", zorder=0)
            ax.text(2024, ax.get_ylim()[0], "112 年起\n小鄉鎮遮蔽", ha="center", va="bottom", fontsize=8, color=ink)
            ax.axvline(2018.5, color=muted, lw=0.8, ls=":")
        ax.set_title(f"{LABEL[v]}", fontsize=10)
        ax.grid(alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xticks(YEARS)
        ax.set_xticklabels([f"{y}\n({y - 1911})" for y in YEARS], fontsize=7)
    fig.suptitle("各變數全國平均（本島鄉鎮簡單平均）隨年份變化", fontsize=12)
    fig.tight_layout()
    fig.savefig(QA / "trend_national.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    towns, mort, pm, cl = load()
    p, sources = merge(towns, mort, pm, cl)
    zero = checks(p, sources)
    ms = missing_summary(p)
    m = town_means(p)
    gm = write_outputs(p, m, towns)
    QA.mkdir(parents=True, exist_ok=True)
    qa_maps(gm)
    qa_hist(p)
    qa_trend(p)

    # ---- 回報 ----
    print(f"panel_long：{len(p)} 列 × {p.shape[1]} 欄；重複 (towncode, year)：{int(p.duplicated(['towncode', 'year']).sum())}")
    print(f"town_mean：{len(m)} 列；gpkg/shp：{len(gm)} 個多邊形，EPSG:{gm.crs.to_epsg()}")
    print("\n數值摘要：")
    num = ["asmr_heart", "asmr_raw", "cmr_heart", "deaths", "pop", "pm25", "pm25_krig", "tmean", "ndvi"]
    s = p[num].astype(float).describe().T[["count", "mean", "min", "max"]]
    s["n_nan"] = p[num].isna().sum()
    print(s.round(2).to_string())
    print("\n缺值與旗標 1（變數 × 年）：")
    print(ms.pivot(index="variable", columns="roc_year", values="n_missing").to_string())
    print(ms.pivot(index="variable", columns="roc_year", values="n_flag1").to_string())
    print(f"\ndeaths = 0：{len(zero)} 筆，asmr_heart 皆為 0（不是 NaN）")
    print("town_mean n_asmr 分布：", m["n_asmr"].value_counts().sort_index().to_dict())
    print("\n檔案大小：")
    for f in sorted(OUT.rglob("*")):
        if f.is_file() and f.name != ".gitkeep":
            print(f"  {f}  {f.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
