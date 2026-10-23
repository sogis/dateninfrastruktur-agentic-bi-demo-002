# Startauftrag

Implementiere die in diesem Repository spezifizierte Conversational-BI-Anwendung mit SLayer.

Lies zuerst `AGENTS.md` und die sechs Dokumente unter `spec/`. Verwende die tatsächlichen eingefrorenen Testdaten unter `tests/fixtures/real/`. Die Originaldateien und fachlichen Sollwerte dürfen nicht an die Implementierung angepasst werden.

Halte die Umsetzung klein: Funktionen und wenige Klassen, ein Python-Dienst, drei MCP-Werkzeuge, SLayer als Berechnungsengine und höchstens ein aktiver Query-Unterprozess. Baue keine zusätzlichen Architekturframeworks und keine zweite SQL-Engine.

Beginne mit dem ersten vertikalen Umsetzungsschritt aus `spec/05_BETRIEB_UND_UMSETZUNG.md` und arbeite danach selbständig bis zur vollständigen Abnahme weiter. Verwende die vorgesehenen Methoden und Datenverträge als verbindliche Ausgangsbasis. Falls eine tatsächlich geprüfte SLayer-API eine kleine Anpassung erfordert, führe diese begründet durch, halte das Fachverhalten unverändert und ergänze den gezielten Integrationstest.

Die Anwendung ist erst fertig, wenn die realen Positivfälle, die fachlichen Ablehnungen, die Quarantäne der fehlerhaften optionalen Quelle, Timeout/BUSY/Prozessbereinigung, strukturierte Logs und ein echter MCP-Ende-zu-Ende-Aufruf nachgewiesen sind. Liefere den startbaren Code, die ausführbaren Tests und einen knappen Abschlussbericht mit verbleibenden Grenzen.
