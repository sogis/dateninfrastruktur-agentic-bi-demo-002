# Native SLayer-Probes mit den realen Pilotdaten

`probe_real.py` führt elf gezielte Integrationsproben über die physischen Tabellen in `../slayer_detail_data/normalized/pilot.duckdb` aus. Die Sollwerte stammen aus den unabhängigen SQL-Abfragen auf den unveränderten Quellen in `../slayer_detail_data/expected_results.json`. Alle elf Probes haben bestanden. Es wird keine produktive Anwendung und keine zweite verbindliche Registry implementiert.

```sh
python probe_real.py
python probe_real.py --data-dir /absolute/path/to/slayer_detail_data
```

Der Lauf erzeugt die nativen YAML-Modelle unter `native_models/` und die vollständigen Abfragen, Ergebnisse, erzeugten SQLs, Warnungen, Versionen und Datenprüfsummen in `results.json`. Die generierte Datasource bindet den absoluten lokalen Datenbankpfad. Nach Verschieben des Beispiels den portablen Python-Lauf erneut ausführen. Die YAMLs sind nachvollziehbare Nachweisbeispiele, nicht die Spezifikation eines zweiten Authoringformats.

| Probe | Nachweis |
|---|---|
| R01 | Bevölkerung als Wurzel und inverse Fahrzeugrelation ergeben richtige kantonale Summen. |
| R02 | Alle 106 Gemeindesummen stimmen; Bevölkerung wird nicht mit Fahrzeugzeilen vervielfacht. |
| R03 | Alle zehn Bezirkssummen über `population → municipalities` stimmen. |
| R04 | Lokaler Kennzahlfilter auf Fahrzeugcodes 01+60, kantonaler Nenner bleibt 293081. |
| R05 | Derselbe lokale Filter und korrekte Quotienten für alle 106 Gemeinden. |
| R06 | Alle 42 Fahrzeugarten mit ausdrücklich konstantem kantonalem Bevölkerungsnenner. Keine globale Filterung einer Faktentabelle. |
| R07 | Gemeinsame Wurzel `years` und inverse Relationen zu Personal/Umsatz für 2024 und 2025. |
| R08 | `AVG(SUM(Personal pro Jahr))` ergibt 65.5. |
| R09 | Nominales Umsatzwachstum 2025: Abfrageperiode 2024–2025, Vorjahresberechnung durch SLayer, Anzeigeauswahl 2025 danach. |
| R10 | Derselbe Ablauf für nominalen Umsatz je Mitarbeitenden. |
| R11 | Implizite Zuordnung des Jahresumsatzes zur Ausbildungsdimension wird abgewiesen. |

## Bewusst exakt belegte Details

Die Modelle deklarieren die tatsächlichen zusammengesetzten Primärschlüssel und die expliziten Join-Paare. `population` verweist auf `municipalities`, `vehicles` auf `population`; Personal und Umsatz verweisen jeweils auf `years`. Die Abfragen nutzen die inversen Relationen von diesen gemeinsamen Wurzeln aus. `to_many_handling='error'` ist in jeder Abfrage gesetzt.

Lokale Fahrzeugfilter werden als literalbasierter Ausdruck erzeugt: ein Tupel aus `ast.Constant`/`ast.unparse`, danach `iif(predicate, value, None)`. Es gibt keine Query-Variables und keine globalen Fahrzeugarten-/Faktenfilter. Insbesondere wird der Bevölkerungsnenner nicht durch einen solchen Filter als Semijoin eingeschränkt. R06 berechnet und vergleicht alle 42 Arten.

Die native `DataType`-Enumeration besitzt weder `DECIMAL` noch `NUMERIC`. Für den Umsatz lautet das vorhandene API-Mapping `type=DOUBLE`, ergänzt um **`db_type='DECIMAL(18,2)'`**. Erst dieser Originaltyp erhält im geprüften nativen Pfad exakte Werte: `SUM` und `time_shift(SUM)` liefern Python-`Decimal`; `model_dump(mode='json')` liefert die Geldbeträge als Dezimalzeichenketten, etwa `"2566066.00"` und `"2762610.00"`. R07/R09 prüfen diese Zeichenketten exakt und protokollieren die ursprünglichen Python-Typen. Quotienten und Wachstumsraten bleiben Gleitkommazahlen und werden mit absoluter Toleranz `1e-9` verglichen.

Measure-Aliase tragen `probe_` als Präfix, da SLayer einen Alias ablehnt, der mit einem Quellspaltennamen kollidiert. Dies ist eine tatsächliche native API-Vorgabe; es ist keine fachliche Umbenennung der Daten.

Die Verbindung verwendet `access_mode=READ_ONLY`. Die Datenbank-SHA256 wird vor und nach dem Lauf geprüft und blieb unverändert. Das 50-ms-Callback im Test-Eventloop weckt lediglich den Test-Harness in dieser Umgebung; der SLayer-Quellcode wurde nicht verändert. Es handelt sich nicht um eine Umsetzung der endgültigen Prozessisolation oder der Betriebsgrenzen.

Die Fahrzeug-/Bevölkerungsverhältnisse sind weiterhin arithmetische Proben über dieselbe Berichtsperiode. Der konkrete Fahrzeugstichtag bleibt unbekannt. Ein bestandener Rechentest bestätigt keine strikte Stichtagsgleichheit, keine Vollständigkeit seltener Fahrzeugarten und keine Zuordnung von Personen zu Fahrzeugarten. Die allgemeine Fehlend-/Null-Semantik wird durch diesen Lauf nicht erweitert.
