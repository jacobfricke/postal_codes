"""
01_download.py
Download all external data sources to data/raw/.
Idempotent: skips files that already exist.

Sources:
- BBSR Raumgliederungen 2024 (Excel)
- Zensus 2022 Bevölkerungszahl 1km-Gitter (CSV in ZIP)
- BKG GeoGitter 1km Geometrie (GeoPackage in ZIP)
- VG250 Gemeindegrenzen (GeoPackage in ZIP)
- PLZ-Polygone (Esri Feature Service, batched GeoJSON)

Already present (manual):
- plz-suche.csv
- Ländlichkeit_Kreisregionen_2016.xlsx
"""

import json
import pathlib
import zipfile

import requests

RAW = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download_file(url: str, dest: pathlib.Path) -> None:
    """Download a file if it does not already exist."""
    if dest.exists():
        print(f"  SKIP (exists): {dest.name}")
        return
    print(f"  Downloading: {dest.name} ...")
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    print(f"  OK ({dest.stat().st_size / 1e6:.1f} MB)")


def download_and_unzip(url: str, zip_dest: pathlib.Path, extract_dir: pathlib.Path) -> None:
    """Download a ZIP and extract it. Skip if extract_dir already has files."""
    if extract_dir.exists() and any(extract_dir.iterdir()):
        print(f"  SKIP (exists): {extract_dir.name}/")
        return
    download_file(url, zip_dest)
    extract_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Extracting to {extract_dir.name}/ ...")
    with zipfile.ZipFile(zip_dest) as zf:
        zf.extractall(extract_dir)
    print(f"  OK ({sum(1 for _ in extract_dir.rglob('*') if _.is_file())} files)")


# ---------------------------------------------------------------------------
# 1. BBSR Raumgliederungen 2024
# ---------------------------------------------------------------------------

def download_bbsr():
    print("\n[1/5] BBSR Raumgliederungen 2024")
    url = (
        "https://www.bbsr.bund.de/BBSR/DE/forschung/raumbeobachtung/"
        "Raumabgrenzungen/downloads/raumgliederungen-referenzen-2024.xlsx"
        "?__blob=publicationFile&v=5"
    )
    download_file(url, RAW / "bbsr_raumgliederungen_2024.xlsx")


# ---------------------------------------------------------------------------
# 2. Zensus 2022 Bevölkerungszahl Gitterzellen
# ---------------------------------------------------------------------------

def download_zensus():
    print("\n[2/5] Zensus 2022 Bevölkerungszahl 1km-Gitter")
    url = "https://www.destatis.de/static/DE/zensus/gitterdaten/Zensus2022_Bevoelkerungszahl.zip"
    download_and_unzip(url, RAW / "zensus2022_bevoelkerung.zip", RAW / "zensus2022_gitter")


# ---------------------------------------------------------------------------
# 3. BKG GeoGitter 1km Geometrie
# ---------------------------------------------------------------------------

def download_geogitter():
    print("\n[3/5] BKG GeoGitter 1km Geometrie")
    url = "https://daten.gdz.bkg.bund.de/produkte/sonstige/geogitter/aktuell/DE_Grid_ETRS89-LAEA_1km.gpkg.zip"
    download_and_unzip(url, RAW / "geogitter_1km.zip", RAW / "geogitter_1km")


# ---------------------------------------------------------------------------
# 4. VG250 Gemeindegrenzen
# ---------------------------------------------------------------------------

def download_vg250():
    print("\n[4/5] VG250 Gemeindegrenzen (UTM32)")
    url = "https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_0101/aktuell/vg250_01-01.utm32s.gpkg.ebenen.zip"
    download_and_unzip(url, RAW / "vg250.zip", RAW / "vg250")


# ---------------------------------------------------------------------------
# 5. PLZ-Polygone vom Esri Feature Service
# ---------------------------------------------------------------------------

def download_plz_polygons():
    print("\n[5/5] PLZ-Polygone (Esri Feature Service)")
    dest = RAW / "plz_polygone.geojson"
    if dest.exists():
        print(f"  SKIP (exists): {dest.name}")
        return

    base_url = (
        "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/"
        "PLZ_Gebiete/FeatureServer/0/query"
    )

    all_features = []
    offset = 0
    batch_size = 500

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=3)
    session.mount("https://", adapter)

    while True:
        params = {
            "where": "1=1",
            "outFields": "plz,note,einwohner,qkm",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": batch_size,
        }
        print(f"  Fetching batch at offset {offset} ...")
        resp = session.get(base_url, params=params, timeout=300)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            break

        all_features.extend(features)
        offset += len(features)

        if len(features) < batch_size:
            break

    geojson = {
        "type": "FeatureCollection",
        "features": all_features,
    }

    with open(dest, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)

    print(f"  OK ({len(all_features)} features, {dest.stat().st_size / 1e6:.1f} MB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Downloading data sources to data/raw/")
    print("=" * 60)

    download_bbsr()
    download_zensus()
    download_geogitter()
    download_vg250()
    download_plz_polygons()

    print("\n" + "=" * 60)
    print("All downloads complete.")
    print("=" * 60)

    # Verify manual files
    manual_files = [
        RAW / "plz-suche.csv",
        RAW / "Ländlichkeit_Kreisregionen_2016.xlsx",
    ]
    for f in manual_files:
        status = "OK" if f.exists() else "MISSING"
        print(f"  [{status}] {f.name}")


if __name__ == "__main__":
    main()
