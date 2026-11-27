"""把鄉鎮主表轉成 GEE 可上傳的 Shapefile zip（EPSG:4326）。

從 repo 根目錄執行：python src/04_gee_prep.py
輸入：data/interim/town_master.gpkg（layer town_master，已移除遠方島嶼）
輸出：data/interim/gee_upload/town_master_4326.zip（.shp/.shx/.dbf/.prj/.cpg）
上傳到 GEE 後，在 gee/export_tmean_ndvi.js 最上面填 asset 路徑。
"""
import zipfile
from pathlib import Path

import geopandas as gpd

INTERIM = Path("data/interim")
OUT = INTERIM / "gee_upload"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    g = gpd.read_file(INTERIM / "town_master.gpkg", layer="town_master")[["towncode", "geometry"]]
    g["towncode"] = g["towncode"].astype(str)  # 字串欄位，保留 8 碼
    g = g.to_crs(4326)
    assert len(g) == 349
    shp = OUT / "town_master_4326.shp"
    g.to_file(shp, driver="ESRI Shapefile", encoding="UTF-8")
    zpath = OUT / "town_master_4326.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for ext in ["shp", "shx", "dbf", "prj", "cpg"]:
            f = shp.with_suffix(f".{ext}")
            if f.exists():
                z.write(f, f.name)
    print(f"{zpath}  ({zpath.stat().st_size / 1e6:.1f} MB, {len(g)} 鄉鎮, EPSG:4326)")


if __name__ == "__main__":
    main()
