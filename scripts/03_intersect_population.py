"""
03_intersect_population.py
Assign Zensus 2022 grid population to PLZ-Gemeinde combinations.

Approach: assign each 1km grid cell midpoint to its PLZ and Gemeinde via
spatial join, then aggregate population by (PLZ, AGS).

For small PLZ where no 1km midpoint falls inside (typically inner-city PLZ
under ~2 km²), a fallback to the 100m grid is used automatically.

For PLZ that exist in plz-suche.csv but have no polygon (12 dissolved
Thuringian localities), a crosswalk-based fallback assigns them to their
Kreis using the nearest matching municipality.

Input:
  - data/raw/plz_polygone.geojson
  - data/raw/vg250/.../DE_VG250.gpkg (layer vg250_gem)
  - data/raw/zensus2022_gitter/Zensus2022_Bevoelkerungszahl_1km-Gitter.csv
  - data/raw/zensus2022_gitter/Zensus2022_Bevoelkerungszahl_100m-Gitter.csv
  - data/raw/plz-suche.csv

Output:
  - data/interim/plz_gemeinde_population.parquet
"""

import pathlib

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
INTERIM.mkdir(parents=True, exist_ok=True)

TARGET_CRS = "EPSG:25832"
WORKED_EXAMPLES = ["83527", "06333"]


def show_examples(df: pd.DataFrame, step: str) -> None:
    print(f"\n--- Worked Examples after: {step} ---")
    for plz in WORKED_EXAMPLES:
        subset = df[df["plz"] == plz]
        if subset.empty:
            print(f"  PLZ {plz}: NOT FOUND")
        else:
            print(f"\n  PLZ {plz} ({len(subset)} rows):")
            print(subset.to_string(index=False))
    print()


# ---------------------------------------------------------------------------
# Load functions
# ---------------------------------------------------------------------------

def load_zensus_1km() -> gpd.GeoDataFrame:
    print("[1] Loading Zensus 2022 1km grid ...")
    csv_path = RAW / "zensus2022_gitter" / "Zensus2022_Bevoelkerungszahl_1km-Gitter.csv"
    df = pd.read_csv(csv_path, sep=";")
    print(f"  {len(df)} grid cells, {df['Einwohner'].sum():,.0f} total population")

    geometry = [Point(x, y) for x, y in zip(df["x_mp_1km"], df["y_mp_1km"])]
    gdf = gpd.GeoDataFrame(
        df[["GITTER_ID_1km", "Einwohner"]],
        geometry=geometry,
        crs="EPSG:3035",
    )
    gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def load_zensus_100m() -> gpd.GeoDataFrame:
    print("\n[fallback] Loading Zensus 2022 100m grid ...")
    csv_path = RAW / "zensus2022_gitter" / "Zensus2022_Bevoelkerungszahl_100m-Gitter.csv"
    df = pd.read_csv(csv_path, sep=";")
    print(f"  {len(df)} grid cells, {df['Einwohner'].sum():,.0f} total population")

    geometry = [Point(x, y) for x, y in zip(df["x_mp_100m"], df["y_mp_100m"])]
    gdf = gpd.GeoDataFrame(
        df[["GITTER_ID_100m", "Einwohner"]],
        geometry=geometry,
        crs="EPSG:3035",
    )
    gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def load_plz_polygons() -> gpd.GeoDataFrame:
    print("\n[2] Loading PLZ polygons ...")
    gdf = gpd.read_file(RAW / "plz_polygone.geojson")
    print(f"  {len(gdf)} PLZ polygons, CRS={gdf.crs}")

    gdf = gdf.rename(columns={"qkm": "flaeche_km2"})
    gdf["plz"] = gdf["plz"].astype(str).str.zfill(5)

    gdf = gdf.to_crs(TARGET_CRS)
    return gdf[["plz", "flaeche_km2", "geometry"]]


def load_vg250_gem() -> gpd.GeoDataFrame:
    print("\n[3] Loading VG250 Gemeindegrenzen ...")
    gpkg_path = RAW / "vg250" / "vg250_01-01.utm32s.gpkg.ebenen" / "vg250_ebenen_0101" / "DE_VG250.gpkg"
    gdf = gpd.read_file(gpkg_path, layer="vg250_gem")
    gdf = gdf[gdf["GF"] == 4].copy()
    print(f"  {len(gdf)} Gemeinden (GF=4)")

    gdf = gdf.rename(columns={"AGS": "ags_vg250", "GEN": "gemeinde_name_vg250"})
    return gdf[["ags_vg250", "gemeinde_name_vg250", "geometry"]]


def load_plz_suche_target() -> set:
    """All unique PLZ from plz-suche.csv, our canonical PLZ list."""
    df = pd.read_csv(
        RAW / "plz-suche.csv", header=None,
        names=["id", "ags", "name", "plz", "kreis", "land"],
        dtype={"plz": str},
    )
    df["plz"] = df["plz"].str.zfill(5)
    return set(df["plz"].unique())


# ---------------------------------------------------------------------------
# Spatial join helper
# ---------------------------------------------------------------------------

def sjoin_grid_to_plz_gem(
    points: gpd.GeoDataFrame,
    plz_poly: gpd.GeoDataFrame,
    gem_poly: gpd.GeoDataFrame,
    id_col: str,
) -> pd.DataFrame:
    """Spatial-join grid points to PLZ and Gemeinde, aggregate by (PLZ, AGS)."""
    joined_plz = gpd.sjoin(points, plz_poly, how="inner", predicate="within")
    joined_gem = gpd.sjoin(points, gem_poly, how="inner", predicate="within")

    plz_assign = joined_plz[[id_col, "Einwohner", "plz", "flaeche_km2"]].copy()
    gem_assign = joined_gem[[id_col, "ags_vg250", "gemeinde_name_vg250"]].copy()

    merged = plz_assign.merge(gem_assign, on=id_col, how="inner")

    agg = (
        merged
        .groupby(["plz", "ags_vg250", "gemeinde_name_vg250"])
        .agg(einwohner=("Einwohner", "sum"), n_cells=(id_col, "count"))
        .reset_index()
    )
    plz_area = merged.groupby("plz")["flaeche_km2"].first().reset_index()
    agg = agg.merge(plz_area, on="plz", how="left")
    return agg


# ---------------------------------------------------------------------------
# Fallback for PLZ without polygons
# ---------------------------------------------------------------------------

def fallback_no_polygon(
    missing_plz: set,
    gem_poly: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """For PLZ in plz-suche.csv that have no polygon, assign them to a
    Gemeinde via the crosswalk. These are 12 dissolved Thuringian localities
    without AGS. We find another PLZ in the same Kreis and use its
    Gemeinde as a proxy."""
    print(f"\n[fallback] {len(missing_plz)} PLZ without polygons, using crosswalk ...")
    df = pd.read_csv(
        RAW / "plz-suche.csv", header=None,
        names=["id", "ags_raw", "name", "plz", "kreis", "land"],
        dtype={"ags_raw": str, "plz": str},
    )
    df["plz"] = df["plz"].str.zfill(5)

    rows = []
    for plz in sorted(missing_plz):
        plz_rows = df[df["plz"] == plz]
        kreis = plz_rows["kreis"].iloc[0]
        land = plz_rows["land"].iloc[0]

        # Find a PLZ in the same Kreis that has a valid AGS.
        # If Kreis is NaN, fall back to matching by PLZ prefix (same city)
        # then by Bundesland.
        same_kreis = df[(df["kreis"] == kreis) & df["ags_raw"].notna()] if pd.notna(kreis) else pd.DataFrame()
        if same_kreis.empty:
            plz_prefix = plz[:3]
            same_kreis = df[(df["plz"].str[:3] == plz_prefix) & df["ags_raw"].notna()]
        if same_kreis.empty:
            same_kreis = df[(df["land"] == land) & df["ags_raw"].notna()]
        if same_kreis.empty:
            print(f"  WARNING: No proxy found for PLZ {plz}, skipping")
            continue

        proxy_ags = same_kreis["ags_raw"].iloc[0].zfill(8)
        proxy_name_match = gem_poly[gem_poly["ags_vg250"] == proxy_ags]
        if proxy_name_match.empty:
            proxy_name = same_kreis["name"].iloc[0]
        else:
            proxy_name = proxy_name_match["gemeinde_name_vg250"].iloc[0]

        rows.append({
            "plz": plz,
            "ags_vg250": proxy_ags,
            "gemeinde_name_vg250": proxy_name,
            "einwohner": 0,
            "n_cells": 0,
            "flaeche_km2": 0.0,
        })
        print(f"  {plz} ({plz_rows['name'].iloc[0]}) → proxy AGS {proxy_ags} ({proxy_name}) via Kreis '{kreis}'")

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("03: Spatial intersection and population assignment")
    print("=" * 60)

    target_plz = load_plz_suche_target()
    print(f"\nTarget: {len(target_plz)} unique PLZ from plz-suche.csv")

    points_1km = load_zensus_1km()
    plz_poly = load_plz_polygons()
    gem_poly = load_vg250_gem()

    # --- Pass 1: 1km grid ---
    print("\n[4] Pass 1: 1km grid spatial join ...")
    result_1km = sjoin_grid_to_plz_gem(points_1km, plz_poly, gem_poly, "GITTER_ID_1km")
    matched_plz = set(result_1km["plz"].unique())
    print(f"  {len(result_1km)} PLZ-Gemeinde combinations, {len(matched_plz)} unique PLZ")

    # --- Pass 2: 100m grid for PLZ with polygons but no 1km match ---
    poly_plz = set(plz_poly["plz"].unique())
    missing_with_poly = poly_plz - matched_plz
    print(f"\n  PLZ with polygons but no 1km match: {len(missing_with_poly)}")

    result_100m = pd.DataFrame()
    if missing_with_poly:
        points_100m = load_zensus_100m()
        plz_poly_missing = plz_poly[plz_poly["plz"].isin(missing_with_poly)]
        print(f"  Running 100m grid spatial join for {len(plz_poly_missing)} PLZ ...")
        result_100m = sjoin_grid_to_plz_gem(points_100m, plz_poly_missing, gem_poly, "GITTER_ID_100m")
        recovered = set(result_100m["plz"].unique())
        still_missing = missing_with_poly - recovered
        print(f"  Recovered {len(recovered)} PLZ via 100m grid")
        if still_missing:
            print(f"  Still missing after 100m fallback: {sorted(still_missing)}")
        del points_100m  # free memory

    # --- Pass 3: PLZ without polygons (crosswalk fallback) ---
    all_matched = matched_plz | set(result_100m["plz"].unique()) if len(result_100m) else matched_plz
    missing_no_poly = target_plz - all_matched
    result_nopoly = pd.DataFrame()
    if missing_no_poly:
        result_nopoly = fallback_no_polygon(missing_no_poly, gem_poly)
        all_matched = all_matched | set(result_nopoly["plz"].unique()) if len(result_nopoly) else all_matched

    # --- Combine ---
    parts = [result_1km]
    if len(result_100m):
        parts.append(result_100m)
    if len(result_nopoly):
        parts.append(result_nopoly)
    result = pd.concat(parts, ignore_index=True)

    result = result.rename(columns={"ags_vg250": "ags"})

    final_count = result["plz"].nunique()
    still_missing = target_plz - set(result["plz"].unique())
    print(f"\n  Final: {len(result)} PLZ-Gemeinde combinations, {final_count} unique PLZ")
    if still_missing:
        print(f"  WARNING: {len(still_missing)} target PLZ still missing: {sorted(still_missing)}")
    else:
        print(f"  All {len(target_plz)} target PLZ covered.")

    pop_total = result["einwohner"].sum()
    print(f"  Total population: {pop_total:,.0f}")

    show_examples(result, "population assignment")

    out = INTERIM / "plz_gemeinde_population.parquet"
    result.to_parquet(out, index=False)
    print(f"Output: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
