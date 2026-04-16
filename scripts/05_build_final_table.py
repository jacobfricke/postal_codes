"""
05_build_final_table.py
Aggregate PLZ-Gemeinde data to one row per PLZ with both methods.

Methode A (population-weighted):
  - thuenen_index_gewichtet: population-weighted mean of Thünen index
  - bbsr_kreistyp_dominant / thuenen_typ_dominant: classification of the
    Gemeinde with the largest population share in the PLZ

Methode B (dominant municipality):
  - Assign the entire PLZ to its dominant Gemeinde, use that Gemeinde's
    classifications directly

Input:
  - data/interim/plz_gemeinde_classified.parquet

Output:
  - data/processed/plz_referenz.parquet
  - data/processed/plz_referenz.csv
"""

import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

WORKED_EXAMPLES = ["83527", "06333"]

BBSR_LABELS = {
    1: "Kreisfreie Großstadt",
    2: "Städtischer Kreis",
    3: "Ländlicher Kreis mit Verdichtungsansätzen",
    4: "Dünn besiedelter ländlicher Kreis",
}

THUENEN_LABELS = {
    1: "sehr ländlich / weniger gute sozioökonomische Lage",
    2: "sehr ländlich / gute sozioökonomische Lage",
    3: "eher ländlich / weniger gute sozioökonomische Lage",
    4: "eher ländlich / gute sozioökonomische Lage",
    5: "nicht ländlich",
}


def main():
    print("=" * 60)
    print("05: Build final PLZ reference table")
    print("=" * 60)

    print("\n[1] Loading classified PLZ-Gemeinde data ...")
    df = pd.read_parquet(INTERIM / "plz_gemeinde_classified.parquet")
    print(f"  {len(df)} rows, {df['plz'].nunique()} unique PLZ")

    # ----- Per-PLZ population total and area -----
    plz_totals = df.groupby("plz").agg(
        einwohner=("einwohner", "sum"),
        flaeche_km2=("flaeche_km2", "first"),
    ).reset_index()

    # ----- Dominant Gemeinde per PLZ (largest population share) -----
    print("\n[2] Finding dominant Gemeinde per PLZ ...")
    idx_dominant = df.groupby("plz")["einwohner"].idxmax()
    dominant = df.loc[idx_dominant].copy()
    dominant["plz_einwohner"] = dominant["plz"].map(plz_totals.set_index("plz")["einwohner"])
    dominant["dominante_gemeinde_anteil"] = dominant["einwohner"] / dominant["plz_einwohner"]

    # ----- Methode A: population-weighted Thünen index -----
    print("\n[3] Computing population-weighted Thünen index ...")
    df_with_total = df.merge(plz_totals[["plz", "einwohner"]], on="plz", suffixes=("", "_plz"))
    df_with_total["weight"] = df_with_total["einwohner"] / df_with_total["einwohner_plz"]
    df_with_total["weighted_index"] = df_with_total["weight"] * df_with_total["thuenen_index"]
    thuenen_weighted = df_with_total.groupby("plz")["weighted_index"].sum().reset_index()
    thuenen_weighted.columns = ["plz", "thuenen_index_gewichtet"]

    # ----- Ambiguity metrics -----
    print("\n[4] Computing ambiguity metrics ...")
    gemeinde_counts = df.groupby("plz")["ags"].nunique().reset_index()
    gemeinde_counts.columns = ["plz", "anzahl_beteiligter_gemeinden"]

    kreis_counts = df.groupby("plz")["kreisschluessel"].nunique().reset_index()
    kreis_counts.columns = ["plz", "anzahl_beteiligter_kreise"]

    # ----- Methode A: dominant CATEGORY by population -----
    # For BBSR: aggregate population by (PLZ, Kreistyp), pick type with most people
    # For Thünen: aggregate population by (PLZ, Kreisregion/Typ), pick type with most people
    # This can differ from Methode B when multiple small Gemeinden of one type
    # together outweigh the single dominant Gemeinde of another type.
    print("\n[4a] Methode A: dominant category by population share ...")
    bbsr_by_type = df.groupby(["plz", "bbsr_kreistyp"])["einwohner"].sum().reset_index()
    idx_bbsr_dom = bbsr_by_type.groupby("plz")["einwohner"].idxmax()
    bbsr_dominant = bbsr_by_type.loc[idx_bbsr_dom, ["plz", "bbsr_kreistyp"]].copy()
    bbsr_dominant.columns = ["plz", "bbsr_kreistyp_dominant"]

    thuenen_by_type = df.groupby(["plz", "thuenen_typ"])["einwohner"].sum().reset_index()
    idx_th_dom = thuenen_by_type.groupby("plz")["einwohner"].idxmax()
    thuenen_dominant = thuenen_by_type.loc[idx_th_dom, ["plz", "thuenen_typ"]].copy()
    thuenen_dominant.columns = ["plz", "thuenen_typ_dominant"]

    # ----- Methode B: dominant Gemeinde's classifications -----
    print("    Methode B: dominant Gemeinde's classifications ...")
    methode_b = dominant[[
        "plz", "bbsr_kreistyp", "thuenen_typ",
    ]].copy()
    methode_b.columns = ["plz", "bbsr_kreistyp_methode_b", "thuenen_typ_methode_b"]

    # ----- Assemble final table -----
    print("\n[5] Assembling final table ...")
    final = plz_totals.copy()

    # Dominant Gemeinde info
    dom_info = dominant[[
        "plz", "ags", "gemeinde_name_vg250", "dominante_gemeinde_anteil",
    ]].copy()
    dom_info.columns = [
        "plz", "dominante_gemeinde_ags", "dominante_gemeinde_name", "dominante_gemeinde_anteil",
    ]

    final = final.merge(dom_info, on="plz")
    final = final.merge(bbsr_dominant, on="plz")
    final = final.merge(thuenen_weighted, on="plz")
    final = final.merge(thuenen_dominant, on="plz")
    final = final.merge(methode_b, on="plz")
    final = final.merge(gemeinde_counts, on="plz")
    final = final.merge(kreis_counts, on="plz")

    # Add labels
    final["bbsr_kreistyp_dominant_label"] = final["bbsr_kreistyp_dominant"].map(BBSR_LABELS)
    final["thuenen_typ_dominant_label"] = final["thuenen_typ_dominant"].map(THUENEN_LABELS)

    # Method conflict flags
    final["methoden_konflikt_bbsr"] = (
        final["bbsr_kreistyp_dominant"] != final["bbsr_kreistyp_methode_b"]
    )
    final["methoden_konflikt_thuenen"] = (
        final["thuenen_typ_dominant"] != final["thuenen_typ_methode_b"]
    )

    # Cast types
    final["einwohner"] = final["einwohner"].astype(int)
    final["bbsr_kreistyp_dominant"] = final["bbsr_kreistyp_dominant"].astype(int)
    final["bbsr_kreistyp_methode_b"] = final["bbsr_kreistyp_methode_b"].astype(int)
    final["thuenen_typ_dominant"] = final["thuenen_typ_dominant"].astype(int)
    final["thuenen_typ_methode_b"] = final["thuenen_typ_methode_b"].astype(int)

    # Order columns according to spec
    final = final[[
        "plz",
        "einwohner",
        "flaeche_km2",
        "bbsr_kreistyp_dominant",
        "bbsr_kreistyp_dominant_label",
        "bbsr_kreistyp_methode_b",
        "thuenen_index_gewichtet",
        "thuenen_typ_dominant",
        "thuenen_typ_dominant_label",
        "thuenen_typ_methode_b",
        "dominante_gemeinde_ags",
        "dominante_gemeinde_name",
        "dominante_gemeinde_anteil",
        "anzahl_beteiligter_gemeinden",
        "anzahl_beteiligter_kreise",
        "methoden_konflikt_bbsr",
        "methoden_konflikt_thuenen",
    ]].sort_values("plz").reset_index(drop=True)

    print(f"  {len(final)} rows")

    # ----- Worked Examples -----
    print("\n--- Final table: Worked Examples ---")
    for plz in WORKED_EXAMPLES:
        row = final[final["plz"] == plz]
        if row.empty:
            print(f"\n  PLZ {plz}: NOT FOUND")
        else:
            print(f"\n  PLZ {plz}:")
            for col in final.columns:
                val = row[col].iloc[0]
                print(f"    {col}: {val}")

    # ----- Save -----
    out_pq = PROCESSED / "plz_referenz.parquet"
    out_csv = PROCESSED / "plz_referenz.csv"
    final.to_parquet(out_pq, index=False)
    final.to_csv(out_csv, index=False)
    print(f"\nOutput: {out_pq} ({out_pq.stat().st_size / 1e6:.1f} MB)")
    print(f"Output: {out_csv} ({out_csv.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
