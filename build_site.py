"""Emit a compact, dictionary-encoded data.json for the HTML report."""
import csv, json, os, re, sys, datetime, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geocode import expand   # reuse the street-abbreviation table used for geocoding

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, SITE = os.path.join(HERE, "data"), os.path.join(HERE, "site")
os.makedirs(SITE, exist_ok=True)


def main():
    rows = list(csv.DictReader(open(os.path.join(DATA, "hdb_blocks.csv"))))

    # dictionary-encode the repeated strings so the payload stays small
    dicts = {k: [] for k in ("street", "town", "planning_area", "region", "project")}
    index = {k: {} for k in dicts}

    def code(field, val):
        val = val or ""
        d, ix = dicts[field], index[field]
        if val not in ix:
            ix[val] = len(d)
            d.append(val)
        return ix[val]

    out = []
    for r in rows:
        has_geo = bool(r["lat"])
        out.append([
            r["blk_no"],
            code("street", r["street"]),
            code("project", r["project"]),
            code("town", r["town"]),
            code("planning_area", r["planning_area"]),
            code("region", r["region"]),
            round(float(r["lat"]), 6) if has_geo else None,
            round(float(r["lon"]), 6) if has_geo else None,
            int(r["top_year"]),
            int(r["mop_year_est"]),
            int(r["total_units"]),
            int(r["max_floor_lvl"]),
            int(r["units_1r"]), int(r["units_2r"]), int(r["units_3r"]),
            int(r["units_4r"]), int(r["units_5r"]), int(r["units_exec"]),
            int(r["units_multigen"]) + int(r["units_studio"]),
            int(r["units_rental"]),
            r["postal"],
            1 if r["has_commercial"] == "True" else 0,
        ])

    # HDB writes streets abbreviated ("ANG MO KIO AVE 10"); property portals expect the
    # expanded form. Emit a parallel dictionary so the page can build search queries.
    def nice(v):
        return re.sub(r"(?<=\w)'S\b", "'s", expand(v).title())

    street_full = [nice(v) for v in dicts["street"]]

    geo = sum(1 for r in rows if r["lat"])
    years = [int(r["top_year"]) for r in rows]
    payload = {
        "meta": {
            "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "blocks": len(rows),
            "units": sum(int(r["total_units"]) for r in rows),
            "towns": len({r["town"] for r in rows}),
            "planning_areas": len({r["planning_area"] for r in rows if r["planning_area"]}),
            "year_min": min(years), "year_max": max(years),
            "geocoded": geo,
            "geocoded_pct": round(geo / len(rows) * 100, 1),
            "this_year": datetime.date.today().year,
            "sources": [
                ["HDB Property Information", "Housing & Development Board via data.gov.sg",
                 "blocks, dwelling units, flat mix, year completed (TOP)"],
                ["OneMap Search API", "Singapore Land Authority",
                 "latitude / longitude / postal code per block"],
                ["Master Plan 2019 Planning Area Boundary", "Urban Redevelopment Authority via data.gov.sg",
                 "URA planning area + region, assigned by point-in-polygon"],
            ],
        },
        "cols": ["blk", "street", "project", "town", "pa", "region", "lat", "lon", "top", "mop",
                 "units", "floors", "u1", "u2", "u3", "u4", "u5", "uex", "uoth",
                 "urent", "postal", "comm"],
        "dict": {**{k: dicts[k] for k in dicts}, "street_full": street_full},
        "rows": out,
    }
    p = os.path.join(SITE, "data.json")
    with open(p, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"wrote {p}  {os.path.getsize(p)/1e6:.2f} MB  rows={len(out)} geocoded={geo}")
    write_config()


def write_config():
    """Emit site/config.js with the Mapbox token, kept out of the HTML itself.

    A Mapbox public (pk.) token is necessarily visible to the browser - that is what
    it is for - but keeping it in a generated, git-ignored file means the token is
    never baked into source, and swapping accounts needs no edit to the page.
    """
    tok = os.environ.get("MAPBOX_TOKEN", "").strip()
    if not tok:
        f = os.path.join(HERE, ".mapbox_token")
        if os.path.exists(f):
            tok = open(f).read().strip()
    cfg = {
        "token": tok,
        "styles": {"light": "mapbox://styles/mapbox/light-v11",
                   "dark": "mapbox://styles/mapbox/dark-v11"},
    }
    p = os.path.join(SITE, "config.js")
    with open(p, "w") as f:
        f.write("window.MAP_CONFIG = " + json.dumps(cfg) + ";\n")
    os.chmod(p, 0o600)
    print("wrote config.js  basemap=" + ("mapbox (token loaded)" if tok else "NONE - falling back to scatter"))


if __name__ == "__main__":
    main()
