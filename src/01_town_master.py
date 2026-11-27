"""鄉鎮主表：臺灣本島 349 個鄉鎮市區（EPSG:3826）+ 死因統計中文名稱對照表。

從 repo 根目錄執行：python src/01_town_master.py
輸入：data/raw/boundary/鄉(鎮、市、區)界線1140318/TOWN_MOI_1140318.shp
      data/raw/mortality/{105..114}_縣市及鄉鎮統計表/**/*各鄉鎮市區*.xls（只讀工作表名稱）
輸出：data/interim/town_master.gpkg     towncode, county, town, geometry
        layer town_master：已移除距本島 > 5 km 的島嶼（分析用）
        layer town_master_official：官方完整界線
      data/interim/town_name_lookup.csv  死因表中文名稱 → towncode
      data/interim/excluded_towns.csv     被排除的 19 個離島鄉鎮
      figures/qa/town_master.png
"""
import re
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

warnings.filterwarnings("ignore")
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK TC", "Noto Sans CJK JP", "WenQuanYi Zen Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

SHP = Path("data/raw/boundary/鄉(鎮、市、區)界線1140318/TOWN_MOI_1140318.shp")
MORT = Path("data/raw/mortality")
INTERIM = Path("data/interim")
QA = Path("figures/qa")
N_EXPECTED = 349
ISLAND_KM = 5  # 距本島主體超過此距離的島嶼部分從分析用幾何中移除

OFFSHORE_COUNTIES = ["澎湖縣", "金門縣", "連江縣"]
OFFSHORE_TOWNS = [("屏東縣", "琉球鄉"), ("臺東縣", "綠島鄉"), ("臺東縣", "蘭嶼鄉")]

# 鄉鎮改名（舊名 → 現名），死因表部分年份仍用舊名。只放查證過的升格案例。
RENAMES = {
    ("彰化縣", "員林鎮"): "員林市",  # 104/08/08 升格為縣轄市；106 年死因表仍用舊名
    ("苗栗縣", "頭份鎮"): "頭份市",  # 104/10/05 升格為縣轄市；106 年死因表仍用舊名
}


def norm(s: str) -> str:
    """名稱正規化：去空白、台→臺。只用來比對，不改輸出的正式名稱。"""
    return re.sub(r"\s+", "", str(s)).replace("台", "臺")


def build_master():
    g = gpd.read_file(SHP)
    g = g.rename(columns={"TOWNCODE": "towncode", "COUNTYNAME": "county", "TOWNNAME": "town"})
    g["towncode"] = g["towncode"].astype(str)
    assert g["towncode"].str.len().eq(8).all() and not g["towncode"].duplicated().any()

    off = g["county"].isin(OFFSHORE_COUNTIES) | pd.Series(
        list(zip(g["county"], g["town"])), index=g.index
    ).isin(OFFSHORE_TOWNS)
    excluded = g.loc[off, ["towncode", "county", "town"]].sort_values("towncode")
    main = g.loc[~off, ["towncode", "county", "town", "geometry"]].to_crs(3826)
    main = main.sort_values("towncode").reset_index(drop=True)

    print(f"界線檔鄉鎮數 {len(g)}，排除 {len(excluded)}，本島 {len(main)}")
    if len(main) != N_EXPECTED:
        print(f"!! 本島鄉鎮數 {len(main)} ≠ {N_EXPECTED}，停止。")
        print(excluded.to_string())
        sys.exit(1)
    return main, excluded


def trim_islands(official):
    """去掉距臺灣本島主體 > ISLAND_KM 的島嶼部分（東沙、南沙、釣魚臺、龜山島、彭佳嶼等）。
    這些島無一般戶籍人口，只影響幾何（重心、網格範圍），不影響死亡率資料。"""
    body = max(official.geometry.union_all().geoms, key=lambda p: p.area)
    parts = official.explode(index_parts=True)
    dist_km = parts.geometry.distance(body) / 1000
    dropped = parts[dist_km > ISLAND_KM].assign(dist_km=dist_km[dist_km > ISLAND_KM], area_km2=lambda d: d.area / 1e6)
    kept = parts[dist_km <= ISLAND_KM].dissolve(by="towncode", as_index=False)[["towncode", "geometry"]]
    trimmed = official.drop(columns="geometry").merge(kept, on="towncode")
    trimmed = gpd.GeoDataFrame(trimmed, geometry="geometry", crs=official.crs)
    assert len(trimmed) == len(official)
    summ = dropped.groupby(["towncode", "county", "town"]).agg(
        n_parts=("dist_km", "size"), max_km=("dist_km", "max"), area_km2=("area_km2", "sum")
    ).round(3)
    return trimmed, summ


def mortality_names():
    """從死因鄉鎮表的檔名（縣市）與工作表名（鄉鎮）收集各年的中文名稱。"""
    rows = []
    for y in range(105, 115):
        files = sorted((MORT / f"{y}_縣市及鄉鎮統計表").rglob("*各鄉鎮市區*.xls"))
        if not files:
            print(f"!! {y} 年找不到鄉鎮表")
        for f in files:
            m = re.search(r"\d+年(.+?)各鄉鎮市區", f.name)
            county_raw = m.group(1)
            sheets = pd.ExcelFile(f, engine="xlrd").sheet_names
            towns = [s for s in sheets if s != "目錄" and not s.endswith("2") and norm(s) != norm(county_raw)]
            rows += [{"roc_year": y, "county_raw": county_raw, "town_raw": t, "file": f.name} for t in towns]
    return pd.DataFrame(rows)


def build_lookup(names, master, excluded):
    ref = pd.concat([master.drop(columns="geometry").assign(mainland=1), excluded.assign(mainland=0)])
    ref["key"] = ref["county"].map(norm) + "|" + ref["town"].map(norm)
    renamed = [RENAMES.get((norm(c), norm(t))) for c, t in zip(names["county_raw"], names["town_raw"])]
    town_now = [r or t for r, t in zip(renamed, names["town_raw"])]
    names["key"] = names["county_raw"].map(norm) + "|" + pd.Series(town_now, index=names.index).map(norm)
    lk = names.merge(ref[["key", "towncode", "county", "town", "mainland"]], on="key", how="left")
    lk["match"] = (lk["county_raw"] + lk["town_raw"] == lk["county"] + lk["town"]).map(
        {True: "exact", False: "normalized"}
    )
    lk.loc[[r is not None for r in renamed], "match"] = "renamed"
    lk.loc[lk["towncode"].isna(), "match"] = "UNMATCHED"
    return lk.drop(columns="key")


def plot(master, excluded_n):
    fig, ax = plt.subplots(figsize=(7, 10))
    master.plot(ax=ax, column="county", cmap="tab20", edgecolor="white", linewidth=0.2)
    ax.set_title(
        f"臺灣本島鄉鎮市區 n = {len(master)}（排除離島鄉鎮 {excluded_n}；"
        f"移除距本島 > {ISLAND_KM} km 島嶼）\nEPSG:3826"
    )
    ax.set_axis_off()
    fig.savefig(QA / "town_master.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    INTERIM.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)

    official, excluded = build_master()
    master, islands = trim_islands(official)
    gpkg = INTERIM / "town_master.gpkg"
    gpkg.unlink(missing_ok=True)
    master.to_file(gpkg, driver="GPKG", layer="town_master")  # 分析用（已移除遠方島嶼）
    official.to_file(gpkg, driver="GPKG", layer="town_master_official")  # 官方完整界線
    print(f"\n移除距本島 > {ISLAND_KM} km 的島嶼部分：")
    print(islands.to_string())
    excluded.to_csv(INTERIM / "excluded_towns.csv", index=False, encoding="utf-8-sig")

    names = mortality_names()
    lk = build_lookup(names, master, excluded)
    lk.to_csv(INTERIM / "town_name_lookup.csv", index=False, encoding="utf-8-sig")

    plot(master, len(excluded))

    # ---- 回報 ----
    print("\n被排除的鄉鎮：")
    print(excluded.groupby("county")["town"].apply(lambda s: "、".join(s)).to_string())
    print("\n死因表各年鄉鎮數（全部 / 本島 / 對不到）：")
    summ = lk.groupby("roc_year").agg(
        total=("town_raw", "size"),
        mainland=("mainland", lambda s: (s == 1).sum()),
        unmatched=("match", lambda s: (s == "UNMATCHED").sum()),
    )
    print(summ.to_string())
    print("\n比對方式：", lk["match"].value_counts().to_dict())
    print("正規化後才對上的名稱：")
    print(lk.loc[lk["match"] == "normalized", ["county_raw", "town_raw", "county", "town"]].drop_duplicates().to_string())
    um = lk[lk["match"] == "UNMATCHED"]
    if len(um):
        print("\n!! 對不到的名稱：")
        print(um[["roc_year", "county_raw", "town_raw", "file"]].to_string())
    # 本島 349 個是否每年都出現在死因表
    miss = []
    for y, grp in lk.groupby("roc_year"):
        lost = set(master["towncode"]) - set(grp["towncode"].dropna())
        miss += [(y, c) for c in lost]
    if miss:
        mm = pd.DataFrame(miss, columns=["roc_year", "towncode"]).merge(master.drop(columns="geometry"))
        print("\n!! 本島鄉鎮在死因表找不到工作表：")
        print(mm.to_string())
    dup = lk[lk.duplicated(["roc_year", "towncode"], keep=False) & lk["towncode"].notna()]
    if len(dup):
        print("\n!! 同一年同一 towncode 出現多次：")
        print(dup.to_string())


if __name__ == "__main__":
    main()
