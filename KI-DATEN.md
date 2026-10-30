# Erweiterung von Demo 002: Daten und Dokumente über einen Zugang

> Stand 24.11.2026. **Prototyp, lokal, nicht abgestimmt.** Ergänzt die Agentic-BI-Demo 002 (AGI), ohne deren Dateien
> zu ändern: Alle Teile liegen daneben und werden über eine zweite Compose-Datei zugeschaltet.

## Was die Erweiterung zeigt
1. **Ein Zugang für Zahlen und Texte.** Ein zweites Modell im Chat nutzt den Daten-Server der Demo *und* einen zweiten
   MCP-Server mit Dokumenten (Erlasse aus der BGS, Regierungsratsbeschlüsse).
2. **Ein Katalog über alle Quellen**, nach DCAT-AP CH, mit DQV für die Qualität: Je Quelle steht, welche Kriterien
   erfüllt sind und was fehlt, mit Befund in Worten. Berechnet, nicht eingeschätzt.
3. **Dokumentprofile:** Für Dokumente das Gegenstück zum Datenmodell: was ein Rechtstext bzw. ein Beschluss mitbringen
   muss. Jeder Bestand wird dagegen geprüft.
4. **Rechte je Person** nach dem Access-Modell der Dateninfrastruktur: `open`/`restricted` je Datensatz, Freigabe
   für Gruppe oder Person, Protokoll. Das Modell sieht nie mehr als die fragende Person.

## Aufbau

```
┌───────────────────────────────────────────────────────────────────┐
│ OpenWebUI                                                         │
│ Modell „Agentic BI – SLayer“ (Demo 002): nutzt den Daten-Server   │
│ Modell „Daten + Dokumente“ (neu): nutzt beide Server              │
└───────────────┬──────────────────────────────────┬────────────────┘
                │ MCP                              │ MCP + Person (Mail, Gruppen)
                ▼                                  ▼
┌──────────────────────────────┐   ┌────────────────────────────────┐
│ Daten-Server (Demo 002)      │   │ Dokumente-Server (neu)         │
│ search · inspect · analyse   │   │ catalog · search_laws          │
│                              │   │ get_section · get_changes      │
│                              │   │ search_decisions · get_decision│
├──────────────────────────────┤   ├────────────────────────────────┤
│ Semantic Layer (models/)     │   │ Katalog: 27 Quellen            │
│ DuckDB                       │   │ BGS: 3 Erlasse, alle Fassungen │
│                              │   │ RRB 2026 (nur lokal)           │
└──────────────────────────────┘   └────────────────────────────────┘
                ▲                                  ▲
                │ Daten                            │ Katalogbau liest Release
                └──────────────────────────────────┘
                              Datenportal
```

| Komponente | Herkunft | Dateien |
|---|---|---|
| OpenWebUI, Start, Modell „Agentic BI – SLayer“, Daten-Server, Semantic Layer | Demo 002, unverändert | `docker-compose.yml`, `scripts/openwebui.py`, `src/`, `models/`, … |
| Dokumente-Server (6 Werkzeuge) | neu | `documents/src/documents_mcp/server.py`, `corpus.py` |
| Dokumente holen und aufbereiten (raw → aufbereitet) | neu | `bgs.py`, `rrb.py`, `distribution_list.py` → `corpus/` |
| Katalog über alle Quellen | neu | `catalog.py`, `dcat.py` → `catalog/catalog.json`; von Hand nur `catalog/datasheets/*.yaml` |
| Kriterien und Dokumentprofile | neu | `rules/criteria.yaml`, `rules/document_profiles/`, `rules.py` |
| Rechte | neu | `rules/access.yaml`, `access/grants.yaml`, `access.py` |
| Zweites Modell, Prompt-Zusatz, Einrichtung, Gesamtcheck | neu | `scripts/ai_data.py`, `openwebui/ai-data-prompt.md` |
| Anbau an Compose | neu | `compose.ai-data.yml` (über `COMPOSE_FILE`) |

Namen im Code, in Dateien und Schlüsseln sind englisch wie in der Demo 002; Meldungen, Prompt, Werkzeugbeschreibungen
und Fachinhalte (Kriterien, Datenblätter) sind deutsch.

## Werkzeuge des Dokumente-Servers

| Werkzeug | Wozu | Beispiel |
|---|---|---|
| `catalog` | Wegweiser: was gibt es, welches Werkzeug, was fehlt | „Fahrzeugbestand“ → über `analyse` rechnen; Stichtag fehlt |
| `search_laws` | Volltext in den Erlassen, gültige Fassung am Datum | „Motorfahrzeugsteuer“ → BGS 614.61 §§ 1–3 und 5 |
| `get_section` | Wortlaut zitieren, auch frühere Fassung | `get_section(act="614.61", section="3", date="2024-01-01")` |
| `get_changes` | Fassungen mit Gültigkeit und Änderungstabelle | `get_changes(act="614.61")` |
| `search_decisions` | RRB filtern nach Amt, Zeitraum, BGS-Nummer | Gesundheitsamt 2026 → 90 (Volltext allein: 41) |
| `get_decision` | einzelner Beschluss, Verteiler nur mit Freigabe | RRB 2026/1680 |

Technisch: BGS über die Schnittstelle (XHTML), in Paragrafen zerlegt, alle Fassungen mit Gültigkeit. Suche mit
SQLite-Volltext im Speicher, beim Start gebaut; keine Vektordatenbank. Ämter aus dem RRB-Verteiler und BGS-Nummern aus
dem Text werden herausgelesen und als „ungeprüft“ markiert. PDF nur als Notbehelf, mit Hinweis ans Modell.

## Katalog
`python3 scripts/ai_data.py catalog` baut `catalog/catalog.json` ohne Netz und reproduzierbar
(`--fetch` holt vorher den aktuellen Datenportal-Release nach `catalog/raw/`, nicht versioniert).

| Teil | woher |
|---|---|
| 24 Datensätze und Reihen | Datenportal-Release (Katalog-XTF), Lizenz aus dem DCAT-Export `opendata.rdf`; dazu `models/` und Quellen-Manifest der Demo: was als Kennzahl abfragbar ist |
| 3 Dokument-Datensätze (`bgs`, `rrb`, `rrb-distribution-list`) | je ein Datenblatt + Bestand + Dokumentprofil |
| Kriterien je Quelle (*erfüllt* / *fehlt* mit Befund) | Prüfregeln in `catalog.py` und Dokumentprofile; im Katalog als DQV-Messwert |

Der Katalog enthält nur Standard (DCAT-AP CH + DQV) und nennt Schnittstellen, keine Werkzeuge oder Modelle. Das Modell
bekommt je Frage eine Kurzfassung, nicht die ganze Datei.

Häufigste Lücken (Release 3e564d39, 27 Quellen):

| Kriterium fehlt | Quellen | Beispiel |
|---|---|---|
| Personendaten bekannt | 24 | Datenportal hat kein Feld dafür |
| Kennzahlen definiert | 18 | nicht im Semantic Layer |
| Stand und Gültigkeit | 10 | Fahrzeugbestand ohne Stichtag; BGS Gültigkeit nur als Text |
| Angaben als Feld | 6 | RRB: beteiligte Ämter nur im PDF-Verteiler |
| Feste Kennung | 5 | `…steuerfuss_gemeinden-2026` statt `…_2026`; BGS ohne Kennung je Paragraf |

## Rechte
- OpenWebUI schickt bei jedem Werkzeugaufruf E-Mail und Gruppen der angemeldeten Person mit (`X-User-Email`,
  `X-User-Groups`). Sie gelten nur zusammen mit dem gemeinsamen Schlüssel `DOCUMENTS_API_KEY`, sonst ist der Aufruf
  anonym.
- `open` für alle; `restricted` ist im Katalog auffindbar, der Inhalt nur mit Eintrag in `access/grants.yaml`
  (`group:<Name>` oder `person:<E-Mail>`). Änderungen gelten sofort.
- Jeder Zugriff auf `restricted` wird in `access/audit.jsonl` festgehalten (lokal, nicht versioniert).
- Beispiel: Der Verteiler der RRB ist ein eigener Datensatz `rrb-distribution-list` (`restricted`), freigegeben für
  die OpenWebUI-Testgruppe „Staatskanzlei“ (`seed` legt sie leer an; Mitglieder von Hand).
- Vereinfacht: Gruppen aus OpenWebUI statt Keycloak, Datei statt Datenbank. Wie eine Freigabe entsteht (Antrag,
  Entscheid), zeigt der Prototyp nicht. Der Daten-Server der Demo prüft keine Rechte.

## Starten
Voraussetzungen wie bei der Demo (Docker, Python ≥ 3.9), dazu `uv`; `poppler-utils` (`pdftotext`) nur für einen neuen
Abruf. Lokale `.env` wie `.env.example`, zusätzlich:

```sh
OPEN_WEBUI_HOST_PORT='3004'
AGENTIC_BI_HOST_PORT='8004'
DOCUMENTS_HOST_PORT='8005'
COMPOSE_FILE='docker-compose.yml:compose.ai-data.yml'
WEBUI_SECRET_KEY='…'     # eigener Wert, falls die Demo daneben läuft (Cookies gelten portübergreifend)
DOCUMENTS_API_KEY='…'    # python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# DOCUMENTS_UID / DOCUMENTS_GID nur, wenn die eigene Benutzerkennung nicht 1000 ist (Schreibrecht auf access/)
```

```sh
cd documents && uv sync --group dev && cd ..   # einmalig: Umgebung für Katalogbau, Tests und Abruf
python3 scripts/ai_data.py start          # Start der Demo + Dokumente-Server + Modell „Daten + Dokumente“
python3 scripts/ai_data.py check          # Gesamtcheck (ohne Provider-Kosten)
python3 scripts/ai_data.py ask "…"        # Frage als gespeicherten Chat (kostet einen Provider-Aufruf)
python3 scripts/ai_data.py catalog        # Katalog neu bauen; danach: docker compose up -d --build documents-mcp
python3 scripts/ai_data.py access grants|audit
```

OpenWebUI läuft in v0.12.5 statt v0.12.3 (Sicherheitskorrekturen), festgelegt in `compose.ai-data.yml`.

Der **Gesamtcheck** prüft: Dateien der Demo unverändert, Roh-Stufe unverändert, 38 Tests in `documents/`, drei Dienste
gesund, Dokumente-Server hat genau `catalog/catalog.json` geladen, OpenWebUI (Prüfungen der Demo + Modell, Werkzeuge,
Kopfzeilen), Hinweis bei neuerem Datenportal-Release.

Bestand neu abrufen bzw. nur neu aufbereiten:
```sh
cd documents
.venv/bin/python -m documents_mcp.bgs 614.61 614.62 733.11 --target ../corpus/bgs [--prepare-only]
.venv/bin/python -m documents_mcp.rrb 2026 --target ../corpus/rrb   # 1 Anfrage/s (≈ 1 h), fortsetzbar
```
`corpus/rrb/` ist nicht versioniert und nicht im Image (Titel und Verteiler enthalten Personendaten); ohne Abruf
liefern die RRB-Werkzeuge nichts.

## Grenzen
- Kriterien, Dokumentprofile und Prüfregeln sind Vorschläge. Geprüft wird nur, was sich aus vorhandenen Angaben
  entscheiden lässt. Die Datenblätter der Dokumentbestände sind von Hand ausgefüllt, nicht vom Eigner.
- BGS: drei Erlasse. 614.62 gibt es nur als PDF; Text heuristisch, Tabellen unbrauchbar. Keine Kennung je Paragraf.
- RRB: ein Jahrgang, nur das Beschlussdokument; Ämter und BGS-Nummern herausgelesen, ungeprüft.
- Der Katalog liest `models/` und das Quellen-Manifest der Demo; der neue Stack (Katalog in PostgreSQL) ist nicht
  angebunden.

## Offene Punkte
1. **Person bis zum Daten-Server:** Die Demo verbindet OpenWebUI ohne Anmeldung (`auth_type="none"`). Könnten
   KI-Abfragen denselben Rechte-Entscheid nutzen wie Downloads im neuen Stack?
2. **Wegweiser für Datensätze ohne Abfrage:** Was im Datenportal liegt, aber nicht im Semantic Layer, findet `search`
   nicht; das Katalog-Werkzeug kennt alle und verweist auf den Download.
3. **Prüfungen beim Anliefern:** uneinheitliche Kennungen (`so_hotellerie_herkunft_2025`,
   `…staatssteuerertraege_gemeinden-2025`), fehlender Stichtag oder Zeitraum im Datenblatt. Teil der Lieferprüfung?
4. **Dokumente im neuen Stack:** Dokumentbestand als Dataset (Dateien, Datenblatt, gleiche Rechte)? Bleibt der
   DCAT-Export, kommt ein Feld „enthält Personendaten“?
