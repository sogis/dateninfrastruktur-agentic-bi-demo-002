# Reale Testdaten und Abnahme

## 1 Verbindliche Testgrundlage

Das Paket enthält **neun vollständige unveränderte Parquet-Dateien**, zusammen 55’119 Bytes, aus den Quellenverweisen des vom Benutzer gelieferten Katalogs. Es ist keine künstliche Hauptfixture und keine Stichprobe. Die 106 Gemeinden und alle vorhandenen Jahre der gewählten Quellen bleiben enthalten.

Katalogrelease: `e4560849-cd01-4e19-ac09-11f5d3036fb1`. Abruf der Dateien: 23. Oktober 2026, 09:02:21–09:02:22 UTC. Die URLs liegen unter `https://s3.eu-central-1.amazonaws.com/ch.so.daten-test/`. Ihre Herkunft wird so dokumentiert; aus dem Test-Bucket wird keine zusätzliche Behauptung über einen amtlich bestätigten produktiven Publikationsstand abgeleitet.

`tests/fixtures/real/manifest.json` enthält je Original URL, Abrufzeit, SHA-256, Dateigrösse, Spalten, Zeilenanzahl und Herkunft der Zeit-/Lizenzangaben. Die passenden gelieferten RDF-Distributionen nennen `http://dcat-ap.ch/vocabulary/licenses/terms_open`. `metadata_excerpts.json` enthält die relevanten gelieferten Beschreibungen. Kataloge dienen hier der Herkunft und dem Datenverständnis, nicht als vorgeschriebene Runtime-Importschnittstelle.

### 1.1 Enthaltene Quellen

| Alias | Originalzeilen | Einbezug in V1 |
|---|---:|---|
| `population_age` | 106 | Kanonische Bevölkerung 2025, aktive Kernquelle |
| `population_sex_nationality` | 106 | Realer Schlüsselfehler; unverändert als Quarantänetest |
| `vehicles` | 2’623 | Aktive Kernquelle, 42 Fahrzeugarten, 106 Gemeinden |
| `staff` | 224 | Aktive Kernquelle, Jahresbestände 1980–2025 nach Ausbildung |
| `revenue` | 43 | Aktive Kernquelle, nominale Jahresumsätze 1983–2025 |
| `heating` | 106 | Einfache zusätzliche Bestandsquelle 2025 |
| `building_category` | 106 | Einfache zusätzliche Bestandsquelle 2025 |
| `taxes` | 104 | Vergleichs-/Negativfixture: Berichtsjahr 2025, Gebietsstand 2026 |
| `ebau` | 23 | Monatsdaten November 2024 bis September 2026; späterer Umfang |

Die GWS-Modelle sollen als kleine Erweiterung mit demselben Mechanismus umgesetzt werden, sobald die Kernfälle funktionieren. Steuern und eBau bleiben mit erklärtem Status inspizierbar, werden in V1 aber nicht queryfähig registriert. Die normale Anfrage auf eine bekannte ausgeschlossene Kennzahl ergibt deshalb `E_MODEL_UNAVAILABLE`. Die zugrunde liegenden fachlichen Regeln werden zusätzlich in isolierten Compiler-/Authoringtests nachgewiesen: Geografiegrenze `E_INCOMPATIBLE_POPULATION`, nicht jährliche Zeitform `E_UNSUPPORTED_PERIOD`.

### 1.2 Dateien des Testpakets

| Pfad unter `tests/fixtures/real/` | Zweck |
|---|---|
| `raw/` | Originale, unveränderliche Testeingaben |
| `manifest.json`, `metadata_excerpts.json`, `catalogue_metadata.json` | Provenienz und beschreibende Quellinformationen |
| `fixture_build.py` | Expliziter Aufbau kanonischer physischer Tabellen |
| `normalized/pilot.duckdb` | Bereits gebautes Testbundle mit DuckDB 2.0.0 |
| `normalized/pilot.schema.json` | Jede Spalte, jeder SQL-Typ, alle Schlüssel und Ableitungs-SQLs |
| `reference_queries.sql`, `run_reference.py` | 24 unabhängige Abfragen direkt auf Originalen, ohne SLayer |
| `expected_results.json`, `expected/*.csv` | Vollständige erwartete Ergebnisse |
| `verify_normalized.py`, `normalized/verification.json` | Vergleich der Normalisierung mit den Rohdaten-Orakeln |
| `author_invariants.sql` | 18 konkrete Baseline-Invarianten |
| `edgecases/`, `build_edgecases.py` | Drei gekennzeichnete Mutationen mit Herkunft und Hash |
| `README.md`, `DATA_FINDINGS.md` | Ausführliche Datenbefunde und Reproduktionsbefehle |

Die Quelldaten sind normativ. Die fertige DuckDB-Datei ist eine bequeme reproduzierbare Ableitung. Ein erneuter Build kann eine andere binäre Dateiprüfsumme erhalten; entscheidend sind unveränderte Rohhashes, die dokumentierten Ableitungen und gleiche Tabelleninhalte. Für einen Build mit anderer freigegebener DuckDB-Version zuerst aus `raw/` neu erzeugen und die Sollwerte erneut prüfen.

## 2 Der reale Schlüsselfehler muss erhalten bleiben

Die Datei nach Geschlecht/Staatsangehörigkeit enthält 106 Zeilen, aber nur 104 eindeutige BFS-Schlüssel:

| BFS-Schlüssel im Original | Gemeinde | Total |
|---:|---|---:|
| 2525 | Halten | 832 |
| 2525 | Kriegstetten | 1’463 |
| 2525 | Oekingen | 888 |

Die Altersdatei führt die Gemeinden unter 2520, 2525 und 2529. Beide Dateien haben trotzdem dieselbe kantonale Bevölkerungssumme. Ein Test nur der Gesamtsumme würde den Defekt übersehen.

**MUSS:** Qualitätsprüfung erkennt den mehrfachen Schlüssel; Quelle erhält `quarantined`; Original bleibt erhalten; `inspect` erklärt den Grund; `analyse` kann sie nicht durch eine andere ID, einen nativen Pfad oder ein Inline-Modell nutzen. Der übrige Pilot bleibt bereit. Keine automatische Korrektur nach Namen.

## 3 Unabhängige Sollwerte

Die folgenden Werte stammen aus den beiliegenden SQL-Orakeln. Gezählt und monetär exakt vergleichen; Floatquotienten mit absoluter Toleranz `1e-9`, relative Toleranz 0. NULL und 0 sind niemals äquivalent. Zeilen vor dem Vergleich deterministisch nach Schlüsseln sortieren; Spalten nach explizitem Namen zuordnen.

Die Bezirksorakel verwenden Bezirksnamen, während der öffentliche Vertrag `district` als Integer-Schlüssel ausgibt. Der Testadapter bildet die eindeutigen Orakelnamen über die geprüfte Zuordnung `municipalities.district_name → district_id` auf IDs ab und vergleicht danach. Dieser Adapter ändert keine Zahlen und darf keine fehlende oder mehrdeutige Zuordnung still hinnehmen.

| Grösse | Erwarteter Wert |
|---|---:|
| Bevölkerung 2025 | 293’081 |
| Frauen / Männer | 146’123 / 146’958 |
| Personen ab 65 Jahren | 63’260 |
| Einzelne Fahrzeuge, alle Arten | 239’579 |
| Zulassungen unter Berücksichtigung von Wechselschildern | 222’836 |
| Personenwagen `"01"` | 168’245 |
| Motorräder `"60"` | 22’164 |
| Personenwagen + Motorräder | 190’409 |
| Personenwagen pro 1’000 Einwohner | 574.0563189016005 |
| Personenwagen + Motorräder pro 1’000 Einwohner | 649.6804637625776 |
| Personal 2024 / 2025 | 66 / 65 |
| Nominaler Umsatz 2024 / 2025 | CHF 2’566’066.00 / CHF 2’762’610.00 |
| Nominaler Umsatz je Mitarbeiter 2024 | 38’879.78787878788 |
| Nominaler Umsatz je Mitarbeiter 2025 | 42’501.692307692305 |
| Durchschnitt Jahrestotal Personal 2024–2025 | 65.5 |
| Nominales Umsatzwachstum 2025 in Prozent | 7.659350928619912 |
| Wachstum nominaler Umsatz je Mitarbeiter in Prozent | 9.315648635214057 |
| Gebäude / Gebäude mit Wärmepumpe | 71’248 / 19’530 |
| Wärmepumpenanteil in Prozent | 27.411295755670334 |

Prozent-Sollwerte aus den SQL-Orakeln bei `PeriodNode(relative_change)` durch 100 mit der erwarteten dimensionslosen Ergebnisdarstellung vergleichen. Der Test darf den tatsächlichen Ergebniswert nicht erst passend skalieren; der Vertrag verlangt einen dimensionslosen Quotienten, dessen Format Prozent ist.

Die Fahrzeug-/Bevölkerungsquotienten sind gültige Rechenorakel unter der erlaubten Berichtsjahrbetrachtung mit Hinweis. Sie belegen keinen identischen Beobachtungsstichtag. Die native Decimal-Klassifikation muss wie in Dokument 02 beschrieben `db_type=DECIMAL(18,2)` erhalten.

### Absichtlich falsche Kontrollzahlen

| Fehlerhafte Berechnung | Falsches Ergebnis | Erwartete richtige Reaktion |
|---|---:|---|
| Bevölkerung über alle Fahrzeugzeilen joinen und summieren | 8’309’998 | Population bleibt 293’081 |
| Umsatz 2025 über fünf Ausbildungsgruppen joinen und summieren | CHF 13’813’050.00 | Umsatz bleibt CHF 2’762’610.00 |
| Durchschnitt über zehn Personal-Ausbildungszeilen 2024/25 | 13.1 | Durchschnitt der Jahrestotale ist 65.5 |
| Personalbestände 2024 und 2025 addieren | 131 | Zeitraum-Bestandssumme wird abgewiesen |

`negative_control_*`-Ergebnisse sind keine Sollantworten. Die Tests müssen sie bewusst vom fachlich richtigen Ergebnis unterscheiden.

## 4 Datenqualität vor Modellfreigabe

Folgende Prüfungen sind zwingend, als direkte konkrete SQL-/Pythonprüfungen im Authoring. Keine Validatorhierarchie bauen.

1. Originalhashes stimmen; dokumentierte Quellspalten und Typen sind vorhanden. Dateiname allein bestimmt weder Jahr noch Geografie.
2. Sämtliche deklarierten Schlüssel sind eindeutig und nicht NULL. Das gilt insbesondere für Gemeinde/Jahr/Gebietsstand sowie Fahrzeugart und Ausbildung.
3. Jede Gemeinde hat genau eine Bezirkzuordnung. Jede aktive kommunale Faktzeile verweist auf eine vorhandene kompatible Grundzelle. Keine unbeabsichtigten Join-Orphans.
4. Pflichtkennzahlen sind nicht NULL; Zählwerte sind nicht negativ. Umsatzwerte lassen sich mit höchstens zwei Dezimalstellen ohne unbemerkten Informationsverlust normalisieren.
5. Bevölkerung = Frauen + Männer = Schweizer + Ausländer = Summe der fünf disjunkten Altersgruppen. `age_65_plus` entspricht den beiden ältesten Gruppen.
6. Die Heizungsgruppen und Gebäudekategorien ergeben je Gemeinde ihr jeweiliges Total. Beide Gebäude-Totale stimmen überein. Das beweist weiterhin keine gemeinsame Kategorie-Heizungsverteilung.
7. Technischer Jahresbucket ist exakt der 1. Januar des Berichtsjahres. Beobachtungsstichtag wird getrennt geprüft. Fahrzeuge behalten `reference_date=NULL`.
8. Geografie 2025 und 2026 bleiben verschieden. Gleicher BFS-Code rechtfertigt keinen Join über den Gebietsstand hinweg.
9. Tatsächliche Jahre, kleine Kategorienlisten und vollständige Kategorieabdeckungen werden gemessen, nicht behauptet. Ausbildungsgruppen dürfen über die lange AV-Zeitreihe wechseln.
10. Die vorbereitete Runtime-Datenbank enthält nur physische Tabellen; keine HTTP-/Parquet-Views und keine clientdefinierte Datenquelle.

Die beigefügten 18 Baseline-Prüfungen sollen für das unveränderte Ausgangsbundle alle 0 Verletzungen liefern. Sie sind kein vollständiger allgemeiner Qualitätsstandard: beispielsweise ergänzt die Implementation explizite Pflicht-NULL-Prüfungen aller aktiven Kennzahlen. Im allgemeinen Statusbericht sind Schlüssel-/Typ-/Orphanfehler hart, gemessene Abdeckungslücken separat sichtbar. Ein kontrollierter Test darf eine solche Lücke bis zur Compiler-/Ergebnisprüfung einspeisen, ohne sie als unveränderten produktiven Referenzsnapshot auszugeben.

## 5 Verbindliche funktionale Abnahmematrix

Die IDs sind stabile Testnamen. Parametrisieren, wo mehrere Fälle dieselbe Regel prüfen. Keine Klasse pro Testfall. Tests dürfen einen direkten Compiler-/Enginepfad verwenden; mindestens der vollständige MCP-Ende-zu-Ende-Fall muss den echten Runtime-/Workerpfad benutzen.

### 5.1 Positive und numerische Fälle

| ID | Eingabe/Prüfung | Erwartung / Referenz |
|---|---|---|
| F01 | Bevölkerung kantonal und nach Gemeinde | Exakte Summen; alle 106 Zeilen gegen `population_by_municipality` |
| F02 | Bevölkerung und Fahrzeuge gemeinsam nach Gemeinde | Alle 106 Zeilen gegen `population_vehicles_by_municipality`; keine Vervielfachung |
| F03 | Dieselbe Kombination nach Bezirk | Alle zehn Zeilen gegen `population_vehicles_by_district` |
| F04 | Fahrzeugzähler lokal `category in ["01","60"]`, Bevölkerungsnenner | 190’409 / 293’081 × 1’000; Nenner unverändert |
| F05 | Dieselbe Quote pro Gemeinde | Vollständige 106 Ergebnisse; Egerkingen z.B. 668.7299403943146 |
| F06 | Fahrzeugart im Ausgabegrain, Bevölkerungsnenner `grain=[]` | Alle 42 Arten mit konstantem kantonalem Nenner; Kategorie-Abdeckungshinweise korrekt |
| F07 | Nur Personenwagen `"01"` | Führende Null bleibt erhalten; Total 168’245, Quote 574.0563189016005 |
| F08 | Personal, nominaler Umsatz und Verhältnis nach Jahr 2024/25 | Genau zwei Jahre, 66/65 Mitarbeitende, exakte Geldstrings, richtige Quotienten |
| F09 | Mittel der Personal-Jahrestotale 2024/25 | 65.5; weder 13.1 noch 131 |
| F10 | Nominaler Umsatz über 2024/25 summiert | CHF 5’328’676.00, Jahresfluss-Summe zulässig |
| F11 | Nominales Umsatzwachstum 2025 zum Vorjahr | Richtiger dimensionsloser Wert, intern Scan 2024/25, öffentlich nur 2025 |
| F12 | Wachstum Umsatz je Mitarbeiter 2025 | Richtiger zusammengesetzter Vergleich; Vorjahresnenner korrekt |
| F13 | Personal nach Ausbildung 2025 | Fünf Gruppen: 25, 1, 13, 9, 17 gemäss vollständigem Oracle |
| F14 | Wärmepumpenanteil kantonal und nach Bezirk | Verhältnis der aggregierten Summen; kein ungewichteter Mittelwert der Gemeindequoten |
| F15 | Gemeinsamer Raumfilter, z.B. Gemeinde 2401 | Filter wirkt identisch auf alle Blätter und Nenner, keine Namensauflösung durch Raten |
| F16 | Jahresmittel nach faktlokaler Ausbildung | Innere Partition enthält Ausbildung und Jahr; gegen unabhängige SQL-Abfrage auf realen Daten prüfen |

### 5.2 Fachliche Ablehnungen und begrenzte Interpretation

| ID | Fall | Erwartung |
|---|---|---|
| N01 | Bevölkerung aus gesperrter Geschlecht-/Nationalitätsquelle | `E_MODEL_UNAVAILABLE`, DUPLICATE_KEY-Grund |
| N02 | Strenge Stichtagsgleichheit Bevölkerung/Fahrzeuge | `E_REFERENCE_DATE_UNKNOWN` |
| N03 | Globaler Fahrzeugartenfilter | `E_GLOBAL_FILTER_NOT_SHARED`; keine implizite EXISTS-Populationsänderung |
| N04 | Umsatz nach Ausbildung ohne ausdrücklichen zulässigen Bezug | `E_CROSS_CLASSIFICATION_UNAVAILABLE` beziehungsweise Grainfehler vor nativer Ausführung |
| N05 | Personalbestand über zwei Jahre einfach summieren | `E_TIME_AGGREGATION_NOT_ALLOWED` |
| N06 | Datenwert × Datenwert; zusätzlich a/(b/c) als Umgehung | `E_UNSUPPORTED_PRODUCT` / `E_UNSUPPORTED_DENOMINATOR` |
| N07 | Nicht vorhandener Schnitt Frauen × Alter oder Gebäudekategorie × Heizung | Unbekannte Kennzahl/Dimension oder unzulässige Faktkombination; keine geschätzte Beobachtung |
| N08 | Unterschied zweier verfügbarer Marginalzahlen mit irreführender Output-ID | Berechnung darf zulässig sein; Label und Formel bleiben automatisch und `nature=calculated`, keine übernommene Bedeutung der ID |
| N09 | Unzulässige Addition verschiedener Einheiten | `E_UNIT_MISMATCH` |
| N10 | Explizit gröberer Normaloutput | `E_REFERENCE_ONLY_DENOMINATOR` |
| N11 | Unsichtbares Hilfsjahr und explizites gröberes Nennergrain | Intern bleibt Jahr erhalten; Vergleich darf niemals mehrere Jahresbestände im Nenner summieren |
| N12 | Öffentliche Jahresserie, expliziter Nenner ohne year | Definierter Grain-/Zeitfehler |
| N13 | Jahresmittel mit PeriodNode im selben Request | `E_UNSUPPORTED_TEMPORAL_COMPOSITION` |
| N14 | Fixes Basisjahr für mehrere sichtbare Jahre | `E_UNSUPPORTED_FIXED_BASE_SERIES` |
| N15 | Sichtbarer Umsatz 1980–1982 | `E_PERIOD_UNAVAILABLE`; fehlender Umsatz ist nicht 0 |
| N16 | Steuerdaten mit 2025er Bevölkerung verbinden | Quelle in V1 gesperrt; separate Kompatibilitätsprüfung lehnt Geografie 2026↔2025 ab |
| N17 | eBau als Jahres-/Quartalsmodell im V1-Vertrag | Quelle nicht freigegeben; keine fingierte Vollperiodensumme |

### 5.3 Gezielte Randfälle mit abgeleiteten Daten

Die Originale bleiben unangetastet. Mutationen erhalten eigene Pfade, Hashes und Testnamen. Der normale Builder akzeptiert sie nicht still als Originalmanifest. Für Tests einen klaren Quelloverride im Testaufbau oder eine separate temporäre DB verwenden; kein öffentliches Override-Werkzeug implementieren.

| ID | Fixture | Erwartung |
|---|---|---|
| M01 | `duplicate_population_key.parquet`: Egerkingen einmal zusätzlich | 107 Zeilen; Kernschlüsselprüfung scheitert, Readiness bleibt falsch |
| M02 | `zero_population_denominator.parquet`: alle demografischen Werte Egerkingens 0 | Summenidentitäten bleiben gültig; Quote NULL mit `ZERO_DENOMINATOR`, andere Gemeinden unverändert |
| M03 | `missing_vehicle_municipality.parquet`: 26 Egerkinger Fahrzeugzeilen fehlen | 2’597 Zeilen; Abdeckungslücke erkannt, kein 0-Bestand; im kontrollierten Ergebnistest betroffene Gemeinde-/Kantonwerte NULL mit Grund |
| M04 | Ein benötigtes AV-Vorjahr entfernen | Vergleich NULL mit `MISSING_BASE_PERIOD`; aktueller unabhängiger Wert bleibt vorhanden |
| M05 | Eine Jahresbeobachtung in einem Mittelwert entfernen | Native AVG über Restjahre wird nicht als vollständiges Mittel ausgegeben; `MISSING_YEAR_COVERAGE` |
| M06 | Vorjahreswert für relative Änderung auf 0 setzen | `ZERO_DENOMINATOR` auch bei intern erzeugter Period-Division |
| M07 | Nur Vorjahres-Grundzelle eines Fakts entfernen | Verschobener Coverage-Check erkennt die Lücke; heutige Vollständigkeit reicht nicht |
| M08 | Lokale Kategorieauswahl ohne Treffer | Kein erfundener 0-Wert; NULL mit `NO_MATCHING_OBSERVATIONS` oder leeres Ergebnis, je tatsächlichem Grain |
| M09 | Filterliteral mit Quote, Backslash oder DSL-ähnlichem Text | Bleibt exakt ein Literal; keine zusätzliche Referenz/Operation; kein Querytext aus Stringkonkatenation |

M01–M03 sind als tatsächliche abgeleitete Dateien enthalten. M04–M09 benötigen nur kleine gezielte Testaufbauten auf Kopien vorhandener Daten beziehungsweise eine kleine Literalfixture; daraus keine neue grosse synthetische Datenlandschaft bauen.

### 5.4 Betriebs- und Schnittstellenfälle

| ID | Prüfung | Nachweis |
|---|---|---|
| B01 | MCP initialize, tools/list, tools/call | Genau `search`, `inspect`, `analyse`; korrektes tatsächliches JSON-Schema und `structuredContent` |
| B02 | Echte MCP-Analyse F04 | Durch Server, Unterprozess, Compiler und unveränderte native Engine; exakter Wert plus Zeitwarnung |
| B03 | Optionaler Quarantänefehler | Ready bleibt true; gesperrte Quelle inspizierbar, andere Analysen funktionieren |
| B04 | Fehlerhafte Kernquelle | Ready 503, Analyse `E_NOT_READY`, Health weiterhin ansprechbar |
| B05 | Aktiver echter Worker, zweiter Analyseaufruf | Sofort `E_BUSY`, kein zweiter Kindprozess und keine Queue |
| B06 | Wirklich laufende lange DuckDB-Abfrage | Nach Frist Prozessgruppe beendet und Prozess geerntet; anschliessend neue Analyse möglich |
| B07 | Nur Worker-eigener Alarm | Auch ohne Supervisor-Kill beendet der OS-Alarm die lange Abfrage |
| B08 | Cancellation/Shutdown bei aktiver Analyse | Cleanup abgeschlossen, Kind beendet, kein zu früh freier Slot |
| B09 | Unerwarteter Workerexit/ungültige oder übergrosse Ergebnisdatei | Definierter Fehler, kein Dateileck, keine rohe Exceptionantwort |
| B10 | Hardcap 10’000/10’001 interne Zeilen, öffentliches Limit | Vollständige Rechnung vor Limit; Überschreitung ergibt Fehler ohne scheinbar vollständige Teildaten |
| B11 | 40/41 Knoten, Tiefe, Output-/Prädikatbudget | Grenze konsistent im Vertrag und Compiler; keine Engineausführung bei Ablehnung |
| B12 | Requestgrösse >65’536 Bytes, Ergebnishülle >2 MiB | Transport 413 beziehungsweise `E_RESULT_TOO_LARGE`; tatsächliche MCP-Wiregrösse im Test dokumentiert |
| B13 | Read-only/offline-Datasource | Geprüfte Connectionsettings; CREATE wird abgewiesen; keine Runtime-Remote-Datei/Extension |
| B14 | Logs und optionaler Token | IDs/Codes/Laufzeit vorhanden; keine Tokens, kompletten Prompts, SQL-Texte oder Ergebniszeilen |
| B15 | Nicht privilegierter Container, Bundle read-only, Arbeitsvolume | Start, Readiness, echte Abfrage und Shutdown erfolgreich |

Ein Testworker für B06/B07 darf eine feste langsame SQL-Abfrage enthalten; diese Möglichkeit darf im Produktvertrag nicht existieren. Für B10/B12 kleine kontrollierte technische Testdaten erzeugen, statt den realen Quellen künstlich Millionen Zeilen anzuhängen.

## 6 Vorhandene Nachweise und noch zu leistende Abnahme

Bereits für diese Spezifikation ausgeführt:

- 24 unabhängige Rohdaten-SQL-Abfragen mit vollständigen gespeicherten Ergebnissen.
- 13 Vergleiche der normalisierten Tabellen gegen die Rohorakel, insgesamt 383 Ergebniszeilen, bestanden.
- 18 konkret verfasste Baseline-Invarianten mit 0 Verletzungen.
- Elf native SLayer-Proben auf diesen echten Daten bestanden: zehn erfolgreiche Zahlen-/Gruppierungsfälle und eine erwartete Ablehnung der Umsatzzuordnung zu Ausbildung.
- Native Detailproben für sichere Literale, explizit erweiterte Zeitfenster, Jahresmittel und vor lokalen Filtern geprüfte Quellenabdeckung.
- MCP-/Lifespan-/Bodylimitproben und tatsächlich beendete DuckDB-CPU-Abfragen.

Diese Nachweise liegen unter `evidence/`. Sie bestätigen die verwendeten nativen Bausteine und Datenstände. **Sie ersetzen nicht** die noch zu implementierenden Fassade-, Compiler-, Quarantäne-, Prozess- und Ende-zu-Ende-Abnahmetests. Der Coding-Agent muss die obige Matrix für seine konkrete Anwendung erfüllen und den Unterschied im Abschlussbericht erhalten.

## 7 Testaufbau ohne unnötige Testarchitektur

`test_authoring.py` prüft Hashes, Schemata, Invarianten und Quarantäne. `test_semantics.py` prüft fachliche Ablehnungen und gezielte Guard-/Literalrisiken. `test_real_queries.py` vergleicht die echten nativen Ergebnisse vollständig gegen die unabhängigen Orakel. `test_runtime.py` prüft Prozesse und Grenzen. `test_mcp.py` prüft den tatsächlichen Transport.

Die Dateien dürfen umbenannt oder sinnvoll zusammengelegt werden. Keine DTO-Spiegeltests, die lediglich bestätigen, dass ein Feld genauso heisst wie in der Implementierung. Keine Golden-SQL-Strings als alleinige Korrektheitsprüfung. SQL-Formatierung darf sich ändern; Zahlen, Granularität, Quellenabdeckung, Fehler und Schutzverhalten müssen erhalten bleiben.

Netzwerk ist nach Installation für den vollständigen Abnahmelauf nicht nötig. Ein erneuter Download aktualisiert niemals still die erwarteten Ergebnisse. Änderungen am Referenzstand brauchen einen neuen Snapshot, eine unabhängige Nachrechnung und eine dokumentierte fachliche Freigabe.
