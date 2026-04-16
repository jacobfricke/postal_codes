# PLZ-Referenztabelle: Implementierungsplan

## Ziel

Eine Zeile pro PLZ mit Einwohnerzahl und Ländlichkeitsklassifizierung
(BBSR Kreistyp + Thünen Ländlichkeitsindex), um später Penetrationsraten
zu berechnen.

## Datenquellen

| Quelle | URL / Pfad | Format | CRS |
|---|---|---|---|
| PLZ-Referenzliste | `data/raw/plz-suche.csv` (bereits vorhanden) | CSV, ohne Header | n/a |
| PLZ-Polygone | Esri Feature Service (8.170 Polygone) | GeoJSON via REST API | EPSG:4326 |
| VG250 Gemeindegrenzen | BKG Open Data, GeoPackage UTM32 | GeoPackage | EPSG:25832 |
| Zensus 2022 1km-Gitter | destatis.de ZIP (Bevölkerungszahl) | CSV (`;`-getrennt) | EPSG:3035 |
| Zensus-Gitter Geometrie | BKG GeoGitter INSPIRE | GeoPackage | EPSG:3035 |
| BBSR Kreistypen | BBSR Raumgliederungen 2024 | Excel (Sheet "Kreisreferenz") | n/a |
| Thünen Ländlichkeit | `data/raw/Ländlichkeit_Kreisregionen_2016.xlsx` (manuell heruntergeladen) | Excel | n/a |

### Download-URLs

```
# VG250 Gemeindegrenzen (GeoPackage, UTM32)
https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_0101/aktuell/vg250_01-01.utm32s.gpkg.ebenen.zip

# Zensus 2022 Bevölkerungszahl Gitterzellen
https://www.destatis.de/static/DE/zensus/gitterdaten/Zensus2022_Bevoelkerungszahl.zip

# BKG GeoGitter 1km (GeoPackage, LAEA)
https://daten.gdz.bkg.bund.de/produkte/sonstige/geogitter/aktuell/DE_Grid_ETRS89-LAEA_1km.gpkg.zip

# BBSR Raumgliederungen Referenztabelle 2024
https://www.bbsr.bund.de/BBSR/DE/forschung/raumbeobachtung/Raumabgrenzungen/downloads/raumgliederungen-referenzen-2024.xlsx?__blob=publicationFile&v=5

# PLZ-Polygone (Esri Feature Service, Batches von 2000)
https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/PLZ_Gebiete/FeatureServer/0/query
```

## Struktur von plz-suche.csv

12.866 Zeilen, kein Header. Spalten:

| Index | Inhalt | Beispiel |
|---|---|---|
| 0 | Unbekannte ID | 940688 |
| 1 | AGS (7-8 Ziffern, führende Null ggf. fehlend) | 9183119 → 09183119 |
| 2 | Gemeindename | Haag in Oberbayern |
| 3 | PLZ (5-stellig) | 83527 |
| 4 | Kreisname | Landkreis Mühldorf am Inn |
| 5 | Bundesland | Bayern |

### Worked Examples in plz-suche.csv

**PLZ 83527** (einfacher Fall, ein Kreis):
- 940688, 9183119, Haag in Oberbayern, 83527, Landkreis Mühldorf am Inn, Bayern
- 940709, 9183123, Kirchdorf, 83527, Landkreis Mühldorf am Inn, Bayern

**PLZ 06333** (Stresstest, zwei Kreise):
- 64313, 15085110, Falkenstein/Harz, 06333, Landkreis Harz, Sachsen-Anhalt
- 2408511, 15087220, Hettstedt, 06333, Landkreis Mansfeld-Südharz, Sachsen-Anhalt

## Thünen-Daten

361 Kreisregionen. Spalten: `Kennziffer` (7-stellig, z.B. 1002000),
`name`, `t_typ` (1-5), `Ländlichkeit` (Float).

Die Kennziffer ist der Kreisschlüssel (5 Ziffern) + "000". Kreisregionen
fassen kleine kreisfreie Städte (<100k Einwohner) mit dem Umlandkreis
zusammen.

Mapping Kreis → Kreisregion muss aus der BBSR-Referenztabelle oder dem
VG250 abgeleitet werden.

### Thünen-Typen

| Typ | Label |
|---|---|
| 1 | sehr ländlich / weniger gute sozioökonomische Lage |
| 2 | sehr ländlich / gute sozioökonomische Lage |
| 3 | eher ländlich / weniger gute sozioökonomische Lage |
| 4 | eher ländlich / gute sozioökonomische Lage |
| 5 | nicht-ländlich |

## BBSR Kreistypen

| Typ | Label |
|---|---|
| 1 | Kreisfreie Großstadt |
| 2 | Städtischer Kreis |
| 3 | Ländlicher Kreis mit Verdichtungsansätzen |
| 4 | Dünn besiedelter ländlicher Kreis |

Quelle: Sheet "Kreisreferenz", Spalten KRS2024 (AGS), KTU2024 (Typ), KTU_NAME (Label).

## Skripte

### 01_download.py

Downloads aller externen Quellen nach `data/raw/`. Idempotent (prüft ob
Datei existiert, überspringt wenn vorhanden).

1. BBSR Excel herunterladen
2. Zensus 2022 ZIP herunterladen und entpacken (1km CSV)
3. BKG GeoGitter 1km herunterladen und entpacken
4. VG250 GeoPackage herunterladen und entpacken
5. PLZ-Polygone vom Esri Feature Service abrufen (Batches von 2000,
   als GeoJSON speichern)

Thünen-Datei und plz-suche.csv sind bereits in `data/raw/`.

### 02_prepare_crosswalk.py

Baut die PLZ-Gemeinde-Zuordnungstabelle auf.

1. `plz-suche.csv` einlesen
2. AGS auf 8 Stellen mit führender Null auffüllen
3. Kreisschlüssel ableiten (erste 5 Stellen des AGS)
4. Kreisregion-Mapping bauen:
   - Kreisfreie Städte mit <100k Einwohnern dem Umlandkreis zuordnen
   - Dafür BBSR-Referenztabelle oder Thünen-Kennziffern nutzen
5. Worked Examples für 83527 und 06333 ausgeben
6. Output: `data/interim/plz_gemeinde_crosswalk.parquet`

### 03_intersect_population.py

Räumliche Verschneidung und Bevölkerungszuordnung.

1. PLZ-Polygone laden (GeoJSON → GeoDataFrame, reprojizieren auf EPSG:25832)
2. VG250 Gemeindegrenzen laden (Layer VG250_GEM)
3. Zensus-Gitter laden:
   - CSV mit Einwohnern (EPSG:3035)
   - Gitter-Geometrie (GeoPackage, EPSG:3035)
   - Joinen und auf EPSG:25832 reprojizieren
4. PLZ-Polygone mit Gemeinde-Polygonen verschneiden (overlay intersection)
5. Zensus-Gitterzellen per Spatial Join den Schnittflächen zuordnen
6. Einwohner pro PLZ-Gemeinde-Kombination summieren
7. Einwohner pro PLZ summieren (für die `einwohner` Spalte im Output)
8. Worked Examples für 83527 und 06333 ausgeben
9. Output: `data/interim/plz_gemeinde_population.parquet`

### 04_join_classifications.py

Klassifizierungen an die PLZ-Gemeinde-Tabelle joinen.

1. BBSR-Referenztabelle laden (Kreisschlüssel → Kreistyp)
2. Thünen-Daten laden (Kreisregion → Index + Typ)
3. An PLZ-Gemeinde-Population joinen über Kreisschlüssel / Kreisregion
4. Worked Examples für 83527 und 06333 ausgeben
5. Output: `data/interim/plz_gemeinde_classified.parquet`

### 05_build_final_table.py

Aggregation auf PLZ-Ebene, beide Methoden.

**Methode A (einwohnergewichtet):**
- `thuenen_index_gewichtet`: Einwohnergewichtetes Mittel des Thünen-Index
  über alle Gemeinden in der PLZ
- `bbsr_kreistyp_dominant`: Kreistyp der Gemeinde mit dem größten
  Einwohneranteil
- `thuenen_typ_dominant`: Thünen-Typ der Gemeinde mit dem größten
  Einwohneranteil

**Methode B (dominante Gemeinde):**
- PLZ der Gemeinde mit dem größten Einwohneranteil zuordnen
- Deren Klassifizierungen direkt übernehmen

**Ambiguitätskennzahlen:**
- `dominante_gemeinde_anteil`: Einwohneranteil der größten Gemeinde (0-1)
- `anzahl_beteiligter_gemeinden`: Wie viele Gemeinden in die PLZ reinragen
- `anzahl_beteiligter_kreise`: Wie viele Kreise betroffen sind
- `methoden_konflikt_bbsr`: True wenn Methode A und B abweichen
- `methoden_konflikt_thuenen`: True wenn Methode A und B abweichen

Output: `data/processed/plz_referenz.parquet` + `data/processed/plz_referenz.csv`

### 06_sanity_checks.py

1. Summe Einwohner gegen Zensus-Gesamtbevölkerung (~84 Mio)
2. Anzahl PLZ gegen erwartete Zahl (~8.200)
3. Keine NaNs in Pflichtspalten
4. Verteilung der Kreistypen und Thünen-Typen plausibel
5. Methoden-Konfliktrate
6. Worked Examples 83527 und 06333 als vollständige Zeilen

## Output-Schema

| Spalte | Typ | Beschreibung |
|---|---|---|
| plz | string | 5-stellig |
| einwohner | int | Summe aus Zensus-Gitter über PLZ-Polygon |
| flaeche_km2 | float | |
| bbsr_kreistyp_dominant | int 1-4 | Methode A |
| bbsr_kreistyp_dominant_label | string | |
| bbsr_kreistyp_methode_b | int 1-4 | Methode B |
| thuenen_index_gewichtet | float | Einwohnergewichtetes Mittel |
| thuenen_typ_dominant | int 1-5 | Methode A |
| thuenen_typ_dominant_label | string | |
| thuenen_typ_methode_b | int 1-5 | Methode B |
| dominante_gemeinde_ags | string | |
| dominante_gemeinde_name | string | |
| dominante_gemeinde_anteil | float 0-1 | |
| anzahl_beteiligter_gemeinden | int | |
| anzahl_beteiligter_kreise | int | |
| methoden_konflikt_bbsr | bool | |
| methoden_konflikt_thuenen | bool | |

## CRS-Strategie

- Alle Geodaten werden für Verschneidungen auf EPSG:25832 (ETRS89/UTM32)
  reprojiziert
- Zensus-Gitter kommt in EPSG:3035, wird nach 25832 transformiert
- PLZ-Polygone kommen in EPSG:4326, werden nach 25832 transformiert
- VG250 kommt bereits in EPSG:25832
