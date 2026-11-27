"""下載環境部空氣品質測站 PM2.5 日平均值（2016–2025）與測站基本資料。

從 repo 根目錄執行：python src/00_download_pm25.py
需要環境變數 MOENV_API_KEY（不要寫進任何檔案）：
    source ~/.moenv_key && python src/00_download_pm25.py

資料集：
- aqx_p_19  空氣品質監測日平均值（一般污染物），篩 itemengname = PM2.5
- aqx_p_07  空氣品質監測站基本資料（站名、經緯度 TWD97、測站類型）
每個月存一個 csv 到 data/raw/pm25/daily/，已存在的月份不重抓。
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

KEY = os.environ.get("MOENV_API_KEY")
if not KEY:
    sys.exit("請先 source ~/.moenv_key 設定 MOENV_API_KEY")

BASE = "https://data.moenv.gov.tw/api/v2/"
OUT = Path("data/raw/pm25")
DAILY = OUT / "daily"
LIMIT = 1000


def fetch(dataset, filters=None):
    rows, offset = [], 0
    while True:
        params = {"api_key": KEY, "format": "json", "limit": LIMIT, "offset": offset}
        if filters:
            params["filters"] = filters
        for i in range(5):
            try:
                r = requests.get(BASE + dataset, params=params, timeout=180)
                r.raise_for_status()
                page = r.json()
                break
            except (requests.RequestException, ValueError) as e:
                print(f"  retry {i + 1}: {type(e).__name__}", file=sys.stderr)
                time.sleep(5 * (i + 1))
        else:
            raise RuntimeError(f"failed {dataset} offset={offset}")
        if not isinstance(page, list):
            raise RuntimeError(f"unexpected response: {str(page)[:200]}")
        rows += page
        if len(page) < LIMIT:
            return rows
        offset += LIMIT


def main():
    DAILY.mkdir(parents=True, exist_ok=True)
    st = pd.DataFrame(fetch("aqx_p_07"))
    st.to_csv(OUT / "stations_aqx_p_07.csv", index=False, encoding="utf-8-sig")
    print(f"stations: {len(st)}")

    for month in pd.period_range("2016-01", "2025-12", freq="M"):
        out = DAILY / f"pm25_daily_{month}.csv"
        if out.exists():
            continue
        start = month.start_time.strftime("%Y-%m-%d")
        end = (month + 1).start_time.strftime("%Y-%m-%d")
        rows = fetch("aqx_p_19", f"itemengname,EQ,PM2.5|monitordate,GR,{start}|monitordate,LT,{end}")
        df = pd.DataFrame(rows)
        # GR 是否含當天不確定，若第一天沒抓到就單獨補抓
        if df.empty or start not in set(df["monitordate"]):
            df = pd.concat([pd.DataFrame(fetch("aqx_p_19", f"itemengname,EQ,PM2.5|monitordate,EQ,{start}")), df])
        df = df.drop_duplicates()
        df.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"{month}: {len(df)} rows, {df['siteid'].nunique()} sites, {df['monitordate'].nunique()} days")


if __name__ == "__main__":
    main()
