# Maschinenlesbare Vertragsbeispiele

`contracts_reference.py` ist die ausführbare DTO-Definition aus Dokument 01. `analysis_request.schema.json` wurde daraus mit dem gepinnten Pydantic generiert. Alle Anfragebeispiele wurden gegen diese Grammatik geprüft.

**Die Grammatikprüfung ist keine implementierte Fachprüfung.** Die zusätzlichen Feld-, Budget-, Grain-, Zeit-, Quellen- und Operatorregeln aus den normativen Spezifikationsdateien muss der Coding-Agent umsetzen. Die negativen JSON-Beispiele sind absichtlich strukturell gültig und müssen danach fachlich abgewiesen werden. `cases.json` ordnet Erwartungen und Orakel zu.

Die JSON-Dateien enthalten jeweils den Wert von `arguments.request` des MCP-Werkzeugs `analyse`. Sie sind keine nativen SlayerQuery-Objekte. Die Codebeispiele zeigen Eingaben, keine Liste fest erlaubter Benutzerfragen.
