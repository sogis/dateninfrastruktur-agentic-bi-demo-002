"""Catalog in a standard format: DCAT-AP CH (eCH-0200, the format of opendata.swiss and I14Y) plus DQV for quality.

The catalog only describes *what* exists, who owns it, who may roughly see it, how to get to it and how good it
is. It knows nothing about AI, models or tools: every statement belongs to exactly one layer.

There are no custom fields. Custom are only three vocabularies under the placeholder namespace ``so:``
(application profile Solothurn, no official address yet):
  so:criterion/<id>         criteria as DQV metrics (rules/criteria.yaml, e.g. so:criterion/validity)
  so:document-profile/<id>  document profiles (rules/document_profiles/), for dct:conformsTo
  so:document-type/<id>     document types, for dct:type
Access: EU vocabulary (PUBLIC, RESTRICTED), as in the data portal.

``to_dcat`` builds an entry from the intermediate record of the catalog build; ``view`` turns an entry into the
short view for people and chat (German labels). The catalog itself stays the source of truth.
"""

from __future__ import annotations

from .rules import Rules

SO = "urn:x-ai-ready-data:"  # placeholder, not an official address
CONTEXT = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dct": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "vcard": "http://www.w3.org/2006/vcard/ns#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "so": SO,
}
TYPE = {"dataset": "dcat:Dataset", "series": "dcat:DatasetSeries", "corpus": "dcat:Dataset"}
CRITERION = "so:criterion/"
DOCUMENT_TYPE = "so:document-type/"
DOCUMENT_PROFILE = "so:document-profile/"
SERVICE = "so:service/"


def _compact(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if v not in (None, [], {}, "")}


def _agent(agent: dict | None) -> dict | None:
    if not agent:
        return None
    return _compact({"@type": "foaf:Agent", "@id": agent.get("uri"), "foaf:name": agent.get("name"),
                     "dct:identifier": agent.get("abbreviation")})


def service(identifier: str, title: str, endpoint: str, description: str, datasets: list[str]) -> dict:
    """An interface (dcat:DataService). What an application does with it is up to the application, not the catalog."""
    return {"@type": "dcat:DataService", "@id": SERVICE + identifier, "dct:identifier": identifier, "dct:title": title,
            "dcat:endpointURL": endpoint, "dcat:endpointDescription": description,
            "dcat:servesDataset": [{"@id": entry_id(d)} for d in datasets]}


def entry_id(identifier: str, uri: str | None = None) -> str:
    return uri or f"{SO}dataset/{identifier}"


def measurements(results: dict, rules: Rules) -> list[dict]:
    """Check results as DQV measurements (met = true, missing = false), in the order of rules/criteria.yaml."""
    return [_compact({"@type": "dqv:QualityMeasurement", "dqv:isMeasurementOf": {"@id": CRITERION + k},
                      "dqv:value": results[k]["value"], "rdfs:comment": results[k].get("finding")})
            for k in rules.criteria if k in results]


def _distributions(items: list[dict] | None) -> list[dict]:
    return [_compact({
        "@type": "dcat:Distribution", "@id": d.get("uri"), "dct:title": d.get("title"),
        "dcat:accessURL": d.get("access_url"), "dcat:downloadURL": d.get("download_url"), "dct:format": d.get("format"),
        "dcat:accessService": {"@id": SERVICE + d["service"]} if d.get("service") else None,
    }) for d in items or []]


def to_dcat(r: dict, rules: Rules) -> dict:
    """One catalog entry from the intermediate record ``r`` of the catalog build."""
    license_ = r.get("license")
    period = r.get("period") or {}
    entry = {
        "@type": TYPE[r["type"]], "@id": entry_id(r["id"], r.get("uri")),
        "dct:identifier": r["id"], "dct:title": r["title"], "dct:description": r.get("description"),
        "dcat:keyword": r.get("keywords"), "dcat:theme": [{"@id": t} for t in r.get("themes") or []],
        "dct:type": {"@id": DOCUMENT_TYPE + r["document_type"]} if r.get("document_type") else None,
        "dct:creator": _agent(r.get("owner")), "dct:publisher": _agent(r.get("publisher") or r.get("owner")),
        "dcat:contactPoint": _compact({"@type": "vcard:Organization", "vcard:fn": r["contact"].get("name"),
                                       "vcard:hasEmail": r["contact"].get("email")}) if r.get("contact") else None,
        "dct:accessRights": {"@id": rules.access_to_dcat(r["access"])},
        "dct:license": {"@id": license_} if license_ and license_.startswith("http") else None,
        "dct:rights": ({"@type": "dct:RightsStatement", "rdfs:label": license_}
                       if license_ and not license_.startswith("http") else None),
        "dct:accrualPeriodicity": (_compact({"@id": r.get("update_frequency_uri"), "rdfs:label": r.get("update_frequency")})
                                   if r.get("update_frequency_uri") or r.get("update_frequency") else None),
        "dct:issued": r.get("issued"), "dct:modified": r.get("modified"),
        "dct:temporal": {"@type": "dct:PeriodOfTime",
                         "dcat:startDate": period.get("reference_date") or period.get("start"),
                         "dcat:endDate": period.get("reference_date") or period.get("end")} if period else None,
        "dct:conformsTo": ([{"@id": DOCUMENT_PROFILE + r["document_profile"]}] if r.get("document_profile") else [])
        + ([{"rdfs:label": r["data_model"]}] if r.get("data_model") else []),
        "dcat:landingPage": r.get("source"),
        "dct:isPartOf": {"@id": entry_id(r["part_of"])} if r.get("part_of") else None,
        # Issues of a series (DCAT 3: datasets with dcat:inSeries); their downloads belong to the issue.
        "dct:hasPart": [_compact({"@type": "dcat:Dataset", "dct:identifier": i["id"], "rdfs:label": i.get("label"),
                                  "dcat:inSeries": {"@id": entry_id(r["id"], r.get("uri"))},
                                  "dcat:version": "current" if i.get("current") else None,
                                  "dcat:distribution": _distributions(i.get("distributions"))})
                        for i in r.get("issues") or []],
        "dcat:distribution": _distributions(r.get("distributions")),
        "dqv:hasQualityMeasurement": measurements(r["criteria"], rules),
    }
    return _compact(entry)


def catalog(title: str, modified: str, entries: list[dict], services: list[dict], provenance: dict) -> dict:
    return {"@context": CONTEXT, "@type": "dcat:Catalog", "dct:title": title, "dct:modified": modified,
            "dct:source": provenance, "dcat:service": services, "dcat:dataset": entries}


# View for people and chat ----------------------------------------------------------
def _name(agent: dict | None) -> str | None:
    if not agent:
        return None
    return f"{agent['foaf:name']} ({agent['dct:identifier']})" if agent.get("dct:identifier") else agent.get("foaf:name")


def results_of(entry: dict) -> dict:
    return {m["dqv:isMeasurementOf"]["@id"].removeprefix(CRITERION): dict(value=m["dqv:value"], finding=m.get("rdfs:comment"))
            for m in entry.get("dqv:hasQualityMeasurement", [])}


def kind(entry: dict) -> str:
    return "documents" if (entry.get("dct:type") or {}).get("@id", "").startswith(DOCUMENT_TYPE) else "data"


def view(entry: dict, rules: Rules, detailed: bool = True) -> dict:
    """Short view of a catalog entry: what is missing (with finding) and what is met. Labels are German."""
    results = results_of(entry)
    access = rules.access_from_dcat(entry["dct:accessRights"]["@id"])
    order = [k for k in rules.criteria if k in results]
    failed = [k for k in order if results[k]["value"] is False]
    short = dict(id=entry["dct:identifier"], title=entry["dct:title"], kind=kind(entry), access=access)
    if not detailed:
        return dict(short, missing=[rules.criteria[k]["name"] for k in failed])
    temporal = entry.get("dct:temporal") or {}
    license_ = (entry.get("dct:license") or {}).get("@id") or (entry.get("dct:rights") or {}).get("rdfs:label")
    return _compact(dict(
        short,
        missing=[_compact(dict(name=rules.criteria[k]["name"], finding=results[k]["finding"])) for k in failed],
        met=[rules.criteria[k]["name"] for k in order if results[k]["value"] is True],
        description=entry.get("dct:description"),
        owner=_name(entry.get("dct:creator")),
        office=(entry.get("dct:creator") or {}).get("dct:identifier"),
        document_type=(entry.get("dct:type") or {}).get("@id", "").removeprefix(DOCUMENT_TYPE) or None,
        modified=entry.get("dct:modified"),
        period=(f"{temporal.get('dcat:startDate')} bis {temporal.get('dcat:endDate')}"
                if temporal.get("dcat:startDate") != temporal.get("dcat:endDate")
                else f"Stichtag {temporal.get('dcat:startDate')}") if temporal else None,
        update_frequency=_frequency(entry.get("dct:accrualPeriodicity")),
        license=license_,
        source=entry.get("dcat:landingPage"),
        part_of=(entry.get("dct:isPartOf") or {}).get("@id", "").rsplit("/", 1)[-1] or None,
        issues=[i["dct:identifier"] for i in entry.get("dct:hasPart", [])],
        services=sorted({d["dcat:accessService"]["@id"].removeprefix(SERVICE)
                         for d in entry.get("dcat:distribution", []) if d.get("dcat:accessService")}),
        keywords=entry.get("dcat:keyword"),
    ))


FREQUENCY = {"ANNUAL": "jährlich", "MONTHLY": "monatlich", "QUARTERLY": "vierteljährlich", "WEEKLY": "wöchentlich",
             "DAILY": "täglich", "IRREG": "unregelmässig", "AS_NEEDED": "nach Bedarf", "UPDATE_CONT": "laufend",
             "CONT": "laufend", "NEVER": "nie"}


def _frequency(value: dict | None) -> str | None:
    if not value:
        return None
    code = value.get("@id", "").rsplit("/", 1)[-1]
    return value.get("rdfs:label") or FREQUENCY.get(code, code) or None


def standard_gaps(entry: dict) -> list[str]:
    """What is missing for publication under DCAT-AP CH (mandatory fields per the opendata.swiss handbook; to be
    reconciled with eCH-0200 V3.0.1). A series distributes through its issues, not itself."""
    gaps = [f for f in ("dct:identifier", "dct:title", "dct:description", "dct:publisher") if not entry.get(f)]
    if entry["@type"] != "dcat:DatasetSeries" and not entry.get("dcat:distribution"):
        gaps.append("dcat:distribution")
    if not entry.get("dct:license"):
        gaps.append("dct:license")
    return gaps
