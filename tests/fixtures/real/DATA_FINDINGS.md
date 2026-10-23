# Befunde zu den tatsächlichen Pilotdaten

Stand der Untersuchung: 23. Oktober 2026. Die vollständigen Dateien wurden zwischen 09:02:21 und 09:02:22 UTC von den öffentlichen URLs abgerufen, die in den gelieferten DuckDB-Views stehen. Der übergebene Katalog-Release ist `e4560849-cd01-4e19-ac09-11f5d3036fb1`. Alle unten genannten Zahlen stammen aus den beigefügten Originaldateien und den ausführbaren SQL-Abfragen, nicht aus Beispielannahmen.

## 1. Quellen und Nachweise

Die Base-URL der neun Dateien lautet `https://s3.eu-central-1.amazonaws.com/ch.so.daten-test/`. Die vollständigen URLs, HTTP-Metadaten, SHA256 und Originalschemata stehen in `manifest.json`. Die Dateien wurden vollständig und ohne Wertänderung übernommen.

| Alias | Quelldatei an der Base-URL | Zeilen | Berichtszeit / räumlicher Bezug |
|---|---|---:|---|
| `population_age` | `ch.so.bevoelkerung.gemeinde_alter_2025.parquet` | 106 | Stichtag 31.12.2025; 106 eindeutige Gemeinden. |
| `population_sex_nationality` | `ch.so.bevoelkerung.gemeinde_geschlecht_2025.parquet` | 106 | Stichtag 31.12.2025; **nur 104 eindeutige Gemeindeschlüssel**. |
| `vehicles` | `ch.so.fahrzeugbestand_2025.parquet` | 2623 | Zeitabdeckung 2025; Gemeindestand 2025; konkreter Stichtag fehlt. |
| `staff` | `ch.so.av_nachfuehrungsstatistik.personal.parquet` | 224 | Jährlich 1980–2025, nach Ausbildung; Personenbestände. |
| `revenue` | `ch.so.av_nachfuehrungsstatistik.umsatz.parquet` | 43 | Jährlich 1983–2025; nominale CHF. |
| `heating` | `ch.so.gws.gebaeude_heizung.parquet` | 106 | Stichtag und Gemeindestand 31.12.2025. |
| `building_category` | `ch.so.gws.gebaeude_kategorie.parquet` | 106 | Stichtag und Gemeindestand 31.12.2025. |
| `ebau` | `ch.so.ebau_statistik_dossiers.parquet` | 23 | Berichtsmonate November 2024 bis September 2026. |
| `taxes` | `ch.so.staatssteuerertraege_gemeinden_2025.parquet` | 104 | Kalenderjahr 2025, **Gemeindestand 2026**. |

Alle neun passenden RDF-Distributionen nennen die Lizenz-URI `http://dcat-ap.ch/vocabulary/licenses/terms_open`. Der veröffentlichte Katalog nennt `localAccessLevel=open` und das Zugriffsrecht `http://publications.europa.eu/resource/authority/access-right/PUBLIC`. Es wird daraus keine andere Lizenzbezeichnung abgeleitet. Nachweis: `manifest.json`, `metadata_excerpts.json` sowie die dort mit Pfad und Prüfsumme identifizierten gelieferten Katalog-/RDF-Dateien.

Die Katalogkennung des Steuerdatasets ist `ch.so.staatssteuerertraege_gemeinden-2025`, während die Parquet-Datei den Unterstrich vor 2025 enthält. Kennungen sind exakt zu übernehmen; eine Namenskonvention ersetzt keine Metadatenzuordnung.

## 2. Bevölkerung: brauchbarer Basissnapshot und ein wirklicher Schlüsseldefekt

`population_age` enthält 106 Zeilen mit 106 eindeutigen BFS-Schlüsseln. Die Summe beträgt **293 081 Personen**, davon **146 123 Frauen**, **146 958 Männer** und **63 260 Personen ab 65 Jahren**. Die vollständigen Gemeinde- und Bezirksergebnisse stehen in `expected/population_by_municipality.csv` und `expected/population_by_district.csv`. Die kantonalen Werte stammen aus der Abfrage `population_total`.

Die vorhandenen Altersgruppen und Geschlechtstotale sind getrennte Marginalzahlen. Daraus lassen sich beispielsweise Personen ab 65 Jahren und Frauen insgesamt berechnen. Die Zahl der Frauen ab 65 Jahren ist damit nicht beobachtet. Eine Schätzung unter einer Unabhängigkeitsannahme wäre ein anderes Produkt mit eigenständiger Kennzeichnung und ist nicht Bestandteil dieser Fixtures.

Die zweite Datei `population_sex_nationality` enthält tatsächlich gemeinsame Zählungen nach Geschlecht und Staatsangehörigkeit. Sie hat allerdings folgenden wirklichen Defekt:

| BFS_Nr im Original | Gemeinde im Original | Total |
|---:|---|---:|
| 2525 | Halten | 832 |
| 2525 | Kriegstetten | 1463 |
| 2525 | Oekingen | 888 |

Die Altersdatei führt die entsprechenden Gemeindezeilen unter **2520**, **2525** und **2529**. Beide Dateien haben dieselbe kantonale Bevölkerungssumme. Ein reiner Totalvergleich würde den Fehler daher übersehen. Ein Join auf BFS_Nr könnte Bevölkerung vervielfachen oder den falschen Gemeinden zuordnen.

**Konsequenz für den Pilot:** `population_age` liefert die freigegebene Basis. Die unveränderte Geschlecht-/Staatsangehörigkeitsdatei dient als realer negativer Test: Eindeutigkeitsprüfung muss scheitern. Keine Reparatur anhand von Namen, keine automatische Uminterpretation als korrekte Geografie 2026. Nachweise: `quality_duplicate_population_sex_keys`, `quality_fusion_context`, beide Rohdateien.

## 3. Fahrzeuge: Kategorienfilter sind möglich, exakter Beobachtungsstichtag bleibt offen

Die Fahrzeugdaten enthalten 2623 eindeutige Kombinationen aus Gemeinde und Fahrzeugart, verteilt auf 106 Gemeinden und 42 Fahrzeugarten. `FZART_CD` ist eine Zeichenkette. Der tatsächliche Code der Personenwagen ist **`"01"`**, jener der Motorräder **`"60"`**. Beide kommen in allen 106 Gemeinden vor. Andere Arten sind deutlich seltener beobachtet; aus einer fehlenden Kategoriezeile darf ohne bestätigte Quellkonvention nicht automatisch ein Wert 0 entstehen.

Die Originalfelder `Anzahl` und `Anzahl_ohne_WS` sind verschiedene Grössen. Gemäss Beschreibung zählt das erste einzelne immatrikulierte Fahrzeuge, das zweite Zulassungen unter Berücksichtigung von Wechselschildern. Die Datei enthält keine Nullwerte in diesen Zählspalten und keine Zeilen mit Anzahl 0.

| Grösse | Istwert des Snapshots |
|---|---:|
| Einzelne Fahrzeuge, alle Arten | 239 579 |
| Zulassungen unter Berücksichtigung von Wechselschildern | 222 836 |
| Personenwagen, Code 01 | 168 245 |
| Motorräder, Code 60 | 22 164 |
| Personenwagen und Motorräder zusammen | 190 409 |
| Personenwagen pro 1000 Einwohner, arithmetische Vergleichszahl | 574.0563189016005 |
| Personenwagen und Motorräder pro 1000 Einwohner, arithmetische Vergleichszahl | 649.6804637625776 |

Nachweise: `vehicles_total`, `vehicles_by_category`, `canton_vehicle_ratios`. Für jede Gemeinde und jeden Bezirk liegen vollständige erwartete Ergebnisse vor. Beispiel Egerkingen, BFS 2401: 4362 Personen, 3869 Fahrzeuge insgesamt, 2706 Personenwagen, 2917 Personenwagen plus Motorräder. Die entsprechenden Quotienten betragen 620.3576341127923 beziehungsweise 668.7299403943146 pro 1000 Personen.

**Der genaue Fahrzeugstichtag ist nicht belegt.** Die gelieferten Metadaten nennen 01.01.2025–31.12.2025 als Zeitabdeckung und erwähnen einen Bestand «per Stichtag», nennen aber keinen konkreten Tag. Das Fixture setzt deshalb `report_year=2025`, `reference_date=NULL`. Sein `period_start=2025-01-01` ist ausschliesslich ein technischer Jahresschlüssel.

Ein strikter Vergleich desselben Stichtags mit der Bevölkerung vom 31.12.2025 ist damit nicht bestätigt. Die obigen Zahlen bleiben nützlich, um Gruppierung, Voraggregation, Filterreichweite und Nennerverwendung zu testen. Sie sind keine stillschweigende fachliche Freigabe eines Stichtagsvergleichs. Die Spezifikation muss unterscheiden, ob gleiche Berichtsperiode mit Hinweis genügt oder exakt gleicher Stichtag gefordert ist.

Ein naiver Join aller Fahrzeugzeilen mit der Gemeinde-Bevölkerung ergibt die falsche Bevölkerungssumme **8 309 998**. Die korrekte Summe bleibt **293 081**. Ein Fahrzeugartenfilter soll den Zähler auf beispielsweise Personenwagen einschränken, ohne Bewohner als Personenwagenbesitzer umzudeuten oder den Nenner an der Anzahl Fahrzeugzeilen zu vervielfachen. Ein expliziter kantonaler Bevölkerungsnenner darf pro Fahrzeugart als identische Referenz erscheinen. Das weist keine Einwohner einer Fahrzeugart zu und darf nicht über die Fahrzeugarten erneut summiert werden. Nachweise: `negative_control_naive_population_vehicle_join`, `fixed_population_denominator_by_category`.

## 4. Personal und Umsatz: Jahreswerte mit verschiedenen Dimensionen

Personal liegt für alle 46 Jahre 1980–2025 vor. Umsatz liegt für alle 43 Jahre 1983–2025 vor. Für 1980–1982 ist der Umsatz **fehlend**, nicht 0. Der richtige gemeinsame Vergleich beginnt 1983; eine Personalreihe mit linkem Join behält die früheren Personalwerte und weist fehlenden Umsatz aus. Nachweis: `staff_revenue_by_year`.

Die Personalspalte zählt Mitarbeitende. Ein FTE-/Vollzeitäquivalent ist nicht dokumentiert. Die Ausbildungsgruppen ändern sich über die lange Zeitreihe: `Geometerkandidat` endet 1988, `Ingenieur-Geometer` endet 1990, `Patentierter Ingenieur-Geometer` beginnt 1991 und `Ingenieur ETH` beginnt 1995. Eine feste heutige Kategorienliste für alle Jahre wäre falsch. Die Originaldaten enthalten für 2025: Geomatiker 25, Ingenieur ETH 1, Lernende 13, Patentierter Ingenieur-Geometer 9, Techniker HTL / FH / FA 17. Nachweise: `raw/staff.parquet`, `staff_2025_by_education`.

| Jahr | Mitarbeitende gesamt | Nominaler Umsatz CHF | Nominaler Umsatz je Mitarbeitenden CHF |
|---:|---:|---:|---:|
| 2024 | 66 | 2 566 066.00 | 38 879.78787878788 |
| 2025 | 65 | 2 762 610.00 | 42 501.692307692305 |

Der Mittelwert der jährlichen Gesamtbestände 2024 und 2025 ist **65.5**. Der Mittelwert aller zehn Ausbildungszeilen ist **13.1** und beantwortet diese Frage nicht. Die Summe der Jahresbestände **131** ist kein Personalbestand für den Zeitraum. Umsatz dagegen ist ein Jahresfluss und kann bei passender Frage über Jahre summiert werden. Nachweise: `staff_average_of_annual_totals_2024_2025`, `negative_control_average_staff_rows_2024_2025`.

Der Umsatz ist in der Beschreibung ausdrücklich **nominal und nicht inflationsbereinigt**. Nominales Wachstum 2025 gegenüber 2024: **7.659350928619912 %**; nominaler Umsatz je Mitarbeitenden: **9.315648635214057 %** Wachstum. Diese Werte dürfen nicht als reale Produktivitätssteigerung ausgegeben werden. Der gleiche Umsatzwert in 2023 und 2025 bleibt unverändert; aus dem Gleichstand allein wird kein Fehler abgeleitet. Nachweis: `nominal_growth_2025`, `metadata_excerpts.json#revenue`.

Umsatz hat keine Ausbildungsdimension. Eine Frage nach «Umsatz der Geomatiker» kann nicht aus dieser Quelle beantwortet werden. Ein ausdrücklich definierter Quotient «Gesamtumsatz geteilt durch Anzahl Geomatiker» wäre eine andere Kennzahl mit Gesamtumsatz als konstantem Zähler und ausgewähltem Personal als Nenner. Sie darf weder als Umsatzzuordnung noch als Erlösbeitrag dieser Gruppe bezeichnet werden. Die Präzisierung betrifft die Rolle von Dimensionen und Filtern, nicht das Vorhandensein einer SQL-Rechenoperation.

Ein naiver Join Umsatz ↔ fünf Personalgruppen und anschliessendes Summieren ergibt für 2025 den falschen Umsatz **13 813 050.00 CHF**. Voraggregation des Personals auf Jahr erhält den richtigen Umsatz **2 762 610.00 CHF**. Nachweis: `negative_control_naive_staff_revenue_join_2025`.

## 5. GWS: passende Bestände, aber kein gemeinsamer Kategorie-Heizung-Schnitt

Beide GWS-Dateien enthalten dieselben 106 Gemeinden, 2025 als Datenjahr und laut Metadaten Bestand/Gemeindestand per 31.12.2025. Die Gebäude-Gesamtsummen stimmen je Gemeinde zwischen den Dateien überein. Kantonal sind es **71 248 Gebäude**, davon **19 530 mit Wärmepumpe**. Der gewichtete kantonale Anteil beträgt **27.411295755670334 %**. Nachweise: `heating_total`, `heating_by_district`, beide Rohdateien.

Die Datei zur Gebäudekategorie und jene zur Heizung sind getrennte Marginaltabellen. «Anteil Wärmepumpen an allen Gebäuden» ist berechenbar. «Wie viele Einfamilienhäuser haben eine Wärmepumpe?» ist aus diesen Quellen nicht beobachtet. Ein Join über Gemeinde erzeugt die fehlende Kreuzklassifikation nicht. Übereinstimmende Totale ändern diese Informationsgrenze nicht.

## 6. Steuerdaten: identisches Berichtsjahr bedeutet keine identische Geografie

Die Steuerquelle beschreibt ausdrücklich Kalenderjahr 2025 mit **Gemeindestand 2026, 104 Gemeinden**, gerundete TCHF. Die GWS-Metadaten erwähnen die Fusion von Halten und Oekingen mit Kriegstetten per 01.01.2026. Die Steuerdatei enthält keine getrennten Zeilen für Halten 2520 und Oekingen 2529. Sie enthält weiterhin den Schlüssel 2525 für Kriegstetten, nun aber im neuen räumlichen Zusammenhang.

In den Bevölkerungsdaten 2025 hat Halten 832, Oekingen 888 und das damalige Kriegstetten 1463 Einwohner. Die Steuerzeile 2525 enthält 8999 TCHF. Ein Join allein nach 2525 würde deshalb stillschweigend unterschiedliche Gebiete verknüpfen. Ein bloßer Check auf übereinstimmende Schlüsselwerte oder Jahreszahlen genügt nicht.

**Konsequenz:** `geo_version` gehört zur Vergleichbarkeitsprüfung und zum räumlichen Beziehungsschlüssel. Keine automatische Brücke anhand gleicher Gemeinde-IDs und keine stillschweigende Fusion der Bevölkerungswerte. Ein freigegebener historischer Gebietsschlüssel/Crosswalk wäre eine zusätzliche Grundlage. Die Steuerfixture dient hier dem Nachweis, dass diese Grenze erkannt wird. Nachweise: `quality_tax_geography_difference`, `quality_fusion_context`, `metadata_excerpts.json#taxes`, `metadata_excerpts.json#heating`.

## 7. eBau: ein Datum als Monatsschlüssel, eine unvollständige erste Periode

Die 23 Monatszeilen reichen lückenlos von November 2024 bis September 2026. `berichtsmonat` ist jeweils der Monatserste und bezeichnet gemäss Beschreibung den ganzen Berichtsmonat, keinen Erhebungsstichtag. Die eingereichten Dossiers sind Monatsflüsse; die beteiligten Gemeinden sind Monatsbestände. Beide Kennzahlen benötigen verschiedene Zeitaggregation.

Das vierte Quartal 2024 enthält nur November und Dezember. Die vorhandenen Monate ergeben **48 Dossiers**, bei **6 Gemeinden im letzten vorhandenen Monat**. Die 48 dürfen nicht als vollständige Quartalssumme bezeichnet werden. Q1 2025 enthält alle drei Monate und **170 Dossiers**, bei ebenfalls 6 Gemeinden im letzten Monat. Im letzten vorhandenen Monat September 2026 stehen 64 Gemeinden und 447 eingereichte Dossiers. Nachweise: `ebau_by_quarter`, `raw/ebau.parquet`, `metadata_excerpts.json#ebau`.

## 8. Abnahmeschwerpunkte aus diesen echten Daten

Diese Quellen ermöglichen ohne erfundene Hauptfixtures die Prüfung der wichtigsten fachlichen Fehlerarten:

1. Bevölkerungs-, Fahrzeug-, Personal- und Umsatzsummen treffen die vollständigen SQL-Sollwerte auf allen vorhandenen Gemeinden, Bezirken und Jahren.
2. Aggregation mehrerer Fakten vervielfacht keine Bestände oder Umsätze; die belegten falschen Roh-Join-Ergebnisse werden nicht reproduziert.
3. Der Filter Fahrzeugart 01 beziehungsweise 01+60 verändert nur die gewünschte Fahrzeugkennzahl; ein ausdrücklich definierter Gesamtbevölkerungsnenner bleibt korrekt.
4. Unterschiedliche Körnungen erlauben eindeutige Referenznenner/-zähler, behaupten aber keine nicht vorhandene fachliche Zuordnung.
5. Ein geforderter genauer Fahrzeugstichtag bleibt wegen fehlender Quelle unbestätigt.
6. Jahresbestände werden nicht über Jahre summiert; der Mittelwert wird nach Bildung der jeweiligen Jahresgesamtsumme berechnet.
7. Fehlende Umsatzjahre bleiben fehlend. Nominalbeträge und Personenzahlen bleiben entsprechend bezeichnet.
8. Der reale doppelte Gemeindeschlüssel der Geschlechtsdatei verhindert deren Aktivierung.
9. Gemeindestand 2026 der Steuerquelle wird trotz Berichtsjahr 2025 und teilweise gleicher Schlüssel erkannt.
10. Alter × Geschlecht und Gebäudekategorie × Heizung werden nicht als beobachtete Kreuzklassifikation ausgegeben.
11. Unvollständige eBau-Quartale werden erkannt; Gemeindebestände werden nicht monatlich aufsummiert.
12. Die drei gesondert dokumentierten Mutationsfixtures prüfen fehlende Gemeindedeckung, Nenner 0 und einen zusätzlichen doppelten Schlüssel, ohne Rohdaten zu verändern.

Das Fixture-Bundle macht diese Fälle reproduzierbar. Es enthält keine stillen Quellenkorrekturen und keine fachliche Freigabe von Verknüpfungen allein deshalb, weil eine Datenbank sie ausführen könnte.
