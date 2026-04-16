"""
02_prepare_crosswalk.py
Build PLZ → Gemeinde crosswalk with BBSR and Thünen classifications.

Input:
  - data/raw/plz-suche.csv  (PLZ-Gemeinde mapping)
  - data/raw/bbsr_raumgliederungen_2024.xlsx  (Kreistyp, Kreisregion, Thünen-5-Typ)
  - data/raw/Ländlichkeit_Kreisregionen_2016.xlsx  (continuous Ländlichkeitsindex)

Output:
  - data/interim/plz_gemeinde_crosswalk.parquet
"""

import pathlib

import pandas as pd

RAW = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"
INTERIM = pathlib.Path(__file__).resolve().parent.parent / "data" / "interim"
INTERIM.mkdir(parents=True, exist_ok=True)

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


def show_examples(df: pd.DataFrame, step: str) -> None:
    """Print worked examples for the two test PLZ."""
    print(f"\n--- Worked Examples after: {step} ---")
    for plz in WORKED_EXAMPLES:
        subset = df[df["plz"] == plz]
        if subset.empty:
            print(f"  PLZ {plz}: NOT FOUND")
        else:
            print(f"\n  PLZ {plz} ({len(subset)} Gemeinden):")
            print(subset.to_string(index=False))
    print()


# ---------------------------------------------------------------------------
# 1. Load plz-suche.csv
# ---------------------------------------------------------------------------

def load_plz_suche() -> pd.DataFrame:
    print("[1] Loading plz-suche.csv ...")
    df = pd.read_csv(
        RAW / "plz-suche.csv",
        header=None,
        names=["unknown_id", "ags_raw", "gemeinde_name", "plz", "kreis_name", "bundesland"],
        dtype={"ags_raw": str, "plz": str},
    )
    # Drop rows without AGS (12 dissolved localities without valid municipality code)
    n_before = len(df)
    df = df.dropna(subset=["ags_raw"]).copy()
    n_dropped = n_before - len(df)
    if n_dropped > 0:
        print(f"  Dropped {n_dropped} rows without AGS")

    # Pad AGS to 8 digits (leading zero for states 01-09)
    df["ags"] = df["ags_raw"].str.zfill(8)
    # Derive Kreisschlüssel: first 5 digits of 8-digit AGS
    df["kreisschluessel"] = df["ags"].str[:5]
    # Kreisschlüssel as integer for BBSR join (BBSR stores as int with 000 suffix)
    df["krs_key"] = (df["kreisschluessel"] + "000").astype(int)

    df["plz"] = df["plz"].str.zfill(5)

    print(f"  {len(df)} rows, {df['plz'].nunique()} unique PLZ, {df['ags'].nunique()} unique Gemeinden")
    return df


# ---------------------------------------------------------------------------
# 2. Load BBSR reference table
# ---------------------------------------------------------------------------

def load_bbsr() -> pd.DataFrame:
    print("[2] Loading BBSR Raumgliederungen ...")
    bbsr = pd.read_excel(
        RAW / "bbsr_raumgliederungen_2024.xlsx",
        sheet_name="Kreisreferenz",
        header=0,
        skiprows=[1],
    )
    # Keep relevant columns
    bbsr = bbsr[["KRS2024", "KRS_NAME", "KKR2024", "KTU2024", "TH52024"]].copy()
    bbsr.columns = ["krs_key", "krs_name_bbsr", "kreisregion_key", "bbsr_kreistyp", "thuenen_typ"]

    # Convert to int for safe join
    bbsr["krs_key"] = bbsr["krs_key"].astype(int)
    bbsr["kreisregion_key"] = bbsr["kreisregion_key"].astype(int)
    bbsr["bbsr_kreistyp"] = bbsr["bbsr_kreistyp"].astype(int)
    bbsr["thuenen_typ"] = bbsr["thuenen_typ"].astype(int)

    print(f"  {len(bbsr)} Kreise, {bbsr['kreisregion_key'].nunique()} Kreisregionen")
    return bbsr


# ---------------------------------------------------------------------------
# 3. Load Thünen Ländlichkeitsindex
# ---------------------------------------------------------------------------

def load_thuenen() -> pd.DataFrame:
    print("[3] Loading Thünen Ländlichkeitsindex ...")
    th = pd.read_excel(
        RAW / "Ländlichkeit_Kreisregionen_2016.xlsx",
        sheet_name="Daten Ländlichkeit-2016",
    )
    th = th[["Kennziffer", "Ländlichkeit"]].copy()
    th.columns = ["kreisregion_key", "thuenen_index"]
    th["kreisregion_key"] = th["kreisregion_key"].astype(int)
    print(f"  {len(th)} Kreisregionen, Index range: {th['thuenen_index'].min():.2f} to {th['thuenen_index'].max():.2f}")
    return th


# ---------------------------------------------------------------------------
# 4. Join everything
# ---------------------------------------------------------------------------

def build_crosswalk(plz: pd.DataFrame, bbsr: pd.DataFrame, thuenen: pd.DataFrame) -> pd.DataFrame:
    print("[4] Building crosswalk ...")

    # Join PLZ-Gemeinde with BBSR (via Kreisschlüssel as integer key)
    merged = plz.merge(bbsr, on="krs_key", how="left")
    missing_bbsr = merged["bbsr_kreistyp"].isna().sum()
    if missing_bbsr > 0:
        print(f"  WARNING: {missing_bbsr} rows without BBSR match")

    # Fix Kreisregion mismatch: Kaiserslautern Stadt (7312000) is merged
    # with LK Kaiserslautern (7335000) in the Thünen 2016 typology but
    # listed separately in the BBSR 2024 reference.
    KREISREGION_REMAP = {7312000: 7335000}
    merged["thuenen_kreisregion_key"] = merged["kreisregion_key"].replace(KREISREGION_REMAP)

    # Join with Thünen (via Kreisregion)
    merged = merged.merge(
        thuenen,
        left_on="thuenen_kreisregion_key",
        right_on="kreisregion_key",
        how="left",
        suffixes=("", "_th"),
    )
    merged = merged.drop(columns=["kreisregion_key_th", "thuenen_kreisregion_key"])
    missing_th = merged["thuenen_index"].isna().sum()
    if missing_th > 0:
        print(f"  WARNING: {missing_th} rows without Thünen index match")

    # Add labels
    merged["bbsr_kreistyp_label"] = merged["bbsr_kreistyp"].map(BBSR_LABELS)
    merged["thuenen_typ_label"] = merged["thuenen_typ"].map(THUENEN_LABELS)

    # Select and order output columns
    result = merged[[
        "plz",
        "ags",
        "gemeinde_name",
        "kreisschluessel",
        "kreis_name",
        "bundesland",
        "kreisregion_key",
        "bbsr_kreistyp",
        "bbsr_kreistyp_label",
        "thuenen_typ",
        "thuenen_typ_label",
        "thuenen_index",
    ]].copy()

    print(f"  {len(result)} rows in crosswalk")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("02: Build PLZ-Gemeinde crosswalk with classifications")
    print("=" * 60)

    plz = load_plz_suche()
    show_examples(plz, "load plz-suche.csv")

    bbsr = load_bbsr()
    thuenen = load_thuenen()

    crosswalk = build_crosswalk(plz, bbsr, thuenen)
    show_examples(crosswalk, "join classifications")

    out = INTERIM / "plz_gemeinde_crosswalk.parquet"
    crosswalk.to_parquet(out, index=False)
    print(f"\nOutput: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
