"""
06_sanity_checks.py
Validate the final PLZ reference table.

Checks:
1. Total population vs Zensus 2022 (~82.7 Mio)
2. PLZ count (~8,200)
3. No NaNs in required columns
4. Distribution of BBSR Kreistypen and Thünen-Typen
5. Method conflict rate
6. Worked examples as full rows

Input:
  - data/processed/plz_referenz.parquet
"""

import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
WORKED_EXAMPLES = ["83527", "06333"]

REQUIRED_COLUMNS = [
    "plz", "einwohner", "flaeche_km2",
    "bbsr_kreistyp_dominant", "bbsr_kreistyp_dominant_label", "bbsr_kreistyp_methode_b",
    "thuenen_index_gewichtet", "thuenen_typ_dominant", "thuenen_typ_dominant_label",
    "thuenen_typ_methode_b",
    "dominante_gemeinde_ags", "dominante_gemeinde_name", "dominante_gemeinde_anteil",
    "anzahl_beteiligter_gemeinden", "anzahl_beteiligter_kreise",
    "methoden_konflikt_bbsr", "methoden_konflikt_thuenen",
]


def check(name: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    return passed


def main():
    print("=" * 60)
    print("06: Sanity checks")
    print("=" * 60)

    df = pd.read_parquet(PROCESSED / "plz_referenz.parquet")
    all_passed = True

    # --- 1. Population ---
    print("\n[1] Population check")
    total_pop = df["einwohner"].sum()
    zensus_total = 82_706_456
    pop_coverage = total_pop / zensus_total
    all_passed &= check(
        "Total population",
        0.95 < pop_coverage < 1.05,
        f"{total_pop:,} ({pop_coverage:.1%} of Zensus total {zensus_total:,})"
    )
    all_passed &= check(
        "No negative population",
        (df["einwohner"] >= 0).all(),
    )
    all_passed &= check(
        "No zero-population PLZ with large area",
        not ((df["einwohner"] == 0) & (df["flaeche_km2"] > 10)).any(),
    )

    # --- 2. PLZ count ---
    print("\n[2] PLZ count check")
    n_plz = len(df)
    all_passed &= check(
        "PLZ count in expected range",
        7_500 < n_plz < 8_500,
        f"{n_plz} PLZ (expected ~8,200)"
    )
    all_passed &= check(
        "All PLZ are 5 digits",
        df["plz"].str.match(r"^\d{5}$").all(),
    )
    all_passed &= check(
        "No duplicate PLZ",
        df["plz"].is_unique,
    )

    # --- 3. No NaNs ---
    print("\n[3] Completeness check")
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            all_passed &= check(f"Column exists: {col}", False)
        else:
            n_na = df[col].isna().sum()
            all_passed &= check(f"No NaN: {col}", n_na == 0, f"{n_na} NaN" if n_na > 0 else "")

    # --- 4. Distribution ---
    print("\n[4] Distribution checks")

    print("\n  BBSR Kreistyp (Methode A):")
    bbsr_dist = df["bbsr_kreistyp_dominant"].value_counts().sort_index()
    for typ, count in bbsr_dist.items():
        pct = count / len(df) * 100
        print(f"    Typ {typ}: {count} PLZ ({pct:.1f}%)")

    print("\n  Thünen-Typ (Methode A):")
    th_dist = df["thuenen_typ_dominant"].value_counts().sort_index()
    for typ, count in th_dist.items():
        pct = count / len(df) * 100
        print(f"    Typ {typ}: {count} PLZ ({pct:.1f}%)")

    all_passed &= check(
        "BBSR types in range 1-4",
        df["bbsr_kreistyp_dominant"].between(1, 4).all(),
    )
    all_passed &= check(
        "Thünen types in range 1-5",
        df["thuenen_typ_dominant"].between(1, 5).all(),
    )
    all_passed &= check(
        "Thünen index range plausible",
        df["thuenen_index_gewichtet"].between(-6, 3).all(),
        f"range [{df['thuenen_index_gewichtet'].min():.2f}, {df['thuenen_index_gewichtet'].max():.2f}]"
    )

    # --- 5. Method conflicts ---
    print("\n[5] Method conflict analysis")
    n_conflict_bbsr = df["methoden_konflikt_bbsr"].sum()
    n_conflict_thuenen = df["methoden_konflikt_thuenen"].sum()
    print(f"  BBSR conflicts: {n_conflict_bbsr} ({n_conflict_bbsr/len(df)*100:.1f}%)")
    print(f"  Thünen conflicts: {n_conflict_thuenen} ({n_conflict_thuenen/len(df)*100:.1f}%)")

    if n_conflict_bbsr > 0:
        print("\n  Sample BBSR conflicts:")
        conflicts = df[df["methoden_konflikt_bbsr"]].head(5)
        print(conflicts[["plz", "einwohner", "bbsr_kreistyp_dominant", "bbsr_kreistyp_methode_b",
                         "dominante_gemeinde_anteil", "anzahl_beteiligter_kreise"]].to_string(index=False))

    if n_conflict_thuenen > 0:
        print("\n  Sample Thünen conflicts:")
        conflicts = df[df["methoden_konflikt_thuenen"]].head(5)
        print(conflicts[["plz", "einwohner", "thuenen_typ_dominant", "thuenen_typ_methode_b",
                         "dominante_gemeinde_anteil", "anzahl_beteiligter_kreise"]].to_string(index=False))

    # --- 6. Ambiguity stats ---
    print("\n[6] Ambiguity statistics")
    print(f"  Median dominant Gemeinde share: {df['dominante_gemeinde_anteil'].median():.1%}")
    print(f"  PLZ with single Gemeinde: {(df['anzahl_beteiligter_gemeinden']==1).sum()}")
    print(f"  PLZ with 2+ Kreise: {(df['anzahl_beteiligter_kreise']>=2).sum()}")
    print(f"  PLZ with dominant share < 50%: {(df['dominante_gemeinde_anteil']<0.5).sum()}")

    # --- 7. Worked Examples ---
    print("\n[7] Worked Examples (full rows)")
    for plz in WORKED_EXAMPLES:
        row = df[df["plz"] == plz]
        if row.empty:
            print(f"\n  PLZ {plz}: NOT FOUND")
            all_passed = False
        else:
            print(f"\n  PLZ {plz}:")
            for col in df.columns:
                val = row[col].iloc[0]
                if isinstance(val, float):
                    print(f"    {col}: {val:.4f}")
                else:
                    print(f"    {col}: {val}")

    # --- Summary ---
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
