"""
03_intersect_population.py
Assign Zensus 2022 grid population to PLZ-Gemeinde combinations.

Approach: instead of expensive polygon intersection, assign each 1km
grid cell midpoint to its PLZ and Gemeinde via spatial join, then
aggregate population by (PLZ, AGS).

Input:
  - data/raw/plz_polygone.geojson
  - data/raw/vg250/.../DE_VG250.gpkg (layer vg250_gem)
  - data/raw/zensus2022_gitter/Zensus2022_Bevoelkerungszahl_1km-Gitter.csv

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
# 1. Load Zensus grid as points
# ---------------------------------------------------------------------------

def load_zensus_points() -> gpd.GeoDataFrame:
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
    print(f"  Reprojecting to {TARGET_CRS} ...")
    gdf = gdf.to_crs(TARGET_CRS)
    print(f"  Done.")
    return gdf


# ---------------------------------------------------------------------------
# 2. Load PLZ polygons
# ---------------------------------------------------------------------------

def load_plz_polygons() -> gpd.GeoDataFrame:
    print("\n[2] Loading PLZ polygons ...")
    gdf = gpd.read_file(RAW / "plz_polygone.geojson")
    print(f"  {len(gdf)} PLZ polygons, CRS={gdf.crs}")

    gdf = gdf.rename(columns={"plz": "plz", "qkm": "flaeche_km2"})
    gdf["plz"] = gdf["plz"].astype(str).str.zfill(5)

    print(f"  Reprojecting to {TARGET_CRS} ...")
    gdf = gdf.to_crs(TARGET_CRS)
    print(f"  Done.")
    return gdf[["plz", "flaeche_km2", "geometry"]]


# ---------------------------------------------------------------------------
# 3. Load VG250 Gemeinde polygons
# ---------------------------------------------------------------------------

def load_vg250_gem() -> gpd.GeoDataFrame:
    print("\n[3] Loading VG250 Gemeindegrenzen ...")
    gpkg_path = RAW / "vg250" / "vg250_01-01.utm32s.gpkg.ebenen" / "vg250_ebenen_0101" / "DE_VG250.gpkg"
    gdf = gpd.read_file(gpkg_path, layer="vg250_gem")
    print(f"  {len(gdf)} rows, CRS={gdf.crs}")

    # GF=4 means "with water" which is the standard full-area representation
    gdf = gdf[gdf["GF"] == 4].copy()
    print(f"  {len(gdf)} rows after filtering GF=4")

    gdf = gdf.rename(columns={"AGS": "ags_vg250", "GEN": "gemeinde_name_vg250"})
    return gdf[["ags_vg250", "gemeinde_name_vg250", "geometry"]]


# ---------------------------------------------------------------------------
# 4. Spatial joins
# ---------------------------------------------------------------------------

def assign_population(
    points: gpd.GeoDataFrame,
    plz_poly: gpd.GeoDataFrame,
    gem_poly: gpd.GeoDataFrame,
) -> pd.DataFrame:
    print("\n[4] Spatial join: grid cells → PLZ ...")
    joined_plz = gpd.sjoin(points, plz_poly, how="inner", predicate="within")
    print(f"  {len(joined_plz)} cells matched to a PLZ")
    unmatched_plz = len(points) - len(joined_plz)
    if unmatched_plz > 0:
        pop_lost = points["Einwohner"].sum() - joined_plz["Einwohner"].sum()
        print(f"  {unmatched_plz} cells outside all PLZ polygons ({pop_lost:,.0f} people)")

    print("\n[5] Spatial join: grid cells → Gemeinde ...")
    joined_gem = gpd.sjoin(points, gem_poly, how="inner", predicate="within")
    print(f"  {len(joined_gem)} cells matched to a Gemeinde")

    # Merge: for each grid cell, get both PLZ and Gemeinde
    print("\n[6] Merging PLZ and Gemeinde assignments ...")
    plz_assign = joined_plz[["GITTER_ID_1km", "Einwohner", "plz", "flaeche_km2"]].copy()
    gem_assign = joined_gem[["GITTER_ID_1km", "ags_vg250", "gemeinde_name_vg250"]].copy()

    merged = plz_assign.merge(gem_assign, on="GITTER_ID_1km", how="inner")
    print(f"  {len(merged)} cells with both PLZ and Gemeinde")
    pop_both = merged["Einwohner"].sum()
    print(f"  Total population covered: {pop_both:,.0f}")

    # Aggregate by (PLZ, Gemeinde)
    print("\n[7] Aggregating population by (PLZ, Gemeinde) ...")
    agg = (
        merged
        .groupby(["plz", "ags_vg250", "gemeinde_name_vg250"])
        .agg(einwohner=("Einwohner", "sum"), n_cells=("GITTER_ID_1km", "count"))
        .reset_index()
    )
    # Also compute PLZ-level totals for flaeche
    plz_area = merged.groupby("plz")["flaeche_km2"].first().reset_index()
    agg = agg.merge(plz_area, on="plz", how="left")

    print(f"  {len(agg)} PLZ-Gemeinde combinations")
    print(f"  {agg['plz'].nunique()} unique PLZ")
    return agg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("03: Spatial intersection and population assignment")
    print("=" * 60)

    points = load_zensus_points()
    plz_poly = load_plz_polygons()
    gem_poly = load_vg250_gem()

    result = assign_population(points, plz_poly, gem_poly)

    # Rename ags column for consistency with crosswalk
    result = result.rename(columns={"ags_vg250": "ags", "gemeinde_name_vg250": "gemeinde_name_vg250"})

    show_examples(result, "population assignment")

    out = INTERIM / "plz_gemeinde_population.parquet"
    result.to_parquet(out, index=False)
    print(f"Output: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
