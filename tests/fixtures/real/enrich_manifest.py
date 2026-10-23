"""Record supplied catalogue evidence beside the downloaded fixture snapshots."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
UPLOAD = HERE.parents[1] / "upload"
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"


def name(element):
    return element.tag.rsplit("}", 1)[-1]


published = UPLOAD / "published-catalog-e4560849-cd01-4e19-ac09-11f5d3036fb1.xtf"
rdf_path = UPLOAD / "opendata.rdf"
records = {}
for e in ET.parse(published).getroot().iter():
    if name(e) not in {"Dataset", "DatasetIssue"}:
        continue
    direct = {name(c): c for c in e}
    if "identifier" not in direct:
        continue
    data = {key: direct[key].text for key in ("identifier", "title", "resourceUri", "issued", "modified", "description", "surveyMethod", "furtherUses", "auxiliaryData", "publicationStatus", "issueLabel") if key in direct}
    data["xml_type"] = name(e)
    data["temporalCoverage"] = {name(c): c.text for c in direct.get("temporalCoverage", []) .iter() if len(c) == 0} if "temporalCoverage" in direct else {}
    data["accessRights"] = {name(c): c.text for c in direct.get("accessRights", []).iter() if len(c) == 0} if "accessRights" in direct else {}
    for node in e.iter():
        if name(node) == "downloadURL" and node.text and node.text.endswith(".parquet"):
            records[node.text] = data

licenses = {}
for e in ET.parse(rdf_path).getroot().iter():
    if name(e) != "Distribution":
        continue
    direct = {name(c): c for c in e}
    if "downloadURL" in direct:
        url = direct["downloadURL"].attrib.get(RDF_RESOURCE)
        licenses[url] = direct.get("license").attrib.get(RDF_RESOURCE) if direct.get("license") is not None else None

manifest_path = HERE / "manifest.json"
manifest = json.loads(manifest_path.read_text())
manifest["rdf_metadata_sha256"] = hashlib.sha256(rdf_path.read_bytes()).hexdigest()
excerpts = {}
for source in manifest["sources"]:
    data = records[source["source_url"]]
    source["dataset_identifier"] = data["identifier"]
    source["dataset_resource_uri"] = data["resourceUri"]
    source["license_uri"] = licenses.get(source["source_url"])
    source["license_evidence"] = "supplied opendata.rdf, matching dcat:Distribution/downloadURL"
    source["temporal_coverage_as_published"] = data["temporalCoverage"]
    source["publication_status"] = data["publicationStatus"]
    source["metadata_modified"] = data["modified"]
    source["metadata_excerpt"] = f"metadata_excerpts.json#{source['alias']}"
    excerpts[source["alias"]] = data
manifest["important_limitations"] = [
    "Public mutable source URLs are pinned only by included bytes and SHA256, not by a guaranteed immutable upstream version.",
    "vehicles metadata specifies report year 2025 and a stock at an unspecified reference date; it does not prove a snapshot on 2025-12-31.",
    "population_sex_nationality has 106 rows but only 104 distinct BFS_Nr; Halten and Oekingen incorrectly reuse Kriegstetten's 2525 identifier. Preserve and quarantine, do not silently repair.",
    "taxes uses the geographic structure of 2026; population_age, vehicles and GWS contain the three separate pre-fusion municipalities.",
]
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
(HERE / "metadata_excerpts.json").write_text(json.dumps(excerpts, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"enriched_sources": len(manifest["sources"]), "license_uris": sorted({s['license_uri'] for s in manifest['sources']})}, ensure_ascii=False))
