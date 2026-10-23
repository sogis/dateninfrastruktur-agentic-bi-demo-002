# Ausführbare Nachweise und gespeicherte Messergebnisse

Diese Dateien belegen ausgewählte Bibliotheks- und Datenfakten. Sie sind keine bereits implementierte Produktionsanwendung. Normativ sind ausschliesslich `../spec/` und `../AGENTS.md`.

- `native_real/`: elf reale SLayer-Proben, vollständige Queries, generiertes SQL, Ergebnisse und native YAML-Beispiele. Nach Installation des gepinnten SLayer aus dem Paketroot: `python evidence/native_real/probe_real.py --data-dir tests/fixtures/real`. Das Script regeneriert seine Datasource mit dem tatsächlichen lokalen DB-Pfad. Vorgefundene native Datasource-YAMLs sind historische Nachweisdateien mit dem damaligen Pfad, keine direkt zu übernehmende Betriebskonfiguration.
- `semantics/`: synthetische fokussierte Proben zu Zeitfenstern, Jahresmitteln, sicheren Literalen und Quellenabdeckung. Ausführen mit `python evidence/semantics/semantic_compile_probe_fixed.py` beziehungsweise `python evidence/semantics/source_coverage_probe.py`. Die ursprüngliche `semantic_compile_probe.py` zeigt bewusst zwei Fehlformen; sie gehört zur Erklärung des korrigierten Entwurfs. `_upstream_engine_helpers.py` ist der unveränderte SLayer-Testhelfer am geprüften Commit; MIT-Hinweis liegt daneben. Die einzige Anpassung der Probe-Scripts ist ihr portabler lokaler Import dieses Helfers.
- `runtime/mcp_api_probe.py`: tatsächlich ausführbarer Nachweis der FastMCP-/Starlette-Signaturen und Lifecycle-Verdrahtung. Ergebnis in `mcp_api_probe_results.json`.
- `runtime/runtime_measurements.json`: historische Mikrobenchmarks von frischen/warmen Queryprozessen und tatsächlich beendeten CPU-Abfragen. Sie stammen aus dem geprüften Forschungsaufbau. Die Produktionsabnahme B05-B08 bleibt Aufgabe des Coding-Agenten; diese gespeicherten Zahlen sind weder SLA noch fertiger Supervisor.
- `requirements-tested.txt`: Forschungsumgebung. Daraus einen kleinen Produkt-Lock erstellen; nicht jedes Forschungspaket zur Runtime-Abhängigkeit machen.

Die 50-ms-Eventloop-Aufweckfunktion einiger Forschungsproben ist eine Anpassung des hiesigen Testharness. SLayer-Code und Berechnung blieben unverändert. Sie wird nicht als notwendiger Bestandteil der Produktarchitektur übernommen.

Ein erneuter Prüflauf darf Ergebnisprotokolle aktualisieren, aber niemals die `tests/fixtures/real/raw/`-Originale oder fachliche Sollwerte an das tatsächliche Resultat anpassen.
