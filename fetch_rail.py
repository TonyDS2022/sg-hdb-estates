"""Fetch Singapore MRT/LRT line geometry from OpenStreetMap -> site/rail.geojson."""
import json, os, re, urllib.parse, urllib.request, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "site", "rail.geojson")
URL = "https://overpass-api.de/api/interpreter"

# BPLRT and PGLRT are tagged route=monorail in OSM (rubber-tyred guideway systems),
# so querying light_rail alone silently drops two of the three LRT networks.
Q = """[out:json][timeout:180];
area["ISO3166-1"="SG"][admin_level=2]->.sg;
(
  relation["route"="subway"](area.sg);
  relation["route"="light_rail"](area.sg);
  relation["route"="monorail"](area.sg);
);
out geom;"""

# Official line colours; OSM is missing a few and we do not want them defaulting to grey.
COLOURS = {
    "NSL": "#d42e12", "EWL": "#009645", "NEL": "#9016b2", "CCL": "#fa9e0d",
    "DTL": "#0354a6", "TEL": "#9d5b25", "JRL": "#0099aa", "CRL": "#97c616",
    "BPLRT": "#748477", "SKLRT": "#748477", "PGLRT": "#748477", "SPLRT": "#748477",
}
NAMES = {
    "NSL": "North South Line", "EWL": "East West Line", "NEL": "North East Line",
    "CCL": "Circle Line", "DTL": "Downtown Line", "TEL": "Thomson–East Coast Line",
    "JRL": "Jurong Region Line", "CRL": "Cross Island Line",
    "BPLRT": "Bukit Panjang LRT", "SKLRT": "Sengkang LRT", "PGLRT": "Punggol LRT",
}
ORDER = ["NSL", "EWL", "NEL", "CCL", "DTL", "TEL", "JRL", "CRL",
         "BPLRT", "SKLRT", "PGLRT", "SPLRT"]


def main():
    raw = os.path.join(HERE, "data", "overpass_rail.json")
    if os.path.exists(raw):          # Overpass throttles; reuse the response on rebuild
        data = json.load(open(raw))
        print("using cached Overpass response (delete data/overpass_rail.json to refetch)")
    else:
        req = urllib.request.Request(URL, data=urllib.parse.urlencode({"data": Q}).encode(),
                                     headers={"User-Agent": "hdb-estate-db/1.0"})
        with urllib.request.urlopen(req, timeout=200) as r:
            data = json.loads(r.read().decode())
        os.makedirs(os.path.dirname(raw), exist_ok=True)
        with open(raw, "w") as f:
            json.dump(data, f, separators=(",", ":"))

    lines = collections.defaultdict(lambda: {"segs": [], "tags": {}, "seen": set()})
    for el in data.get("elements", []):
        if el.get("type") != "relation":
            continue
        t = el.get("tags", {})
        ref = (t.get("ref") or "").strip().upper()
        # the same query also returns the Sentosa Express and the Changi Skytrain:
        # a tourist monorail and an airport people-mover, neither part of the network
        # that serves HDB estates. Keep only the known MRT/LRT lines.
        if ref not in ORDER:
            continue
        L = lines[ref]
        L["tags"] = L["tags"] or t
        for m in el.get("members", []):
            g = m.get("geometry")
            if not g or m.get("type") != "way":
                continue
            coords = [[round(p["lon"], 5), round(p["lat"], 5)] for p in g]
            if len(coords) < 2:
                continue
            # both travel directions are separate relations over the same track
            key = tuple(coords[0] + coords[-1])
            rkey = tuple(coords[-1] + coords[0])
            if key in L["seen"] or rkey in L["seen"]:
                continue
            L["seen"].add(key)
            L["segs"].append(coords)

    feats = []
    for ref in sorted(lines, key=lambda r: ORDER.index(r) if r in ORDER else 99):
        L = lines[ref]
        if not L["segs"]:
            continue
        t = L["tags"]
        colour = COLOURS.get(ref) or t.get("colour") or "#8a8880"
        # a line still being built should not read as though you can ride it
        building = any(k in t for k in ("construction", "proposed")) or \
            t.get("state") in ("construction", "proposed") or ref in ("JRL", "CRL")
        feats.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": L["segs"]},
            "properties": {
                "ref": ref,
                "name": NAMES.get(ref) or t.get("name", ref),
                "colour": colour.lower(),
                "lrt": 1 if "LRT" in ref else 0,
                "building": 1 if building else 0,
            },
        })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"))
    print(f"wrote {OUT}  {os.path.getsize(OUT)/1e6:.2f} MB  lines={len(feats)}")
    for f_ in feats:
        p = f_["properties"]
        print(f"  {p['ref']:<6} {p['name']:<26} {p['colour']}  segs={len(f_['geometry']['coordinates']):>4}"
              f"{'  (under construction)' if p['building'] else ''}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
STATION_RAW = os.path.join(HERE, "data", "overpass_stations.json")
# A bounding box is used rather than area["ISO3166-1"="SG"]: the area lookup
# reliably times out on Overpass's dispatcher. The box catches a little of Johor,
# so entries are filtered to Singapore station-code patterns below.
STATION_Q = """[out:json][timeout:110];
(
  node["railway"="station"](1.15,103.58,1.50,104.10);
  way["railway"="station"](1.15,103.58,1.50,104.10);
);
out center tags;"""

# station-code prefix -> the line it belongs to
PREFIX_LINE = {
    "NS": "NSL", "EW": "EWL", "CG": "EWL", "NE": "NEL", "CC": "CCL", "CE": "CCL",
    "DT": "DTL", "TE": "TEL", "JS": "JRL", "JE": "JRL", "JW": "JRL",
    "CR": "CRL", "CP": "CRL", "BP": "BPLRT", "SE": "SKLRT", "SW": "SKLRT",
    "PE": "PGLRT", "PW": "PGLRT",
}
BUILDING_LINES = {"JRL", "CRL"}
CODE_RE = re.compile(r"^([A-Z]{2})(\d+[A-Za-z]?)$")


def fetch_stations():
    if os.path.exists(STATION_RAW):
        return json.load(open(STATION_RAW))
    req = urllib.request.Request(URL, data=urllib.parse.urlencode({"data": STATION_Q}).encode(),
                                 headers={"User-Agent": "hdb-estate-db/1.0"})
    with urllib.request.urlopen(req, timeout=140) as r:
        data = json.loads(r.read().decode())
    with open(STATION_RAW, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    return data


def build_stations():
    data = fetch_stations()
    by_key = {}
    for el in data.get("elements", []):
        t = el.get("tags", {})
        name = (t.get("name") or "").strip()
        raw_ref = (t.get("ref") or "").strip().upper()
        if not name or not raw_ref:
            continue
        codes, lines = [], []
        for part in re.split(r"[;,/]", raw_ref):
            m = CODE_RE.match(part.strip())
            if not m:
                continue
            line = PREFIX_LINE.get(m.group(1))
            if not line:
                continue
            codes.append(part.strip())
            if line not in lines:
                lines.append(line)
        # no recognised Singapore code -> Sentosa Express, Changi Skytrain, KTM
        if not codes:
            continue
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        if lon is None or lat is None:
            continue
        key = codes[0]
        # the same station appears as both a node and a building way; keep one
        if key in by_key:
            continue
        by_key[key] = {
            "name": name, "codes": codes, "lines": lines,
            "lon": round(lon, 5), "lat": round(lat, 5),
        }

    # merge entries that are the same station split across separate code nodes
    merged = {}
    for s in by_key.values():
        m = merged.setdefault(s["name"], {**s, "codes": [], "lines": []})
        for c in s["codes"]:
            if c not in m["codes"]:
                m["codes"].append(c)
        for l in s["lines"]:
            if l not in m["lines"]:
                m["lines"].append(l)

    feats = []
    for s in sorted(merged.values(), key=lambda x: x["name"]):
        open_lines = [l for l in s["lines"] if l not in BUILDING_LINES]
        building = not open_lines
        primary = (open_lines or s["lines"])[0]
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "name": s["name"],
                "codes": ", ".join(s["codes"]),
                "lines": ", ".join(s["lines"]),
                "colour": COLOURS.get(primary, "#8a8880"),
                "interchange": 1 if len(s["lines"]) > 1 else 0,
                "building": 1 if building else 0,
            },
        })
    out = os.path.join(HERE, "site", "stations.geojson")
    with open(out, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"))
    inter = sum(f["properties"]["interchange"] for f in feats)
    bld = sum(f["properties"]["building"] for f in feats)
    print(f"wrote {out}  {os.path.getsize(out)/1e3:.0f} KB  stations={len(feats)} "
          f"(interchanges={inter}, under construction={bld})")
