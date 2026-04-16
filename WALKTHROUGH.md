# Walkthrough: Von der Ausgangsdatei zur fertigen PLZ-Referenztabelle

## Ausgangspunkt

Alles beginnt mit einer einzigen Datei: **`plz-suche.csv`** von suche-postleitzahl.org. Diese Datei hat keinen Header und enthält 12.866 Zeilen. Jede Zeile ordnet eine Postleitzahl einer Gemeinde zu:

```
62564,5334002,Aachen,52062,Städteregion Aachen,Nordrhein-Westfalen
```

| Spalte | Inhalt |
|---|---|
| 1 | Interne ID (wird nicht verwendet) |
| 2 | Amtlicher Gemeindeschlüssel (AGS), ggf. ohne führende Null |
| 3 | Gemeindename |
| 4 | Postleitzahl (5-stellig) |
| 5 | Kreisname |
| 6 | Bundesland |

Eine PLZ kann in mehreren Zeilen vorkommen, wenn sie über mehrere Gemeinden verteilt ist. Zum Beispiel hat PLZ 06333 zwei Einträge: einen für Falkenstein/Harz (Landkreis Harz) und einen für Hettstedt (Landkreis Mansfeld-Südharz).

Das Problem: Diese Tabelle sagt uns **welche** Gemeinden in einer PLZ liegen, aber nicht **wie viele Menschen** dort jeweils wohnen. Und die Ländlichkeitsklassifizierungen existieren nur auf Kreis- oder Gemeindeebene, nicht auf PLZ-Ebene.

---

## Schritt 1: Externe Daten herunterladen

**Skript:** `scripts/01_download.py`

Dieses Skript lädt fünf Datensätze herunter und speichert sie in `data/raw/`. Wenn eine Datei bereits existiert, wird sie übersprungen.

### Heruntergeladene Dateien

**`bbsr_raumgliederungen_2024.xlsx`** (8,7 MB)
Die BBSR-Referenztabelle vom Bundesinstitut für Bau-, Stadt- und Raumforschung. Enthält für jeden der 400 deutschen Kreise den Kreistyp (1-4), die Kreisregion-Zuordnung, und den Thünen-Typ (1-5). Das Sheet "Kreisreferenz" hat 77 Spalten mit verschiedenen Raumklassifizierungen. Wir nutzen davon:
- `KRS2024`: Kreisschlüssel
- `KKR2024`: Kreisregion (für den Thünen-Index-Join)
- `KTU2024`: Siedlungsstruktureller Kreistyp (1-4)
- `TH52024`: Thünen-Typ (1-5)

**`zensus2022_gitter/Zensus2022_Bevoelkerungszahl_1km-Gitter.csv`** (10,8 MB)
Bevölkerungszahlen aus dem Zensus 2022, aufgeteilt auf 210.556 Gitterzellen von je 1 km x 1 km. Jede Zeile hat eine Gitter-ID, die Koordinaten des Mittelpunkts (in EPSG:3035), und die Einwohnerzahl. Summe: 82,7 Millionen.

**`geogitter_1km/...DE_Grid_ETRS89-LAEA_1km.gpkg`** (131 MB)
Die Geometrie (Polygone) der 1km-Gitterzellen vom BKG. Wird in diesem Projekt nicht direkt verwendet, weil wir stattdessen die Mittelpunkt-Koordinaten aus der Zensus-CSV nehmen.

**`vg250/.../DE_VG250.gpkg`** (118 MB)
Die Verwaltungsgrenzen Deutschlands (VG250) vom BKG als GeoPackage. Enthält mehrere Layer. Wir nutzen den Layer `vg250_gem` mit 10.949 Gemeinde-Polygonen in EPSG:25832. Jede Gemeinde hat einen AGS-Code, über den wir sie mit plz-suche.csv und den Klassifizierungen verknüpfen.

**`plz_polygone.geojson`** (220 MB)
Die PLZ-Gebietsgrenzen als GeoJSON, abgerufen vom Esri Feature Service (Datenquelle: OpenStreetMap). 8.170 Polygone mit den Attributen `plz`, `einwohner`, `qkm`. In Batches von 500 Features heruntergeladen, weil der Service die Antwortgröße begrenzt.

### Manuelle Datei

**`Ländlichkeit_Kreisregionen_2016.xlsx`** (23 KB)
Manuell heruntergeladen von karten.landatlas.de (Thünen Landatlas). Enthält für 361 Kreisregionen den kontinuierlichen Ländlichkeitsindex und den Thünen-Typ (1-5). Die Kennziffer ist ein 7-stelliger Code, der dem Kreisschlüssel + "000" entspricht.

---

## Schritt 2: PLZ-Gemeinde-Crosswalk aufbauen

**Skript:** `scripts/02_prepare_crosswalk.py`
**Input:** `plz-suche.csv`, `bbsr_raumgliederungen_2024.xlsx`, `Ländlichkeit_Kreisregionen_2016.xlsx`
**Output:** `data/interim/plz_gemeinde_crosswalk.parquet`

Hier passiert Folgendes:

1. `plz-suche.csv` einlesen. 12 Zeilen ohne AGS werden verworfen (aufgelöste Ortsteile ohne gültige Gemeindezuordnung).
2. Den AGS auf 8 Stellen auffüllen (z.B. `9183119` → `09183119`).
3. Die ersten 5 Stellen des AGS ergeben den Kreisschlüssel (`09183`).
4. Über den Kreisschlüssel an die BBSR-Tabelle joinen. So bekommt jede Zeile einen BBSR-Kreistyp, einen Thünen-Typ, und eine Kreisregion-Zuordnung.
5. Über die Kreisregion an die Thünen-Tabelle joinen, um den kontinuierlichen Ländlichkeitsindex zu bekommen.

Ein Sonderfall: Kaiserslautern Stadt (Kreisregion 7312000) existiert in der BBSR-Tabelle 2024 als eigene Kreisregion, ist aber in der Thünen-Tabelle von 2016 mit dem Landkreis Kaiserslautern (7335000) zusammengefasst. Das Skript mappt den einen Key auf den anderen.

**Ergebnis:** 12.854 Zeilen mit PLZ, AGS, Gemeindename, Kreis, Bundesland, BBSR-Kreistyp, Thünen-Typ und Thünen-Index.

---

## Schritt 3: Räumliche Verschneidung und Bevölkerungszuordnung

**Skript:** `scripts/03_intersect_population.py`
**Input:** `plz_polygone.geojson`, `DE_VG250.gpkg`, `Zensus2022_Bevoelkerungszahl_1km-Gitter.csv`
**Output:** `data/interim/plz_gemeinde_population.parquet`

Das ist der rechenintensivste Schritt. Statt die PLZ- und Gemeinde-Polygone direkt zu verschneiden (was geometrisch komplex ist), nutzen wir einen Trick:

1. Aus der Zensus-CSV werden 210.556 Punkte erstellt (die Mittelpunkte der 1km-Gitterzellen, mit ihrer Einwohnerzahl). Diese Punkte werden von EPSG:3035 nach EPSG:25832 reprojiziert.
2. Die PLZ-Polygone werden von EPSG:4326 nach EPSG:25832 reprojiziert.
3. Die VG250-Gemeinde-Polygone sind bereits in EPSG:25832.
4. Per Spatial Join wird jeder Gitterpunkt seiner PLZ zugeordnet.
5. Per Spatial Join wird jeder Gitterpunkt seiner Gemeinde zugeordnet.
6. Die Ergebnisse werden zusammengeführt: Jeder Punkt bekommt eine PLZ und eine Gemeinde.
7. Gruppierung nach (PLZ, Gemeinde) mit Summe der Einwohner.

Dieser Ansatz findet mehr Gemeinde-Überlappungen als die tabellarische Zuordnung aus plz-suche.csv. Zum Beispiel hat PLZ 83527 laut plz-suche.csv 2 Gemeinden, aber die räumliche Verschneidung findet 3 (Rechtmehring ragt mit 40 Einwohnern am Rand hinein).

877 Gitterzellen (97.000 Einwohner) fallen außerhalb aller PLZ-Polygone und gehen verloren. Das sind vermutlich Inseln, Grenzgebiete, oder kleine Lücken zwischen PLZ-Grenzen.

**Ergebnis:** 14.432 PLZ-Gemeinde-Kombinationen für 8.140 PLZ.

---

## Schritt 4: Klassifizierungen an die Bevölkerungsdaten joinen

**Skript:** `scripts/04_join_classifications.py`
**Input:** `plz_gemeinde_population.parquet`, `bbsr_raumgliederungen_2024.xlsx`, `Ländlichkeit_Kreisregionen_2016.xlsx`
**Output:** `data/interim/plz_gemeinde_classified.parquet`

Dieser Schritt nimmt die räumlichen Bevölkerungsdaten aus Schritt 3 und hängt die Klassifizierungen dran. Er nutzt nicht den Crosswalk aus Schritt 2, weil die räumliche Verschneidung zusätzliche Gemeinden gefunden hat. Stattdessen wird der AGS aus VG250 direkt verwendet:

1. AGS (8-stellig) → Kreisschlüssel (erste 5 Stellen) → BBSR-Tabelle → Kreistyp + Kreisregion + Thünen-Typ
2. Kreisregion → Thünen-Tabelle → Ländlichkeitsindex

**Ergebnis:** Jede PLZ-Gemeinde-Kombination hat jetzt Einwohnerzahl, BBSR-Kreistyp, Thünen-Typ und Thünen-Index.

---

## Schritt 5: Finale Tabelle bauen

**Skript:** `scripts/05_build_final_table.py`
**Input:** `plz_gemeinde_classified.parquet`
**Output:** `data/processed/plz_referenz.parquet`, `data/processed/plz_referenz.csv`

Hier wird von der PLZ-Gemeinde-Ebene (14.432 Zeilen) auf die PLZ-Ebene (8.140 Zeilen) aggregiert.

**Methode A (einwohnergewichtet):**
- Thünen-Index: Gewichteter Durchschnitt über alle Gemeinden in der PLZ, gewichtet nach Einwohnerzahl.
- BBSR-Kreistyp: Die Einwohner werden nach Kreistyp gruppiert. Der Typ mit den meisten Einwohnern gewinnt.
- Thünen-Typ: Gleiche Logik wie beim BBSR-Typ.

**Methode B (dominante Gemeinde):**
- Die PLZ wird komplett der Gemeinde mit den meisten Einwohnern zugeordnet.
- Deren Klassifizierungen werden direkt übernommen.

Die Methoden können sich unterscheiden. Beispiel: Wenn in einer PLZ drei kleine Gemeinden vom Typ 4 zusammen mehr Einwohner haben als eine große Gemeinde vom Typ 3, sagt Methode A "Typ 4" und Methode B "Typ 3". Das passiert bei 4 von 8.140 PLZ beim BBSR-Typ und bei 3 PLZ beim Thünen-Typ.

Zusätzlich berechnet:
- Anteil der dominanten Gemeinde an der PLZ-Bevölkerung (Ambiguitätskennzahl)
- Anzahl beteiligter Gemeinden und Kreise
- Konflikt-Flags für beide Methoden

**Ergebnis:** Eine Zeile pro PLZ mit 17 Spalten.

---

## Schritt 6: Sanity Checks

**Skript:** `scripts/06_sanity_checks.py`
**Input:** `plz_referenz.parquet`

Prüft die finale Tabelle gegen Erwartungswerte:

| Check | Ergebnis |
|---|---|
| Gesamtbevölkerung | 82,6 Mio (99,9% des Zensus) |
| Anzahl PLZ | 8.140 (erwartet ~8.200) |
| Keine NaNs in Pflichtspalten | Alle 17 Spalten vollständig |
| BBSR-Typen im Bereich 1-4 | Bestanden |
| Thünen-Typen im Bereich 1-5 | Bestanden |
| Thünen-Index plausibel | -4,54 bis 1,12 |
| Methodenkonflikte | BBSR: 4 PLZ (0,05%), Thünen: 3 PLZ (0,04%) |

---

## Übersicht aller Dateien

### Im Repository committed

| Datei | Beschreibung |
|---|---|
| `plz-suche.csv` | Ausgangsdatei: PLZ-Gemeinde-Zuordnung von suche-postleitzahl.org |
| `requirements.txt` | Python-Abhängigkeiten |
| `PLAN.md` | Implementierungsplan mit Datenquellen und URLs |
| `WALKTHROUGH.md` | Diese Datei |
| `README.md` | Projektbeschreibung für GitHub |
| `scripts/01_download.py` | Lädt externe Daten herunter |
| `scripts/02_prepare_crosswalk.py` | Baut tabellarischen PLZ-Gemeinde-Crosswalk |
| `scripts/03_intersect_population.py` | Räumliche Verschneidung mit Zensus-Gitter |
| `scripts/04_join_classifications.py` | Joint BBSR und Thünen an die Bevölkerungsdaten |
| `scripts/05_build_final_table.py` | Aggregiert auf PLZ-Ebene (Methode A + B) |
| `scripts/06_sanity_checks.py` | Validiert die Ergebnisse |
| `data/processed/plz_referenz.parquet` | Finale Tabelle (Parquet) |
| `data/processed/plz_referenz.csv` | Finale Tabelle (CSV) |

### Heruntergeladen (nicht committed)

| Datei | Größe | Beschreibung |
|---|---|---|
| `data/raw/bbsr_raumgliederungen_2024.xlsx` | 8,7 MB | BBSR-Referenztabelle mit Kreistypen |
| `data/raw/Ländlichkeit_Kreisregionen_2016.xlsx` | 23 KB | Thünen Ländlichkeitsindex (manuell heruntergeladen) |
| `data/raw/plz_polygone.geojson` | 220 MB | PLZ-Gebietsgrenzen vom Esri Feature Service |
| `data/raw/vg250/...DE_VG250.gpkg` | 118 MB | VG250 Gemeindegrenzen vom BKG |
| `data/raw/zensus2022_gitter/...1km-Gitter.csv` | 10,8 MB | Zensus 2022 Bevölkerungszahlen im 1km-Gitter |
| `data/raw/geogitter_1km/...1km.gpkg` | 131 MB | Gitter-Geometrie vom BKG (nicht direkt verwendet) |

### Zwischenergebnisse (nicht committed)

| Datei | Zeilen | Beschreibung |
|---|---|---|
| `data/interim/plz_gemeinde_crosswalk.parquet` | 12.854 | Tabellarischer Crosswalk aus plz-suche.csv mit Klassifizierungen |
| `data/interim/plz_gemeinde_population.parquet` | 14.432 | PLZ-Gemeinde-Kombinationen mit Einwohnerzahlen aus der räumlichen Verschneidung |
| `data/interim/plz_gemeinde_classified.parquet` | 14.432 | Wie oben, plus BBSR und Thünen Klassifizierungen |
