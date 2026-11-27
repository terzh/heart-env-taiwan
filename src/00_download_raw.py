"""下載死因統計（縣市及鄉鎮統計表、年報、結果分析）與鄉鎮市區界線。

從 repo 根目錄執行：python src/00_download_raw.py
- 死因：衛福部統計處每年一頁 https://dep.mohw.gov.tw/DOS/lp-5069-113-xCat-y{105..114}.html
- 界線：政府資料開放平臺 dataset 7441（鄉鎮市區界線 TWD97經緯度）
zip 內檔名為 Big5(cp950)，解壓時轉成正確中文檔名。已存在的檔案不重抓。
"""
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0"}
RAW = Path("data/raw")
MORT = RAW / "mortality"
BND = RAW / "boundary"
YEARS = range(105, 115)

# (title 必含的關鍵字, 副檔名) —— 每年要抓的三種檔
WANT = [("縣市及鄉鎮統計表", "zip"), ("年報", "xlsx"), ("結果分析", "pdf")]


def get(url, **kw):
    for i in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=180, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            print(f"  retry {i + 1}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"failed: {url}")


def fix_name(info: zipfile.ZipInfo) -> str:
    """zip 沒有 UTF-8 旗標時，Python 用 cp437 解碼；還原成 bytes 再用 cp950 解。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp950")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def extract(zpath: Path, dest: Path):
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = fix_name(info)
            out = dest / name
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(info))


def download(url, out: Path):
    if out.exists() and out.stat().st_size > 0:
        print(f"  skip (exists) {out}")
        return
    r = get(url)
    out.write_bytes(r.content)
    print(f"  saved {out} ({len(r.content) / 1e6:.1f} MB)")


def mortality():
    MORT.mkdir(parents=True, exist_ok=True)
    missing = []
    for y in YEARS:
        page = get(f"https://dep.mohw.gov.tw/DOS/lp-5069-113-xCat-y{y}.html").text
        links = re.findall(r'<a[^>]*title="([^"]*)"[^>]*href="([^"]+)"|<a[^>]*href="([^"]+)"[^>]*title="([^"]*)"', page)
        pairs = [(t1 or t2, h1 or h2) for t1, h1, h2, t2 in links]
        print(f"{y}:")
        for kw, ext in WANT:
            hit = [(t, h) for t, h in pairs if kw in t and f".{ext}" in t]
            if not hit:
                missing.append((y, kw, ext))
                print(f"  !! not found: {kw} .{ext}")
                continue
            t, h = hit[0]
            out = MORT / f"{y}_{kw}.{ext}"
            download(h, out)
            if ext == "zip":
                extract(out, MORT / f"{y}_{kw}")
    if missing:
        print("\n找不到的檔案：", missing)


def boundary():
    BND.mkdir(parents=True, exist_ok=True)
    meta = get("https://data.gov.tw/api/v2/rest/dataset/7441").json()
    meta = meta.get("result", meta)
    for d in meta["distribution"]:
        if "SHP" in d.get("resourceDescription", "").upper():
            url = d["resourceDownloadUrl"]
            name = url.rsplit("/", 1)[-1]
            out = BND / name
            print(f"boundary: {d['resourceDescription']}")
            download(url, out)
            extract(out, BND / out.stem)


if __name__ == "__main__":
    mortality()
    boundary()
