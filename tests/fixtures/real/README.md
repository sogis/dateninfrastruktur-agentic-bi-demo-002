# Reale Datenfixtures für die SLayer-Spezifikation

Dieses Verzeichnis enthält neun vollständige öffentliche Quelldateien aus dem bereitgestellten Katalog, ihre Herkunftsnachweise, unabhängige SQL-Sollwerte und ein kleines vorbereitetes DuckDB-Bundle. Die Kataloge wurden zum Auffinden und Verstehen der vorhandenen Daten verwendet. Daraus folgt keine Anforderung an einen produktiven Katalogimport, ETL-Dienst oder eine Java-Komponente.

Die unveränderten Parquet-Dateien umfassen zusammen **55 119 Bytes**. Deshalb wurde keine Stichprobe gezogen. Alle Gemeinden und alle vorhandenen Jahre der ausgewählten Quellen bleiben enthalten. Die genaue Herkunft, Abrufzeit, Prüfsumme, Lizenz, Originalfelder und Zeilenzahl stehen je Datei in `manifest.json`. Inhaltliche Grenzen und konkrete Befunde stehen in `DATA_FINDINGS.md`.

## Dateien und Zuständigkeiten

| Pfad | Bedeutung |
|---|---|
| `raw/*.parquet` | Unveränderte vollständige Quelldateien; niemals von Tests überschreiben. |
| `manifest.json` | Herkunft und SHA256 jedes Originals; zusätzlich Nachweise zu Katalog, Metadaten und Lizenz. |
| `metadata_excerpts.json` | Relevante Originalbeschreibungen, Zeitangaben und Zugriffsrechte aus den gelieferten Metadaten. |
| `catalogue_metadata.json` | Auszug der gelieferten Datenbank-Views und ihrer Quellen. |
| `fetch_sources.py`, `enrich_manifest.py` | Einmalige Erfassungs- und Dokumentationsskripte; benötigen die ursprünglich gelieferten Katalogdateien unter `upload/`. Sie sind kein vorgeschriebener Produktionsprozess. |
| `reference_queries.sql` | 24 fachliche Referenzabfragen direkt auf den unveränderten Originalen; ohne SLayer. |
| `run_reference.py` | Prüft Quellchecksummen und berechnet die Referenzabfragen offline. |
| `expected_results.json`, `expected/*.csv` | Vollständige Sollwerte inklusive aller 106 Gemeinden, aller 10 Bezirke und aller 42 Fahrzeugarten. |
| `fixture_build.py` | Erzeugt die nachfolgend beschriebenen physischen DuckDB-Tabellen; keine produktive App. |
| `normalized/pilot.duckdb` | Vorbereitetes lokales Testbundle mit physischen Tabellen und Primärschlüsseln. |
| `normalized/pilot.schema.json` | Verbindliche Tabelle aller Spalten/Typen/Schlüssel/Zeilenzahlen, Ableitungs-SQL, Engine-Version und Prüfsummen. |
| `verify_normalized.py`, `normalized/verification.json` | Vergleich des vorbereiteten Bundles mit den unabhängigen Original-Sollwerten. 13 Vergleiche mit insgesamt 383 Ergebniszeilen bestanden. |
| `author_invariants.sql` | 18 ausdrücklich verfasste SQL-Prüfungen für diesen Kandidaten: Schlüssel, Beziehungen, bekannte Fahrzeugarten-Abdeckung, Zählidentitäten, Zellschlüssel, technische Periodenschlüssel und dokumentierte Stichtage. Jede Prüfung muss 0 Verletzungen melden. |
| `build_edgecases.py`, `edgecases/` | Drei ausdrücklich abgeleitete Negativfixtures mit eigener Herkunft und Mutation; keine neuen Beobachtungen. |

## Reproduzieren

Die beiliegenden Ergebnisse und das vorbereitete Bundle wurden mit **DuckDB 2.0.0** erstellt. Ein kompatibler Python-Interpreter und dieses Paket genügen; SLayer wird für die Referenzberechnung nicht benötigt. Die folgenden Befehle sind ab diesem Verzeichnis auszuführen:

```sh
python run_reference.py
python verify_normalized.py
python build_edgecases.py
python fixture_build.py --output normalized/rebuilt.duckdb
```

`fixture_build.py` akzeptiert standardmässig `normalized/pilot.duckdb` als Ausgabe und verweigert das Überschreiben einer bestehenden Datenbank. Zum Neuaufbau einen neuen Ausgabepfad verwenden. `verify_normalized.py` prüft das beiliegende `normalized/pilot.duckdb`; für einen abweichenden Ausgabepfad den Prüflauf entsprechend binden. Ein Neuaufbau unter einer anderen freigegebenen Engine-Version muss erneut gegen die Sollwerte geprüft werden. Die binäre Datenbankdatei muss dabei nicht dieselbe SHA256 wie ein früherer Neubau erhalten; ihre eigene Begleitdatei dokumentiert den jeweiligen Build.

Alle Offline-Skripte benötigen nur die Dateien dieses Verzeichnisses. Ausnahme sind die ausdrücklich separat aufgeführten einmaligen Beschaffungs-/Metadaten-Skripte. Ein erneuter Quellenabruf wäre ein neuer Snapshot und darf nicht als stilles Update des bestehenden Teststands behandelt werden.

## Verbindliches normalisiertes Schema

Die exakten SQL-Typen aller Felder und das vollständige Ableitungs-SQL stehen in `normalized/pilot.schema.json`. Diese Übersicht legt die fachliche Bedeutung und die gemeinsame Benennung fest. Sämtliche Objekte in `pilot.duckdb` sind **physische Basistabellen**. Für Laufzeitabfragen ist kein Parquet-Zugriff und kein ursprünglicher Katalog erforderlich.

| Tabelle | Zeilen | Primärschlüssel / Körnung | Weitere Felder |
|---|---:|---|---|
| `municipalities` | 106 | `geo_version, municipality_id` | `municipality_name, district_id, district_name` |
| `population` | 106 | `report_year, geo_version, municipality_id` | `period_start, reference_date, people, women, men, swiss_people, foreign_people, age_0_19, age_20_39, age_40_64, age_65_79, age_80_plus, age_65_plus` |
| `vehicles` | 2623 | `report_year, geo_version, municipality_id, vehicle_category_code` | `period_start, reference_date, vehicle_category_name, vehicle_group_code, vehicle_group_name, vehicles, registrations` |
| `staff` | 224 | `report_year, education` | `period_start, staff` |
| `revenue` | 43 | `report_year` | `period_start, nominal_chf` |
| `heating` | 106 | `report_year, geo_version, municipality_id` | `period_start, reference_date, buildings, heat_pump, heating_oil, gas, wood, electricity, district_heating, other_or_unknown` |
| `building_category` | 106 | `report_year, geo_version, municipality_id` | `period_start, reference_date, buildings, single_family, multi_family, residential_secondary_use, partially_residential` |
| `ebau` | 23 | `period_start` | `report_year, municipalities_stock, submitted_dossiers` |
| `taxes` | 104 | `report_year, geo_version, municipality_id` | `period_start, municipality_name, natural_person_tax_tchf, legal_person_tax_tchf, tax_total_tchf, tax_total_chf` |
| `years` | 46 | `report_year` | `period_start` |

Wesentliche Konventionen:

- `report_year` ist das Berichtsjahr. Bei Bevölkerung/Fahrzeugen stammt es aus den gelieferten Zeitmetadaten, bei Steuern aus der Beschreibung/Edition; es wird nicht aus einem Dateinamen erraten.
- `period_start` ist für Jahresdaten der **technische Periodenschlüssel** 1. Januar. Er behauptet keinen Erhebungsstichtag. Bei eBau bezeichnet er den Berichtsmonat.
- `reference_date` bezeichnet einen tatsächlich dokumentierten Beobachtungsstichtag. Bevölkerung und GWS: `2025-12-31`; Fahrzeuge: `NULL`, weil ein konkreter Stichtag nicht angegeben ist. Bei Personal wird kein nicht belegter Stichtag ergänzt.
- `geo_version` ist im 106-Gemeinden-Pilot `2025`, in der Steuerquelle `2026`. Die Bevölkerungszuordnung zu 2025 ist eine ausdrücklich dokumentierte Fixture-Bindung an die identische 106-Gemeinden-Schlüsselmenge der zeitlich dokumentierten Fahrzeug-/GWS-Geografie. Sie ist keine zusätzliche Aussage aus dem Bevölkerungsdateinamen.
- `municipality_id` ist der BFS-Schlüssel als Integer. Beziehungen verwenden Schlüssel und Gebietsstand. Gemeindenamen dienen zur Anzeige. `district_name` stammt aus der Bevölkerung und enthält beispielsweise `Bezirk Gäu`; `district_id` stammt aus der geprüften eindeutigen Fahrzeugzuordnung.
- `population`, `vehicles`, `heating`, `building_category` und `taxes` enthalten zusätzlich `cell_id VARCHAR` in der exakt definierten Form `geo_version|report_year|municipality_id`, beispielsweise `2025|2025|2401`. Dieser gemeinsame Zellschlüssel dient einem einfachen `count_distinct` vor lokalen Kennzahlfiltern; er ersetzt keinen Primärschlüssel. Auf der Fahrzeugtabelle teilen die Fahrzeugarten einer Gemeinde/Jahreszelle denselben Wert. Für AV genügt das Berichtsjahr als Zellschlüssel.
- `vehicle_category_code` ist eine Zeichenkette. Die führende Null von `"01"` muss erhalten bleiben. `vehicles` zählt einzelne Fahrzeuge; `registrations` zählt nach der gelieferten Beschreibung Zulassungen unter Berücksichtigung von Wechselschildern.
- `nominal_chf` ist `DECIMAL(18,2)`. Die Umsatzquelle enthält `DOUBLE`; sämtliche vorhandenen Werte lassen sich mit höchstens zwei Dezimalstellen darstellen. Die bewusste Typnormalisierung ist im Build sichtbar. Steuerwerte bleiben als gerundete TCHF erhalten; `tax_total_chf` ist lediglich die Einheitenumrechnung mal 1000 und macht die Werte nicht genauer.
- `age_65_plus` ist die Summe der vorhandenen Gruppen 65–79 und 80+. Die anderen Bevölkerungsspalten sind Marginalzahlen; sie erlauben keinen beobachteten Schnitt Alter × Geschlecht.

`population_sex_nationality` wird wegen des tatsächlich vorhandenen mehrfachen Gemeinde-Schlüssels nicht in die Laufzeittabellen übernommen. Das Original ist vollständig vorhanden und bildet einen realen Quarantänetest. Das Steuerdataset ist eine separate Prüftabelle für die Geografiegrenze; seine Aufnahme in die Datei gibt keine Beziehung zur Geografie 2025 frei.

Die spezifische Abdeckung der Fahrzeugwerte `01` und `60` ist durch `vehicle_values_01_60_complete` belegt. Für andere Fahrzeugwerte bleibt die Abdeckung unbekannt; das Bundle setzt keine allgemeine Annahme um, dass jede fehlende Zeile einem Wert 0 entspricht. Die SQL-Prüfungen sind bewusst direkte Prüfungen dieses Beispiels, keine zusätzliche generische Coverage-Engine.

## Rolle der Referenzwerte

Die 24 Rohdaten-Abfragen liefern arithmetische und strukturelle Sollwerte unabhängig vom späteren SLayer-Modell. Sie liefern auch absichtlich falsche Ergebnisse unter `negative_control_*`, damit ein fehlerhafter Roh-Join oder ein falscher Bestandsdurchschnitt eindeutig erkennbar ist. Diese Werte dürfen nicht als fachliche Sollantworten verwendet werden.

Die Fahrzeug-/Bevölkerungsverhältnisse prüfen Rechenweg, Voraggregation und unveränderten Nenner bei einem Fahrzeugartenfilter. Sie bestätigen **keinen gleichen Stichtag**. Ein Test der strikten Stichtagsgleichheit muss wegen `vehicles.reference_date=NULL` scheitern beziehungsweise eine entsprechende strukturierte Entscheidung liefern. Eine freigegebene Rechnung über dieselbe Berichtsperiode muss die abweichende Genauigkeit der Zeitangaben sichtbar erhalten.

Ganzzahlige Werte und Kennungen werden exakt verglichen, CHF-Decimalwerte als Dezimalwerte beziehungsweise die mitgelieferten Dezimalzeichenketten. Für die gespeicherten Quotienten gilt eine absolute Toleranz von `1e-9`. Es gibt keine implizite Gleichsetzung von `NULL` und 0. Die SQL-Sollwerte können nicht die fachliche Aussage ersetzen, ob eine bestimmte Kennzahl freigegeben ist.

## Abgeleitete Negativfixtures

`edgecases/manifest.json` nennt je Fall die unveränderte Ursprungsquelle mit SHA256, das genaue Mutations-SQL, die abgeleitete Prüfsumme und die erwartete Fehlerart. Es handelt sich um alternative **Quellinputs für einen Kandidaten-Prüflauf**, nicht um aktive Tabellen des freigegebenen Bundles. Genau eine Quelle wird je Fall ersetzt; alle anderen bleiben unverändert.

| Fall | Mutation realer Daten | Erwartung |
|---|---|---|
| `missing_vehicle_municipality` | Alle 26 Fahrzeugzeilen für BFS 2401 Egerkingen entfernen; 2597 Zeilen verbleiben. | Vollständigkeitsprüfung erkennt die fehlende Gemeinde. Kein stilles Ersetzen durch 0 und kein scheinbar vollständiger kantonaler Quotient. |
| `zero_population_denominator` | Die demografischen Zählwerte genau einer tatsächlichen Gemeindezeile, Egerkingen, auf 0 setzen; die Summenidentitäten bleiben konsistent. | Der Quotient für diese Gemeinde ist undefiniert, mit dem Grund Nenner 0. |
| `duplicate_population_key` | Genau die Originalzeile Egerkingen zusätzlich einfügen; 107 Zeilen. | Eindeutigkeitsprüfung verhindert die Aktivierung. |

Der Standardbuilder akzeptiert bewusst ausschliesslich den gepinnten Original-Snapshot. Ein späterer Coding-Agent soll die obigen Varianten in die Vorbereitung und ihre Gates einspeisen; er soll dafür weder die Rohdateien noch deren Originalmanifest überschreiben.
