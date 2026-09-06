"""Geocode MOE schools by postal code and emit site/schools.geojson."""
import csv, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geocode as G

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "schools_geocoded.json")

# The 1km / 2km home-to-school distance priority in P1 registration applies to
# PRIMARY schools only, which is the split that matters for a housing map.
LEVEL = {
    "PRIMARY": "P", "MIXED LEVEL (P1-S4)": "P",
    "SECONDARY (S1-S5)": "S", "SECONDARY (S1-S4)": "S",
    "MIXED LEVEL (S1-JC2)": "S", "MIXED LEVEL (S1-S5, JC1-JC2)": "S",
    "JUNIOR COLLEGE": "J", "CENTRALISED INSTITUTE": "J",
}
LEVEL_NAME = {"P": "Primary", "S": "Secondary", "J": "Junior College"}


# The source is entirely uppercase, so names must be title-cased for display — but a
# blind .title() turns real acronyms into words ("CHIJ" -> "Chij"). Only two genuine
# acronyms occur in the 337 names; everything else is an ordinary word.
ACRONYMS = {"CHIJ", "NUS"}


def nice_name(v):
    out = " ".join(w if w in ACRONYMS else w.title() for w in v.split())
    # "St. Joseph'S" -> "St. Joseph's"; the apostrophe defeats str.title()
    return re.sub(r"(?<=\w)'S\b", "'s", out)


def main():
    rows = list(csv.DictReader(open(os.path.join(DATA, "schools.csv"), encoding="utf-8-sig")))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [r for r in rows if r["postal_code"] not in cache]
    print(f"schools={len(rows)} cached={len(cache)} to geocode={len(todo)}")

    for i, r in enumerate(todo, 1):
        pc = r["postal_code"]
        hit = None
        for attempt in range(4):
            try:
                G.throttle()
                res = G.onemap(pc).get("results", [])
                # a 6-digit postal code resolves to exactly one building
                hit = next((x for x in res if x.get("POSTAL") == pc), res[0] if res else None)
                G.reward()
                break
            except G.RateLimited:
                G.penalise(); time.sleep(min(2 ** attempt, 20))
            except Exception:
                time.sleep(1.5)
        cache[pc] = {"lat": float(hit["LATITUDE"]), "lon": float(hit["LONGITUDE"])} if hit else None
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
            json.dump(cache, open(CACHE, "w"))
    json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True)

    feats, missing = [], []
    for r in rows:
        g = cache.get(r["postal_code"])
        lvl = LEVEL.get(r["mainlevel_code"])
        if not g or not lvl:
            missing.append((r["school_name"], r["mainlevel_code"], "no geocode" if not g else "unmapped level"))
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(g["lon"], 5), round(g["lat"], 5)]},
            "properties": {
                "n": nice_name(r["school_name"]),
                "l": lvl,
                "t": r["type_code"].title().replace("Sch", "School").replace("Schoolool", "School"),
                "g": {"CO-ED SCHOOL": "", "BOYS' SCHOOL": "Boys", "GIRLS' SCHOOL": "Girls"}.get(r["nature_code"], ""),
                "u": r["url_address"],
                "p": r["postal_code"],
            },
        })
    feats.sort(key=lambda f: f["properties"]["n"])
    out = os.path.join(HERE, "site", "schools.geojson")
    with open(out, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"), sort_keys=True)
    import collections
    c = collections.Counter(f["properties"]["l"] for f in feats)
    print(f"wrote {out}  {os.path.getsize(out)/1e3:.0f} KB  schools={len(feats)}")
    print("  by level: " + ", ".join(f"{LEVEL_NAME[k]} {v}" for k, v in sorted(c.items())))
    if missing:
        print(f"  {len(missing)} skipped:", missing[:5])


if __name__ == "__main__":
    main()
