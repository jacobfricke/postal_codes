# German Postal Code Reference Table with Population and Rurality Classifications

A ready-to-use dataset that assigns population counts and rurality classifications to each of Germany's ~8,200 five-digit postal code areas (Postleitzahlen). The output is a single flat table with one row per PLZ, available as both Parquet and CSV.

## License

This dataset is derived from multiple open data sources. The most restrictive upstream license is the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/) from the OpenStreetMap-based PLZ boundaries. The derived dataset is therefore released under **ODbL 1.0**. You are free to share and adapt the data, as long as you attribute the sources (see below) and share any adapted database under the same license.

## Why this exists

German rurality classifications (BBSR district types, Thünen rurality index) are published at the district or municipality level. BBSR stands for Bundesinstitut für Bau-, Stadt- und Raumforschung (Federal Institute for Research on Building, Urban Affairs and Spatial Development). Postal code areas, however, do not align with administrative boundaries. A single PLZ can span multiple municipalities and even multiple districts. This repository resolves that mismatch by spatially assigning population from the 2022 Census grid to PLZ-municipality intersections, then aggregating the classifications up to the PLZ level.

## Quick start

The final dataset is in `data/processed/`:

- **`plz_referenz.parquet`** (0.3 MB, recommended)
- **`plz_referenz.csv`** (1.2 MB)

If you just want to use the data, download one of these files. No code needed.

```python
import pandas as pd

plz = pd.read_parquet("data/processed/plz_referenz.parquet")
# or
plz = pd.read_csv("data/processed/plz_referenz.csv", dtype={"plz": str})
```

## What is in the table

8,140 rows (one per PLZ), covering 82.6 million residents (99.9% of the 2022 Census total).

### Example row

PLZ **06333** spans two districts (Landkreis Harz and Landkreis Mansfeld-Südharz) in Sachsen-Anhalt. Hettstedt is the dominant municipality with 94% of the population.

| Column | Value |
|---|---|
| `plz` | 06333 |
| `einwohner` | 14138 |
| `flaeche_km2` | 47.23 |
| `bbsr_kreistyp_dominant` | 4 (Dünn besiedelter ländlicher Kreis) |
| `thuenen_index_gewichtet` | 0.65 |
| `thuenen_typ_dominant` | 1 (sehr ländlich / weniger gute sozioökonomische Lage) |
| `dominante_gemeinde_name` | Hettstedt |
| `dominante_gemeinde_anteil` | 0.94 |
| `anzahl_beteiligter_gemeinden` | 3 |
| `anzahl_beteiligter_kreise` | 2 |
| `methoden_konflikt_bbsr` | False |

### Column reference

| Column | Type | Description |
|---|---|---|
| `plz` | string | Five-digit German postal code |
| `einwohner` | int | Population count, summed from the Census 2022 1km grid cells that fall within this PLZ |
| `flaeche_km2` | float | Area of the PLZ polygon in square kilometers |
| `bbsr_kreistyp_dominant` | int 1-4 | BBSR district type (Method A). 1 = major city, 2 = urban district, 3 = rural district with some density, 4 = sparsely populated rural district |
| `bbsr_kreistyp_dominant_label` | string | Human-readable label for the above |
| `bbsr_kreistyp_methode_b` | int 1-4 | BBSR district type (Method B) |
| `thuenen_index_gewichtet` | float | Thünen rurality index, population-weighted mean across all municipalities within this PLZ. The index combines five indicators: settlement density, share of agricultural/forestry land, share of single/two-family houses, regional population potential (50km radius), and accessibility of major centers. Values above 0 are more rural than average, below 0 are more urban. The threshold between "rural" and "non-rural" is -0.2 |
| `thuenen_typ_dominant` | int 1-5 | Thünen rurality type (Method A). See type definitions below |
| `thuenen_typ_dominant_label` | string | Human-readable label for the above |
| `thuenen_typ_methode_b` | int 1-5 | Thünen rurality type (Method B) |
| `dominante_gemeinde_ags` | string | Official municipality key (AGS) of the municipality with the most residents in this PLZ |
| `dominante_gemeinde_name` | string | Name of that municipality |
| `dominante_gemeinde_anteil` | float 0-1 | Share of the PLZ population living in the dominant municipality. 1.0 means the entire PLZ falls within a single municipality |
| `anzahl_beteiligter_gemeinden` | int | Number of municipalities that overlap with this PLZ |
| `anzahl_beteiligter_kreise` | int | Number of districts that overlap with this PLZ |
| `methoden_konflikt_bbsr` | bool | True if Method A and Method B disagree on the BBSR type |
| `methoden_konflikt_thuenen` | bool | True if Method A and Method B disagree on the Thünen type |

### BBSR district types

| Code | German | English |
|---|---|---|
| 1 | Kreisfreie Großstadt | Major city (independent city) |
| 2 | Städtischer Kreis | Urban district |
| 3 | Ländlicher Kreis mit Verdichtungsansätzen | Rural district with some urban density |
| 4 | Dünn besiedelter ländlicher Kreis | Sparsely populated rural district |

### Thünen rurality types

| Code | German | English |
|---|---|---|
| 1 | Sehr ländlich / weniger gute sozioökonomische Lage | Very rural / less favorable socioeconomic conditions |
| 2 | Sehr ländlich / gute sozioökonomische Lage | Very rural / good socioeconomic conditions |
| 3 | Eher ländlich / weniger gute sozioökonomische Lage | Rather rural / less favorable socioeconomic conditions |
| 4 | Eher ländlich / gute sozioökonomische Lage | Rather rural / good socioeconomic conditions |
| 5 | Nicht-ländlich | Non-rural |

## Methodology

### How PLZ are matched to municipalities

Postal codes and municipality boundaries do not align. Instead of forcing a one-to-one mapping, this pipeline determines the population overlap between each PLZ and each municipality using the Census 2022 population grid.

1. PLZ polygons (from the Esri/OpenStreetMap dataset) and VG250 municipality polygons (from BKG) are loaded in a common coordinate system (EPSG:25832, UTM zone 32N).
2. Each 1km Census grid cell midpoint is spatially joined to both the PLZ it falls in and the municipality it falls in.
3. The population of each grid cell is then attributed to that specific PLZ-municipality combination.
4. This produces a weighted crosswalk: for each PLZ, we know exactly how many people live in each overlapping municipality.

### Two classification methods

**Method A (population-weighted, recommended):**
For the continuous Thünen index, Method A computes a population-weighted average across all municipalities within a PLZ. For categorical classifications (BBSR type, Thünen type), it sums the population by category and picks the category with the most residents. This means that several small municipalities of one type can together outweigh a single larger municipality of a different type.

**Method B (dominant municipality, robustness check):**
Method B assigns the entire PLZ to whichever single municipality contains the most residents, then takes that municipality's classifications directly. This is simpler but ignores all other overlapping municipalities.

Both methods are included as separate columns. When they agree, the classification is unambiguous. When they disagree (flagged by the `methoden_konflikt_*` columns), the PLZ is a borderline case. In practice, the two methods disagree on fewer than 0.1% of all PLZ.

### Ambiguity metric

The column `dominante_gemeinde_anteil` indicates how clearly a PLZ belongs to a single municipality. A value of 1.0 means the entire PLZ population lives in one municipality (no ambiguity). Lower values mean the PLZ is split across multiple municipalities. About 70% of PLZ fall entirely within a single municipality. For the remaining 30%, the median dominant share is still above 80%.

## Data sources

| Dataset | Provider | Reference date | License | URL |
|---|---|---|---|---|
| PLZ-municipality mapping | suche-postleitzahl.org | 2023 | ODbL | `plz-suche.csv` (included) |
| PLZ polygons | OpenStreetMap via Esri DE | July 2023 | ODbL | [ArcGIS Hub](https://opendata-esri-de.opendata.arcgis.com/datasets/esri-de-content::postleitzahlengebiete-in-deutschland) |
| Municipality boundaries (VG250) | BKG (GeoBasis-DE) | 2025-01-01 | dl-de/by-2-0 | [BKG Open Data](https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_0101/aktuell/) |
| Population 1km grid | Statistische Ämter des Bundes und der Länder | Census 2022-05-15 | Open data, attribution required | [Destatis](https://www.zensus2022.de/DE/Ergebnisse-des-Zensus/gitterzellen.html) |
| BBSR district types | BBSR (Raumabgrenzungen) | 2024 | Open data | [BBSR](https://www.bbsr.bund.de/BBSR/DE/forschung/raumbeobachtung/Raumabgrenzungen/deutschland/kreise/siedlungsstrukturelle-kreistypen/kreistypen.html) |
| Thünen rurality index | Thünen Institute (Landatlas) | 2016 | Open data, attribution required | [Landatlas](https://www.landatlas.de/) |

### Attribution

If you use this dataset, please credit the underlying data providers:

- Population data: © Statistische Ämter des Bundes und der Länder, 2024
- Municipality boundaries: © GeoBasis-DE / BKG (2025), dl-de/by-2-0
- PLZ boundaries: © OpenStreetMap contributors, ODbL
- Rurality index: Küpper, P. (2016). Abgrenzung und Typisierung ländlicher Räume. Thünen Working Paper 68. [PDF](https://literatur.thuenen.de/digbib_extern/dn057783.pdf)
- BBSR district types: BBSR Bonn, 2024

## Reproducing the pipeline

### Prerequisites

- Python 3.11+
- About 500 MB disk space for raw data downloads

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Manual download

One file must be downloaded manually from the Thünen Landatlas interactive map, because the site has no API or direct download link:

1. Go to [karten.landatlas.de](https://karten.landatlas.de/)
2. Select the indicator "Ländlichkeit" under "Raumstruktur"
3. Choose spatial level "Kreisregionen"
4. Click "Download Daten und Karten" and export as Excel
5. Save the file as `data/raw/Ländlichkeit_Kreisregionen_2016.xlsx`

### Run the pipeline

The scripts are numbered and should be run in order. Each script reads from `data/raw/` or `data/interim/` and writes its output for the next step.

```bash
python scripts/01_download.py           # Download external data (~5 min)
python scripts/02_prepare_crosswalk.py  # Build PLZ-municipality crosswalk
python scripts/03_intersect_population.py  # Spatial population assignment (~2 min)
python scripts/04_join_classifications.py  # Attach BBSR and Thünen data
python scripts/05_build_final_table.py  # Aggregate to PLZ level
python scripts/06_sanity_checks.py      # Validate the output
```

All downloads in `01_download.py` are idempotent. If a file already exists, it is skipped.

## Project structure

```
data/
  raw/              Downloaded source files (not committed, ~500 MB)
  interim/          Intermediate Parquet files (not committed)
  processed/        Final output (committed — clone and use directly)
    plz_referenz.parquet
    plz_referenz.csv
scripts/
  01_download.py
  02_prepare_crosswalk.py
  03_intersect_population.py
  04_join_classifications.py
  05_build_final_table.py
  06_sanity_checks.py
plz-suche.csv        PLZ-municipality mapping from suche-postleitzahl.org (committed)
```

If you only want the data, clone the repo and use the files in `data/processed/` directly. You only need to run the pipeline if you want to reproduce or modify the results.

## Known limitations

- **30 missing PLZ.** The PLZ polygon dataset contains 8,170 polygons, but only 8,140 have at least one Census grid cell assigned. The remaining 30 are very small areas (single buildings, special-purpose PLZ) with no 1km grid cell midpoint falling inside them.
- **0.1% population not assigned.** About 97,000 people (out of 82.7 million) live in Census grid cells that fall outside all PLZ polygons, likely on islands, near borders, or in gaps between PLZ boundaries.
- **PLZ boundaries are from 2023.** Deutsche Post does not publish official PLZ boundaries as open data. The polygons used here are derived from OpenStreetMap and were last updated in July 2023. Minor boundary changes since then are not reflected.
- **Thünen index is from 2016.** The Thünen rurality index was published in 2016 based on data from 2011-2015. The five rurality types and the continuous index have not been officially updated since then. An update was announced for 2025 but has not yet been released.
- **BBSR types are from 2024.** The Kreistyp classification uses the BBSR 2024 reference, which reflects the current district structure.
- **Temporal mismatch between sources.** The Census population is from May 2022, the municipality boundaries (VG250) from January 2025, and the PLZ polygons from July 2023. Municipality mergers or boundary changes between these dates could cause small mismatches at the edges. In practice, this affects very few PLZ.
- **Coordinate reference systems.** All spatial operations use EPSG:25832 (ETRS89 / UTM zone 32N). The Census grid is natively in EPSG:3035 (ETRS89-LAEA) and is reprojected. PLZ polygons are natively in EPSG:4326 (WGS84) and are reprojected.
