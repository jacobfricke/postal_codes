"""
04_join_classifications.py
Join BBSR Kreistyp and Thünen classifications to the spatial
population data from script 03.

Uses VG250 AGS → Kreisschlüssel → BBSR/Thünen mapping (not plz-suche.csv),
because the spatial intersection found additional Gemeinden beyond those
listed in plz-suche.csv.

Input:
  - data/interim/plz_gemeinde_population.parquet
  - data/raw/bbsr_raumgliederungen_2024.xlsx
  - data/raw/Ländlichkeit_Kreisregionen_2016.xlsx

Output:
  - data/interim/plz_gemeinde_classified.parquet
"""

import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"

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

# Kaiserslautern Stadt is separate in BBSR 2024 but merged in Thünen 2016
KREISREGION_REMAP = {7312000: 7335000}


def show_examples(df: pd.DataFrame, step: str) -> None:
    print(f"\n--- Worked Examples after: {step} ---")
    for plz in WORKED_EXAMPLES:
        subset = df[df["plz"] == plz]
        if subset.empty:
            print(f"  PLZ {plz}: NOT FOUND")
        else:
            print(f"\n  PLZ {plz} ({len(subset)} rows):")
            cols = [c for c in subset.columns if c != "n_cells"]
            print(subset[cols].to_string(index=False))
    print()


def main():
    print("=" * 60)
    print("04: Join BBSR and Thünen classifications")
    print("=" * 60)

    # Load population data
    print("\n[1] Loading population data ...")
    pop = pd.read_parquet(INTERIM / "plz_gemeinde_population.parquet")
    print(f"  {len(pop)} PLZ-Gemeinde combinations")

    # Load BBSR
    print("\n[2] Loading BBSR classifications ...")
    bbsr = pd.read_excel(
        RAW / "bbsr_raumgliederungen_2024.xlsx",
        sheet_name="Kreisreferenz",
        header=0,
        skiprows=[1],
    )
    bbsr = bbsr[["KRS2024", "KKR2024", "KTU2024", "TH52024"]].copy()
    bbsr.columns = ["krs_key", "kreisregion_key", "bbsr_kreistyp", "thuenen_typ"]
    bbsr = bbsr.astype({"krs_key": int, "kreisregion_key": int, "bbsr_kreistyp": int, "thuenen_typ": int})
    print(f"  {len(bbsr)} Kreise")

    # Load Thünen
    print("\n[3] Loading Thünen Ländlichkeitsindex ...")
    th = pd.read_excel(
        RAW / "Ländlichkeit_Kreisregionen_2016.xlsx",
        sheet_name="Daten Ländlichkeit-2016",
    )
    th = th[["Kennziffer", "Ländlichkeit"]].copy()
    th.columns = ["kreisregion_key", "thuenen_index"]
    th["kreisregion_key"] = th["kreisregion_key"].astype(int)

    # Merge Thünen index into BBSR (via Kreisregion, with remap)
    bbsr["thuenen_kr_key"] = bbsr["kreisregion_key"].replace(KREISREGION_REMAP)
    bbsr = bbsr.merge(th, left_on="thuenen_kr_key", right_on="kreisregion_key", how="left", suffixes=("", "_th"))
    bbsr = bbsr.drop(columns=["kreisregion_key_th", "thuenen_kr_key"])

    # Derive Kreisschlüssel from VG250 AGS (8 digits → first 5 → append 000)
    pop["kreisschluessel"] = pop["ags"].str[:5]
    pop["krs_key"] = (pop["kreisschluessel"] + "000").astype(int)

    # Join
    print("\n[4] Joining classifications ...")
    merged = pop.merge(bbsr, on="krs_key", how="left")

    missing = merged["bbsr_kreistyp"].isna().sum()
    if missing > 0:
        print(f"  WARNING: {missing} rows without BBSR match")
        print(merged[merged["bbsr_kreistyp"].isna()][["plz", "ags", "gemeinde_name_vg250"]].head())

    # Add labels
    merged["bbsr_kreistyp_label"] = merged["bbsr_kreistyp"].map(BBSR_LABELS)
    merged["thuenen_typ_label"] = merged["thuenen_typ"].map(THUENEN_LABELS)

    # Select output columns
    result = merged[[
        "plz", "ags", "gemeinde_name_vg250", "kreisschluessel",
        "einwohner", "flaeche_km2",
        "kreisregion_key", "bbsr_kreistyp", "bbsr_kreistyp_label",
        "thuenen_typ", "thuenen_typ_label", "thuenen_index",
    ]].copy()

    print(f"  {len(result)} rows")
    show_examples(result, "join classifications")

    out = INTERIM / "plz_gemeinde_classified.parquet"
    result.to_parquet(out, index=False)
    print(f"Output: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
