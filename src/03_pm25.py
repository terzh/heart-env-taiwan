"""PM2.5：測站日均值 → 測站年均 → 1 km 網格內插（IDW 主／Ordinary Kriging 比較）→ 鄉鎮 zonal mean。

從 repo 根目錄執行：python src/03_pm25.py
輸入：data/raw/pm25/daily/pm25_daily_YYYY-MM.csv（環境部 aqx_p_19 日平均值）
      data/raw/pm25/stations_aqx_p_07.csv（測站基本資料）
      data/interim/town_master.gpkg（layer town_master）
輸出：data/interim/pm25_station_annual.csv   測站 × 年（含剔除的測站-年，kept 欄標示）
      data/interim/pm25.csv                   towncode, year, pm25, pm25_krig, f_pm25
      data/interim/pm25_variogram.csv         每年 Kriging variogram 參數
      data/interim/pm25_loocv.csv             每年 LOOCV RMSE / MAE（IDW vs Kriging）
      figures/qa/pm25_town_2016.png, pm25_town_2025.png, pm25_loocv.png
"""
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pykrige.ok import OrdinaryKriging
from rasterio.transform import from_origin
from rasterstats import zonal_stats

warnings.filterwarnings("ignore")
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK TC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

RAW = Path("data/raw/pm25")
INTERIM = Path("data/interim")
QA = Path("figures/qa")

YEARS = range(2016, 2026)
MIN_VALID = 0.75  # 一年至少 75% 有效日
CELL = 1000  # 網格 1 km（EPSG:3826，公尺）
IDW_POWER = 2
VARIOGRAM = "spherical"
OFFSHORE_COUNTIES = ["澎湖縣", "金門縣", "連江縣"]

# 現行測站基本資料沒有的測站（使用者提供，2026-11-27）
EXTRA_STATIONS = pd.DataFrame(
    [{"siteid": "3", "sitename": "萬里", "county": "新北市", "sitetype": "一般站",
      "twd97lon": 121.689881, "twd97lat": 25.179667, "coord_src": "user (瑪鋉路221號)"}]
)


# ---------------------------------------------------------------- 測站資料
def load_daily():
    d = pd.concat(pd.read_csv(f, dtype=str) for f in sorted((RAW / "daily").glob("pm25_daily_*.csv")))
    n0 = len(d)
    log = {}
    log["siteid0_dropped"] = int((d["siteid"] == "0").sum())
    d = d[d["siteid"] != "0"]  # 2021-03-23 siteid=0「大城」1 筆，代碼錯誤
    log["x_invalid"] = int((d["concentration"] == "x").sum())
    d["pm25"] = pd.to_numeric(d["concentration"], errors="coerce")  # "x" = 無效值 → NaN
    d["date"] = pd.to_datetime(d["monitordate"])
    dup = d.duplicated(["siteid", "date"], keep=False)
    log["dup_pairs"] = int(d[dup].drop_duplicates(["siteid", "date"]).shape[0])
    d = d.groupby(["siteid", "date"], as_index=False).agg(sitename=("sitename", "first"), pm25=("pm25", "mean"))
    log["rows_in"], log["rows_out"] = n0, len(d)
    return d, log


def load_stations():
    st = pd.read_csv(RAW / "stations_aqx_p_07.csv", dtype=str).assign(coord_src="aqx_p_07")
    extra = EXTRA_STATIONS[~EXTRA_STATIONS["siteid"].isin(st["siteid"])]
    st = pd.concat([st, extra.astype({"twd97lon": str, "twd97lat": str})], ignore_index=True)
    st["lon"], st["lat"] = st["twd97lon"].astype(float), st["twd97lat"].astype(float)
    g = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st["lon"], st["lat"]), crs=4326).to_crs(3826)
    g["x"], g["y"] = g.geometry.x, g.geometry.y
    g["mainland"] = ~g["county"].isin(OFFSHORE_COUNTIES)
    return g[["siteid", "sitename", "county", "sitetype", "lon", "lat", "x", "y", "mainland", "coord_src"]]


def station_annual(d, st):
    d["year"] = d["date"].dt.year
    a = d.groupby(["siteid", "year"]).agg(pm25=("pm25", "mean"), valid_days=("pm25", "count"),
                                           rows=("pm25", "size")).reset_index()
    a["days_in_year"] = np.where(pd.to_datetime(a["year"].astype(str) + "-12-31").dt.dayofyear == 366, 366, 365)
    a["pct_valid"] = a["valid_days"] / a["days_in_year"]
    nocoord = sorted(set(a["siteid"]) - set(st["siteid"]))
    if nocoord:
        raise SystemExit(f"!! 測站沒有座標：{nocoord}")
    a = a.merge(st, on="siteid", how="left")
    a["kept"] = a["mainland"] & (a["pct_valid"] >= MIN_VALID)
    a["drop_reason"] = np.select(
        [~a["mainland"], a["pct_valid"] < MIN_VALID], ["offshore", "valid<75%"], default=""
    )
    return a


# ---------------------------------------------------------------- 內插
def make_grid(towns):
    xmin, ymin, xmax, ymax = towns.total_bounds
    xmin, ymin = np.floor(xmin / CELL) * CELL - CELL, np.floor(ymin / CELL) * CELL - CELL
    xmax, ymax = np.ceil(xmax / CELL) * CELL + CELL, np.ceil(ymax / CELL) * CELL + CELL
    xs = np.arange(xmin + CELL / 2, xmax, CELL)  # 網格中心，西 → 東
    ys = np.arange(ymax - CELL / 2, ymin, -CELL)  # 北 → 南（raster 列順序）
    transform = from_origin(xmin, ymax, CELL, CELL)
    return xs, ys, transform


def idw(sx, sy, sv, px, py, power=IDW_POWER):
    d = np.hypot(px[:, None] - sx[None, :], py[:, None] - sy[None, :])
    with np.errstate(divide="ignore"):
        w = 1.0 / d**power
    exact = d == 0
    w[exact.any(axis=1)] = exact[exact.any(axis=1)].astype(float)  # 網格點剛好在測站上 → 取測站值
    return (w * sv).sum(axis=1) / w.sum(axis=1)


def fit_ok(sx, sy, sv):
    return OrdinaryKriging(sx / 1000, sy / 1000, sv, variogram_model=VARIOGRAM, enable_plotting=False)  # 座標用 km


def interpolate(stn, xs, ys):
    sx, sy, sv = stn["x"].values, stn["y"].values, stn["pm25"].values
    gx, gy = np.meshgrid(xs, ys)
    z_idw = idw(sx, sy, sv, gx.ravel(), gy.ravel()).reshape(gx.shape)
    ok = fit_ok(sx, sy, sv)
    z_krig, _ = ok.execute("grid", xs / 1000, ys / 1000)
    z_krig = np.asarray(z_krig)  # shape (len(ys), len(xs))
    p = ok.variogram_model_parameters  # spherical: [psill, range, nugget]
    vg = {"psill": p[0], "range_km": p[1], "nugget": p[2]}
    return z_idw, z_krig, vg


def loocv(stn):
    sx, sy, sv = stn["x"].values, stn["y"].values, stn["pm25"].values
    e_idw, e_krig = [], []
    for i in range(len(sv)):
        m = np.arange(len(sv)) != i
        e_idw.append(idw(sx[m], sy[m], sv[m], sx[[i]], sy[[i]])[0] - sv[i])
        z, _ = fit_ok(sx[m], sy[m], sv[m]).execute("points", sx[[i]] / 1000, sy[[i]] / 1000)
        e_krig.append(float(np.asarray(z)[0]) - sv[i])
    e_idw, e_krig = np.array(e_idw), np.array(e_krig)
    return {"rmse_idw": np.sqrt(np.mean(e_idw**2)), "rmse_krig": np.sqrt(np.mean(e_krig**2)),
            "mae_idw": np.mean(np.abs(e_idw)), "mae_krig": np.mean(np.abs(e_krig))}


# ---------------------------------------------------------------- 鄉鎮 zonal mean
def zonal(towns, z, transform):
    """先用網格中心落在多邊形內；NaN → all_touched=True；仍 NaN → 鄉鎮重心所在網格。"""
    v = np.array([s["mean"] for s in zonal_stats(towns, z, affine=transform, stats="mean", nodata=-9999)], float)
    flag = np.zeros(len(v), int)
    miss = np.isnan(v)
    if miss.any():
        v2 = np.array([s["mean"] for s in zonal_stats(towns[miss], z, affine=transform, stats="mean",
                                                       nodata=-9999, all_touched=True)], float)
        v[miss], flag[miss] = v2, 1
    miss = np.isnan(v)
    if miss.any():
        c = towns[miss].geometry.centroid
        col = ((c.x - transform.c) / CELL).astype(int)
        row = ((transform.f - c.y) / CELL).astype(int)
        v[miss], flag[miss] = z[row, col], 1
    return v, flag


def plot_town(towns, stn, year):
    fig, ax = plt.subplots(figsize=(6.5, 9))
    towns.plot(ax=ax, column=f"pm25", cmap="YlOrRd", legend=True, edgecolor="grey", linewidth=0.1,
               legend_kwds={"label": "PM2.5 年均 (μg/m³)", "shrink": 0.6})
    ax.scatter(stn["x"], stn["y"], s=8, c="k", marker="^", label=f"測站 n={len(stn)}")
    ax.legend(loc="lower right")
    ax.set_title(f"{year}（民國 {year - 1911} 年）鄉鎮 PM2.5（IDW, p={IDW_POWER}）")
    ax.set_axis_off()
    fig.savefig(QA / f"pm25_town_{year}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    towns = gpd.read_file(INTERIM / "town_master.gpkg", layer="town_master")
    d, log = load_daily()
    st = load_stations()
    ann = station_annual(d, st)
    ann.to_csv(INTERIM / "pm25_station_annual.csv", index=False, encoding="utf-8-sig")

    xs, ys, transform = make_grid(towns)
    out, vgs, cvs = [], [], []
    for y in YEARS:
        stn = ann[(ann["year"] == y) & ann["kept"]]
        z_idw, z_krig, vg = interpolate(stn, xs, ys)
        v_idw, f_idw = zonal(towns, z_idw, transform)
        v_krig, _ = zonal(towns, z_krig, transform)
        out.append(pd.DataFrame({"towncode": towns["towncode"], "year": y, "pm25": v_idw,
                                 "pm25_krig": v_krig, "f_pm25": f_idw}))
        vgs.append({"year": y, "n_stations": len(stn), "model": VARIOGRAM, **vg})
        cvs.append({"year": y, "n_stations": len(stn), **loocv(stn)})
        if y in (2016, 2025):
            plot_town(towns.assign(pm25=v_idw), stn, y)
        print(f"{y}: 測站 {len(stn)}，IDW 鄉鎮 NaN→替代 {int(f_idw.sum())}")

    res = pd.concat(out).sort_values(["towncode", "year"])
    assert len(res) == 349 * 10 and res["pm25"].notna().all()
    res.to_csv(INTERIM / "pm25.csv", index=False, encoding="utf-8-sig")
    vg = pd.DataFrame(vgs)
    vg.to_csv(INTERIM / "pm25_variogram.csv", index=False, encoding="utf-8-sig")
    cv = pd.DataFrame(cvs)
    cv.to_csv(INTERIM / "pm25_loocv.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cv["year"], cv["rmse_idw"], "o-", label="IDW (p=2)")
    ax.plot(cv["year"], cv["rmse_krig"], "s-", label="Ordinary Kriging (spherical)")
    ax.set_ylabel("LOOCV RMSE (μg/m³)"); ax.set_title("PM2.5 測站年均 LOOCV"); ax.legend(); ax.grid(alpha=0.3)
    fig.savefig(QA / "pm25_loocv.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ---- 回報 ----
    print("\n日資料清理：", log)
    print("\n剔除的測站-年：")
    print(ann[~ann["kept"]][["year", "siteid", "sitename", "county", "valid_days", "days_in_year",
                             "pct_valid", "drop_reason"]].round(3).to_string(index=False))
    print("\nVariogram：\n", vg.round(3).to_string(index=False))
    print("\nLOOCV：\n", cv.round(3).to_string(index=False))
    print("\n鄉鎮 PM2.5 摘要：\n", res.groupby("year")[["pm25", "pm25_krig"]].agg(["mean", "min", "max"]).round(1).to_string())
    print("\nf_pm25 = 1 的鄉鎮-年：", int(res["f_pm25"].sum()))
    print("IDW vs Kriging 鄉鎮值相關：", round(res["pm25"].corr(res["pm25_krig"]), 3))


if __name__ == "__main__":
    main()
