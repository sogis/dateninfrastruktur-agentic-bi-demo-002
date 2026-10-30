# Rechte des Prototyps

Vereinfacht nach dem Access-Modell der Dateninfrastruktur des AGI (open/restricted je Datensatz, Freigabe für Gruppe
oder Person, Protokoll), siehe `../rules/access.yaml`. Antrag und Entscheid zeigt der Prototyp bewusst nicht.

| Datei | Inhalt | wer schreibt | versioniert |
|---|---|---|---|
| `grants.yaml` | wer welchen restricted Datensatz lesen darf (`group:<Name>`, `person:<E-Mail>`) | Eigner, im Prototyp von Hand | ja (nur Gruppen) |
| `audit.jsonl` | jeder Zugriff auf einen restricted Datensatz: wer, was, wann, erlaubt ja/nein | Dokumente-Server | nein (E-Mail-Adressen) |

Testen: In OpenWebUI unter Admin → Benutzer → Gruppen sich selbst in die Gruppe „Staatskanzlei“ aufnehmen oder
herausnehmen und dieselbe Frage stellen. Anzeigen: `python3 scripts/ai_data.py access grants|audit`.
