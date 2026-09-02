"""Join HDB block data + OneMap geocodes + URA planning areas into a single database."""
import csv, json, os, re, sys, sqlite3, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geocode import expand

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
THIS_YEAR = datetime.date.today().year
MOP_YEARS = 5          # standard HDB Minimum Occupation Period
LEASE_YEARS = 99

TOWNS = {
    "AMK": "Ang Mo Kio", "BB": "Bukit Batok", "BD": "Bedok", "BH": "Bishan",
    "BM": "Bukit Merah", "BP": "Bukit Panjang", "BT": "Bukit Timah",
    "CCK": "Choa Chu Kang", "CL": "Clementi", "CT": "Central Area",
    "GL": "Geylang", "HG": "Hougang", "JE": "Jurong East", "JW": "Jurong West",
    "KWN": "Kallang/Whampoa", "MP": "Marine Parade", "PG": "Punggol",
    "PRC": "Pasir Ris", "QT": "Queenstown", "SB": "Sembawang", "SGN": "Serangoon",
    "SK": "Sengkang", "TAP": "Tampines", "TG": "Tengah", "TP": "Toa Payoh",
    "WL": "Woodlands", "YS": "Yishun",
}

UNIT_COLS = ["1room_sold", "2room_sold", "3room_sold", "4room_sold", "5room_sold",
             "exec_sold", "multigen_sold", "studio_apartment_sold"]
RENTAL_COLS = ["1room_rental", "2room_rental", "3room_rental", "other_room_rental"]


# ---------- point-in-polygon ----------
def ring_contains(ring, x, y):
    """Ray-casting test for a single linear ring."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def poly_contains(rings, x, y):
    """Outer ring minus holes."""
    if not ring_contains(rings[0], x, y):
        return False
    return not any(ring_contains(h, x, y) for h in rings[1:])


class AreaIndex:
    """Bounding-box prefiltered polygon lookup over the URA planning areas."""

    def __init__(self, path):
        gj = json.load(open(path))
        self.items = []
        for f in gj["features"]:
            p, g = f["properties"], f["geometry"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for rings in polys:
                xs = [c[0] for c in rings[0]]
                ys = [c[1] for c in rings[0]]
                self.items.append({
                    "area": p["PLN_AREA_N"].title(),
                    "region": p["REGION_N"].title(),
                    "rings": rings,
                    "bbox": (min(xs), min(ys), max(xs), max(ys)),
                })

    def lookup(self, lon, lat):
        best = None
        for it in self.items:
            x0, y0, x1, y1 = it["bbox"]
            if x0 <= lon <= x1 and y0 <= lat <= y1 and poly_contains(it["rings"], lon, lat):
                return it["area"], it["region"]
            if best is None and x0 - 0.004 <= lon <= x1 + 0.004 and y0 - 0.004 <= lat <= y1 + 0.004:
                best = it
        # coastal reclamation / boundary slop: fall back to nearest bbox
        return (best["area"], best["region"]) if best else (None, None)


# OneMap returns a BUILDING name for many blocks - the HDB project/precinct name
# ("Clementi Peaks", "Eunos Spring"). It is embedded in the ADDRESS string between the
# road name and the postal code, so it can be recovered without re-geocoding.
# It also sometimes names a co-located FACILITY instead (a childcare centre, a police
# post, "HDB Public Shelters"); those are filtered out. NB: "Depot Heights" is a real
# estate, so DEPOT must not be in this pattern.
FACILITY = re.compile(
    r"\b(HAWKER|MARKET|COMMUNITY (CENTRE|CLUB)|PUBLIC SHELTER|SHELTERS?|CAR ?PARK|CARPARK|"
    r"MULTI-?STOREY|CHILD ?CARE|CHILDREN|CHILD DEVELOPMENT|KINDER\w*|POLYCLINIC|SCHOOL\w*|"
    r"MOSQUE|TEMPLE|CHURCH|SUBSTATION|PUMPING|SERVICE RESERVOIR|NEIGHBOURHOOD POLICE|"
    r"POLICE (POST|CENTRE)|CLINIC|SPORTS|SWIMMING|LIBRARY|BUS (INTERCHANGE|TERMINAL)|"
    r"FIRE STATION|SENIOR CARE|FAMILY SERVICE|STUDENT ?CARE|EATING HOUSE|FOOD CENTRE|"
    # "PRE-SCHOOL" needed the hyphen, so plain "Preschool" slipped through and 60-odd
    # PCF Sparkletots childcare centres were published as HDB project names.
    r"PRE ?-? ?SCHOOL\w*|SPARKLETOTS|EDUCARE|SCHOOLHOUSE|LEARNING (CENTRE|COVE|CENTER)|"
    r"ENRICHMENT|DAY ?CARE|NURSERY|TUITION|VETERINARY|ANIMAL MEDICAL|MONTESSORI|"
    r"SALVATION ARMY|PTE\.? ?LTD\.?|\bLTD\.?)\b|\(BLK",
    re.I)


def title_case(v):
    return re.sub(r"(?<=\w)'S\b", "'s", v.title())


def project_of(address, blk, street):
    """Pull the building/project name out of a OneMap ADDRESS string."""
    if not address:
        return ""
    s = address.strip()
    pre = blk.upper() + " "
    if s.upper().startswith(pre):
        s = s[len(pre):]
    s = re.sub(r"\s*SINGAPORE\s+\d{6}\s*$", "", s)
    road = expand(street)
    if not s.upper().startswith(road):
        return ""              # non-exact road match: do not guess
    s = s[len(road):].strip()
    if not s or FACILITY.search(s):
        return ""
    return title_case(s)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return None if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def rollup(blocks):
    """Aggregate blocks up to the HDB estate (town) level."""
    by = {}
    for b in blocks:
        by.setdefault(b["town"], []).append(b)
    out = []
    for town, bs in sorted(by.items()):
        units = sum(b["total_units"] for b in bs)
        geo = [b for b in bs if b["lat"] is not None]
        pas = {}
        for b in bs:
            if b["planning_area"]:
                pas[b["planning_area"]] = pas.get(b["planning_area"], 0) + b["total_units"]
        tops = [b["top_year"] for b in bs]
        mix = {k: sum(b[k] for b in bs) for k in
               ("units_1r", "units_2r", "units_3r", "units_4r", "units_5r",
                "units_exec", "units_multigen", "units_studio", "units_rental")}
        top_pa = sorted(pas.items(), key=lambda kv: -kv[1])
        regions = {}
        for b in bs:
            if b["region"]:
                regions[b["region"]] = regions.get(b["region"], 0) + b["total_units"]
        out.append({
            "town_code": bs[0]["town_code"],
            "town": town,
            "blocks": len(bs),
            "total_units": units,
            "rental_units": mix["units_rental"],
            "first_top": min(tops),
            "last_top": max(tops),
            "median_top": median(tops),
            "median_age": THIS_YEAR - (median(tops) or THIS_YEAR),
            "mop_reached_units": sum(b["total_units"] for b in bs if b["mop_status"] == "reached"),
            "mop_upcoming_units": sum(b["total_units"] for b in bs if b["mop_status"] == "upcoming"),
            "avg_storeys": round(sum(b["max_floor_lvl"] for b in bs) / len(bs), 1),
            "centroid_lat": round(sum(b["lat"] for b in geo) / len(geo), 6) if geo else None,
            "centroid_lon": round(sum(b["lon"] for b in geo) / len(geo), 6) if geo else None,
            "geocoded_blocks": len(geo),
            "region": max(regions, key=regions.get) if regions else None,
            "planning_areas": "; ".join(n for n, _ in top_pa),
            "main_planning_area": top_pa[0][0] if top_pa else None,
            **mix,
        })
    return out


def main():
    idx = AreaIndex(os.path.join(DATA, "planning_area.geojson"))

    geo = {}
    cache = os.path.join(DATA, "geocode_cache.jsonl")
    if os.path.exists(cache):
        for line in open(cache):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("lat") is not None:
                geo[r["key"]] = r

    rows = [r for r in csv.DictReader(open(os.path.join(DATA, "hdb_property.csv")))
            if r["residential"] == "Y"]

    out = []
    for r in rows:
        key = f'{r["blk_no"]}|{r["street"]}'
        g = geo.get(key)
        lat = g["lat"] if g else None
        lon = g["lon"] if g else None
        area = region = None
        if lat is not None:
            area, region = idx.lookup(lon, lat)
        top = int(r["year_completed"])
        units = int(r["total_dwelling_units"])
        mop = top + MOP_YEARS
        out.append({
            "blk_no": r["blk_no"],
            "street": r["street"],
            "project": project_of((g or {}).get("address", ""), r["blk_no"], r["street"]),
            "address": (g or {}).get("address", ""),
            # OneMap returns the literal "NIL" when a block has no postal code
            "postal": (lambda v: v if v.isdigit() else "")((g or {}).get("postal", "") or ""),
            "town_code": r["bldg_contract_town"],
            "town": TOWNS.get(r["bldg_contract_town"], r["bldg_contract_town"]),
            "planning_area": area,
            "region": region,
            "lat": lat, "lon": lon,
            "geocode_match": (g or {}).get("match", "missing"),
            "top_year": top,
            "mop_year_est": mop,
            "mop_status": "reached" if mop <= THIS_YEAR else "upcoming",
            "age_years": THIS_YEAR - top,
            "lease_remaining_est": LEASE_YEARS - (THIS_YEAR - top),
            "max_floor_lvl": int(r["max_floor_lvl"]),
            "total_units": units,
            "units_1r": int(r["1room_sold"]), "units_2r": int(r["2room_sold"]),
            "units_3r": int(r["3room_sold"]), "units_4r": int(r["4room_sold"]),
            "units_5r": int(r["5room_sold"]), "units_exec": int(r["exec_sold"]),
            "units_multigen": int(r["multigen_sold"]),
            "units_studio": int(r["studio_apartment_sold"]),
            "units_rental": sum(int(r[c]) for c in RENTAL_COLS),
            "has_commercial": r["commercial"] == "Y",
            "has_market_hawker": r["market_hawker"] == "Y",
            "has_mscp": r["multistorey_carpark"] == "Y",
            "has_pavilion": r["precinct_pavilion"] == "Y",
        })

    # ---------- sqlite ----------
    db = os.path.join(DATA, "hdb.sqlite")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    cols = list(out[0].keys())
    decl = ", ".join(f'"{c}"' for c in cols)
    con.execute(f"CREATE TABLE blocks ({decl})")
    con.executemany(f"INSERT INTO blocks VALUES ({','.join('?' * len(cols))})",
                    [[b[c] for c in cols] for b in out])
    for c in ["town", "planning_area", "region", "top_year", "mop_year_est"]:
        con.execute(f'CREATE INDEX ix_{c} ON blocks("{c}")')
    con.commit()
    con.close()

    with open(os.path.join(DATA, "hdb_blocks.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    with open(os.path.join(DATA, "hdb_blocks.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))

    estates = rollup(out)
    ecols = list(estates[0].keys())
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE estates (" + ", ".join(f'"{c}"' for c in ecols) + ")")
    con.executemany(f"INSERT INTO estates VALUES ({','.join('?' * len(ecols))})",
                    [[e[c] for c in ecols] for e in estates])
    con.commit()
    con.close()
    with open(os.path.join(DATA, "hdb_estates.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ecols)
        w.writeheader()
        w.writerows(estates)

    geocoded = sum(1 for b in out if b["lat"] is not None)
    witharea = sum(1 for b in out if b["planning_area"])
    print(f"blocks={len(out)} geocoded={geocoded} ({geocoded/len(out)*100:.1f}%) "
          f"planning_area={witharea} ({witharea/len(out)*100:.1f}%) "
          f"units={sum(b['total_units'] for b in out):,} estates={len(estates)}")
    return out


if __name__ == "__main__":
    main()
