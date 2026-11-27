"""心臟疾病（高血壓性疾病除外）死亡資料：105–114 年 × 本島 349 鄉鎮。

從 repo 根目錄執行：python src/02_mortality.py
輸入：data/raw/mortality/{年}_縣市及鄉鎮統計表/**/*各鄉鎮市區*.xls（每鄉鎮一張「主要死亡原因」工作表）
      data/interim/town_name_lookup.csv（01_town_master.py 產出）
輸出：data/interim/mortality.csv
      docs/mortality_masked.csv（被遮蔽「*」的鄉鎮-年與原始符號）

欄位處理：
- deaths     原發布死亡人數（不乘轉換比值）
- pop        年中人口（取自工作表附註「年中人口數計 N 人」）
- asmr_raw   原發布標準化死亡率（每十萬人口）
- asmr_adj   105–107 年 = asmr_raw × 0.9162（全國轉換比值），108–114 年 = asmr_raw
- asmr_heart = asmr_adj（主要分析變數）
- cmr_heart  粗死亡率 = deaths / pop × 1e5（自行計算、未轉換，112 年起遮蔽的鄉鎮也有值）
- cmr_adj    105–107 年 = cmr_heart × 0.9104（全國粗死亡率轉換比值），108–114 年 = cmr_heart
- rule_chg   死因選取準則：105–107 = 0（舊準則），108–114 = 1（WHO 2016 版）
- f_asmr     0 正常；2 = asmr 被遮蔽（112 年起死亡數 < 20 以「*」呈現）→ NaN
- 心臟疾病不在死因表、且表列死因 < 15 個（代表有死亡的死因已全部列出）→ deaths = 0、asmr = 0，f_asmr = 0
"""
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

MORT = Path("data/raw/mortality")
INTERIM = Path("data/interim")
DOCS = Path("docs")

HEART = "心臟疾病（高血壓性疾病除外）"
HEART_ICD = "I01-I02.0, I05-I09, I20-I25, I27, I30-I52"
# 衛福部 108 年起死因統計結果分析附表 1：心臟疾病（高血壓性疾病除外）全國轉換比值（適用 97–107 年原發布數）
RATIO_ASMR = 0.9162
RATIO_CMR = 0.9104  # 死亡人數與粗死亡率同一比值（108–114 年 7 份結果分析附表 1 皆同）
RULE_CHANGE_YEAR = 108
TOP_N = 15

# 合計欄位置（10 年表頭一致，執行時仍逐表檢查）
C_RANK, C_ICD, C_CAUSE, C_DEATHS, C_CMR, C_ASMR = 0, 1, 2, 3, 4, 5
EXPECTED_HEADER = ["順", "ICD-10", "合計", "死亡", "每十萬人口", "標準化"]

# 全國心臟疾病死亡人數（結果分析附表 1；105 為原發布數，108–114 為新準則），用來核對加總
NATIONAL_DEATHS = {105: 20812, 108: 19859, 109: 20457, 110: 21852, 111: 23668, 112: 23424, 113: 23276, 114: 22907}


def clean(v) -> str:
    return re.sub(r"\s+", "", "" if pd.isna(v) else str(v))


def check_header(df, where):
    head = "".join(clean(v) for v in df.iloc[4:7, :7].values.ravel())
    missing = [h for h in EXPECTED_HEADER if h not in head]
    if missing:
        raise ValueError(f"{where} 表頭不符，缺 {missing}")


def parse_sheet(df, where):
    check_header(df, where)
    body = df.iloc[7:]
    causes = body[C_CAUSE].map(clean)
    deaths_col = pd.to_numeric(body[C_DEATHS], errors="coerce")
    n_causes = int(deaths_col.notna().sum())

    m = re.search(r"年中人口數計\s*([\d,]+)\s*人", " ".join(df[0].map(clean)))
    if not m:
        raise ValueError(f"{where} 找不到年中人口")
    out = {"pop": int(m.group(1).replace(",", "")), "n_causes": n_causes}

    hit = body[causes == HEART]
    if len(hit) > 1:
        raise ValueError(f"{where} 心臟疾病出現 {len(hit)} 列")
    if len(hit) == 1:
        r = hit.iloc[0]
        if clean(r[C_ICD]) != clean(HEART_ICD):
            raise ValueError(f"{where} ICD 不符：{r[C_ICD]}")
        out.update(
            deaths=float(r[C_DEATHS]),
            asmr_sym=clean(r[C_ASMR]),
            asmr_raw=pd.to_numeric(r[C_ASMR], errors="coerce"),
            status="listed",
        )
    elif n_causes < TOP_N:
        # 表列死因不足 15 個 → 所有有死亡的死因都已列出 → 心臟疾病死亡數為 0
        out.update(deaths=0.0, asmr_sym="(not listed)", asmr_raw=0.0, status="zero_inferred")
    else:
        out.update(deaths=np.nan, asmr_sym="(not in top 15)", asmr_raw=np.nan, status="not_in_top15")
    return out


def main():
    lk = pd.read_csv(INTERIM / "town_name_lookup.csv", dtype={"towncode": str})
    files = {f.name: f for f in MORT.rglob("*各鄉鎮市區*.xls")}

    rows = []
    for fname, grp in lk.groupby("file"):
        sheets = pd.read_excel(files[fname], sheet_name=None, header=None, engine="xlrd")
        for r in grp.itertuples():
            rec = parse_sheet(sheets[r.town_raw], f"{fname}/{r.town_raw}")
            rows.append({"towncode": r.towncode, "roc_year": r.roc_year, "mainland": r.mainland,
                         "county": r.county, "town": r.town, **rec})
    allt = pd.DataFrame(rows)

    # ---- 核對：368 鄉鎮死亡數加總 vs 全國公布值 ----
    print("全國核對（368 鄉鎮加總 vs 結果分析附表 1）：")
    tot = allt.groupby("roc_year")["deaths"].sum()
    for y, n in NATIONAL_DEATHS.items():
        print(f"  {y}: 加總 {tot[y]:,.0f}  公布 {n:,}  差 {tot[y] - n:+,.0f}")

    d = allt[allt["mainland"] == 1].copy()
    d["year"] = d["roc_year"] + 1911
    d["asmr_adj"] = np.where(d["roc_year"] < RULE_CHANGE_YEAR, d["asmr_raw"] * RATIO_ASMR, d["asmr_raw"])
    d["asmr_heart"] = d["asmr_adj"]
    d["cmr_heart"] = d["deaths"] / d["pop"] * 1e5
    d["cmr_adj"] = np.where(d["roc_year"] < RULE_CHANGE_YEAR, d["cmr_heart"] * RATIO_CMR, d["cmr_heart"])
    d["rule_chg"] = (d["roc_year"] >= RULE_CHANGE_YEAR).astype(int)
    d["f_asmr"] = np.where(d["asmr_heart"].isna(), 2, 0)
    d["deaths"] = d["deaths"].astype("Int64")

    cols = ["towncode", "year", "roc_year", "asmr_heart", "asmr_raw", "asmr_adj", "deaths", "pop",
            "cmr_heart", "cmr_adj", "rule_chg", "f_asmr"]
    out = d.sort_values(["towncode", "year"])[cols]
    assert len(out) == 349 * 10 and not out.duplicated(["towncode", "year"]).any()
    out.to_csv(INTERIM / "mortality.csv", index=False, encoding="utf-8-sig")

    masked = d[d["f_asmr"] == 2][["towncode", "county", "town", "roc_year", "deaths", "pop", "asmr_sym", "status"]]
    masked.sort_values(["roc_year", "towncode"]).to_csv(DOCS / "mortality_masked.csv", index=False, encoding="utf-8-sig")

    # ---- 回報 ----
    print(f"\n輸出 {len(out)} 列 → data/interim/mortality.csv")
    print("\n各年 f_asmr 與狀態：")
    print(pd.crosstab(d["roc_year"], [d["status"], d["f_asmr"]]).to_string())
    print("\n被遮蔽的原始符號：", masked["asmr_sym"].value_counts().to_dict())
    print("\n推斷為 0 的鄉鎮-年：")
    print(d[d["status"] == "zero_inferred"][["towncode", "county", "town", "roc_year", "pop", "n_causes"]].to_string())
    print("\n數值摘要：")
    print(out[["asmr_heart", "asmr_raw", "deaths", "pop", "cmr_heart"]].describe().round(1).to_string())
    print("\n各年全國平均（本島鄉鎮簡單平均）：")
    print(out.groupby("roc_year")[["asmr_raw", "asmr_heart", "cmr_heart", "cmr_adj", "rule_chg"]].mean().round(1).to_string())
    print("\ndeaths < 5 的鄉鎮-年：", int((out["deaths"] < 5).sum()), "；deaths < 20：", int((out["deaths"] < 20).sum()))


if __name__ == "__main__":
    main()
