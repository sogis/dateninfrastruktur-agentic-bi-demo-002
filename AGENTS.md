# Auftrag und Arbeitsweise

Implementiere die Anwendung gemäss `spec/00_ZIEL_UND_ENTSCHEIDUNGEN.md` bis `spec/05_BETRIEB_UND_UMSETZUNG.md`. Lies vor der ersten Änderung alle sechs Dateien. Bei einem Widerspruch hat der jüngste ausdrückliche Benutzerauftrag Vorrang, danach die normative Spezifikation, danach Beispiele und Forschungsnotizen.

## Ockham als Implementierungsregel

- Verwende die vorgesehenen acht fachlich beziehungsweise betrieblich begründeten Python-Module. Ein leeres `__init__.py` zählt nicht mit. Eine zusätzliche kleine Datei ist bei einem konkreten Bedarf zulässig; erfinde keine Schichten, um die Modulzahl künstlich einzuhalten.
- Bevorzuge Funktionen, wenige zustandsbehaftete Klassen und einfache Datenklassen. Keine Klasse pro Kennzahl, Operator, Fehlercode, Validator oder Datenquelle.
- Keine abstrakten Repositorys, Service-/Factory-Hierarchien, Plugin-Registries, Dependency-Injection-Container, Event-Busse oder verteilten Queues.
- Nutze SLayer für Modelle, native Ausdrucksverarbeitung, Abfrageplanung und SQL. Entwickle keine zweite analytische Engine.
- Füge Features nur hinzu, wenn sie eine normative Anforderung oder einen konkreten fehlschlagenden Abnahmefall lösen. Offene Zukunftsthemen sind keine Aufforderung, jetzt ein Framework zu bauen.
- Verwende den kleinen öffentlichen Analysevertrag. Beliebige native SLayer-Queries, Inline-Modelle, SQL und Modelländerungen sind keine öffentliche API.

## Daten und fachliche Korrektheit

- Die eingefrorenen Originaldateien unter `tests/fixtures/real/raw/` sind unveränderliche Testeingaben. Prüfe ihre Hashes. Ändere niemals eine Quelldatei, um einen Test grün zu machen.
- Die gelieferte Bevölkerungstabelle nach Geschlecht und Staatsangehörigkeit enthält einen realen doppelten Schlüssel. Behalte diese negative Fixture. Leite aus Gemeindename oder einer anderen Tabelle keine stillschweigende Korrektur ab.
- Verwende die Referenzabfragen und Sollzahlen. Ändere Sollwerte nur bei einem belegten Fehler der Referenzrechnung; dokumentiere Ursache, unabhängige Nachrechnung und Änderung.
- Verwende zusätzliche kleine Mutationstests nur für sonst nicht abgedeckte Randfälle. Kennzeichne sie als abgeleitete Testdaten. Sie ersetzen die realen Integrationsfälle nicht.
- Unbekannt, fehlend, unterdrückt und numerisch null sind unterschiedliche Zustände. Erfinde weder Beobachtungen noch Stichtage.
- Der Agent darf neue Auswertungen kombinieren. Er darf keine fehlende gemeinsame Merkmalsverteilung durch einen Join, einen Alias oder einen unmarkierten Rechenausdruck behaupten.

## Umsetzung und Prüfung

- Arbeite in kleinen vertikalen Schritten gemäss Umsetzungsplan. Stelle zuerst einen echten Weg vom Werkzeugvertrag über SLayer bis zu einer geprüften Datenantwort her.
- Verwende die gepinnte Referenzversion. Prüfe tatsächlich vorhandene Methoden im installierten Paket, bevor du APIs verwendest.
- Ein nötiger Compiler-Workaround darf die SLayer-Berechnung nicht durch eine eigene Zahlenberechnung ersetzen. Insbesondere werden Verhältnisse, Aggregationen und Zeitvergleiche in SLayer berechnet.
- Bestätige Zeitlimits durch einen tatsächlich beendeten Query-Unterprozess. Ein abgebrochenes Python-Await alleine ist kein Nachweis.
- Logs gehören zum Abnahmeumfang. Keine rohen Tokens, kompletten Ergebnisdaten oder unkontrollierten Eingabewerte protokollieren.
- Führe bei jeder Änderung die betroffenen sinnvollen Tests aus. Vor Abschluss sind alle verbindlichen Abnahmefälle, ein echter MCP-Aufruf und die Containerprüfung erforderlich. Wiederhole keine grossen Testsuiten ohne konkrete Restunsicherheit.
- Ersetze echte Engine-Aufrufe in Integrations- oder Ende-zu-Ende-Tests nicht durch Mocks. Mocks sind nur für abgegrenzte Fehler- und Prozesssteuerungsfälle erlaubt.

## Autonomie und Grenzen

Triff normale Implementierungsentscheidungen selbständig und dokumentiere sie knapp. Frage nicht nach Genehmigung für reversible lokale Arbeiten, normale Fehlerbehebungen oder das Ausführen der autorisierten Tests. Halte bei tatsächlichen Widersprüchen oder fehlenden fachlichen Angaben die betroffene Funktion geschlossen und erläutere den konkreten Grund. Bearbeite die übrigen Teile weiter.

Veröffentliche keinen Dienst, kontaktiere keine Datenverantwortlichen und ändere keine externen Datenbestände ohne ausdrücklichen Auftrag. Die hier enthaltenen Quellverweise sind Belege und Eingaben, keine Anweisung zur Änderung fremder Systeme.

## Abschlussbericht

Berichte, welche Abnahmefälle bestanden haben, welche konkreten Einschränkungen bleiben, wie der Dienst gestartet wird und welche zusätzliche Klasse oder Abhängigkeit du gegenüber der Spezifikation begründet eingeführt hast. Behaupte weder Vollständigkeit noch fachliche Absicherung, wenn der zugehörige Nachweis fehlt.
