# Prüfbericht zur Detailspezifikation SLayer 1.0

**23. Oktober 2026 · Diese Prüfung betrifft die Daten und verwendeten SLayer-Bausteine. Die spezifizierte Gesamtanwendung ist noch zu implementieren.**

## Umfang des Übergabepakets

Sechs normative Kapitel beschreiben den öffentlichen Vertrag, die Fachregeln, native Übersetzung, acht Anwendungsmodule, Klassen-/Methodensignaturen, Datenabnahme und Betrieb. `AGENTS.md` und `STARTPROMPT.md` geben dem Coding-Agenten einen direkten Arbeitsauftrag. 19 JSON-Anfragebeispiele, eine ausführbare DTO-Referenz, ein daraus erzeugtes JSON-Schema und eine native Fahrzeugmodellvorlage konkretisieren den Vertrag.

Die DTO-Referenz prüft die Grammatik. Die zusätzliche fachliche Prüfung ist bewusst Teil des Implementierungsauftrags. Strukturell gültige Negativbeispiele müssen von der späteren Anwendung fachlich abgewiesen werden.

## Tatsächlich verfügbare Daten

Neun vollständige unveränderte Parquet-Dateien aus den Quellenverweisen des gelieferten Katalogs, insgesamt 55’119 Bytes. Keine Stichproben. Quellen, Abrufzeiten, SHA-256, Originalfelder und Lizenzhinweise sind je Datei dokumentiert. Die Quellen liegen im öffentlich erreichbaren `ch.so.daten-test`-Bucket; eine zusätzliche amtliche Produktionsfreigabe wird daraus nicht abgeleitet.

Die vorbereiteten zehn physischen Tabellen enthalten unter anderem 106 Gemeinden, 2’623 Fahrzeugzeilen, 224 Personalzeilen und 43 Umsatzjahre. Die 42 Fahrzeugarten bleiben mit Originalcodes erhalten. Die vollständigen Originale und ein neuer Aufbau aus ihnen sind im Paket enthalten.

## Bestandene Nachweise

| Nachweis | Ergebnis |
|---|---|
| Unabhängige Rohdaten-SQL-Abfragen | 24 Abfragen mit vollständigen gespeicherten Sollresultaten |
| Normalisierung gegen Rohdaten-Orakel | 13 Vergleiche mit 383 Ergebniszeilen bestanden |
| Konkrete Baseline-Dateninvarianten | 18 Prüfungen, jeweils 0 Verletzungen |
| Native SLayer-Proben auf realen Daten | Elf bestanden: zehn Zahlen-/Gruppierungsfälle und eine erwartete fachliche Zuordnungsablehnung |
| Gemeindevergleich | Alle 106 Gemeinden ohne Vervielfachung der Bevölkerung |
| Bezirksvergleich | Alle zehn Bezirke geprüft |
| Referenznenner je Fahrzeugart | Alle 42 Arten mit konstantem kantonalem Bevölkerungsnenner geprüft |
| Geldwerte | Mit `db_type=DECIMAL(18,2)` bleiben Summen und Vorjahressummen exakte Decimalwerte |
| Fokussierte native Semantikproben | Jahresmittel, Vorjahresrahmen, Literalescaping und Quellenabdeckung vor lokalen Filtern bestanden |
| MCP-/ASGI-Probe | Initialisierung, Toolaufruf, strukturierte Antwort, Bodylimit 413 und einmalige globale Lifespan bestätigt |
| Prozessbegrenzung | Laufende DuckDB-CPU-Abfrage durch Supervisor-Kill sowie separat durch eigenen OS-Alarm beendet |
| 19 öffentliche Anfragebeispiele | Gegen die tatsächliche Pydantic-DTO-Grammatik geprüft |

Die portablen realen Native-, Semantik-, Quellenabdeckungs- und MCP-Proben wurden zusätzlich aus dem zusammengestellten Übergabepaket ausgeführt. Keine Rohdatei wurde dabei geändert. Forschungs-Mikrobenchmarks ergaben ungefähr 1.00–1.28 Sekunden pro frischem Queryprozess; das ist kein SLA.

## Zentrale reale Datenbefunde

Die kanonische Bevölkerung beträgt 293’081, der Personenwagenbestand 168’245, Personenwagen plus Motorräder 190’409. Daraus ergeben sich rechnerisch 574.0563189016005 beziehungsweise 649.6804637625776 Fahrzeuge pro 1’000 Einwohner. Der Fahrzeugstichtag ist jedoch nicht dokumentiert; strenge Stichtagsgleichheit darf nicht behauptet werden.

Die separate Bevölkerungstabelle nach Geschlecht und Staatsangehörigkeit hat einen tatsächlichen Schlüsselfehler: Halten, Kriegstetten und Oekingen tragen alle BFS 2525. Die Datei bleibt unverändert als Quarantänefixture erhalten. Der kantonale Totalvergleich alleine erkennt diesen Fehler nicht.

AV-Personal 2024/2025: 66/65 Personen, korrekter Durchschnitt der Jahrestotale 65.5. Nominaler Umsatz: CHF 2’566’066.00 / CHF 2’762’610.00. Personal ist keine dokumentierte FTE-Kennzahl, Umsatz ist nicht inflationsbereinigt.

Steuerdaten 2025 verwenden den Gebietsstand 2026 mit 104 Gemeinden. eBau enthält Monatsdaten, einschliesslich eines unvollständigen ersten Quartalszeitraums. Beide sind als erklärende Negativ-/Erweiterungsfälle enthalten und in V1 nicht als kompatible kommunale Jahresmodelle freigegeben.

## Abgrenzung zur noch offenen Implementierung

Der Coding-Agent muss den eigentlichen Compiler, die Metadaten-/Qualitätsintegration, die drei MCP-Werkzeuge, den produktiven Prozesssupervisor, das Authoring und die Containerabnahme noch umsetzen. Insbesondere die gesamte Verknüpfung verschobener Nenner-/Coverageprüfungen ist ein verpflichtender Anwendungstest. Die beigefügten Forschungsproben dürfen nicht als bereits bestandene Ende-zu-Ende-Abnahme dieser noch nicht gebauten Anwendung ausgegeben werden.

Verbindliche Umsetzungskriterien sind F01–F16, N01–N17, M01–M09 und B01–B15 in `spec/04_DATEN_UND_ABNAHME.md`. Ihre Formulierung und die konkreten Sollwerte bilden die Grundlage für eine ehrliche spätere Abnahme.

## Belegdateien

- `tests/fixtures/real/manifest.json`, `expected_results.json`, `reference_queries.sql`, `author_invariants.sql`, `normalized/verification.json`.
- `evidence/native_real/results.json` und `probe_real.py`.
- `evidence/semantics/*_results.json` und die zugehörigen Proben.
- `evidence/runtime/mcp_api_probe_results.json`, `runtime_measurements.json`.
- `examples/cases.json`, `analysis_request.schema.json`, `contracts_reference.py`.

Geprüfter SLayer-Stand: 1.4.1, Commit `516539dfec2979180695efa4351e0adccd6b2816`. Die vollständige technische Basis ist in Kapitel 05 festgehalten.
