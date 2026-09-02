"""QA the assembled database: coverage, bounds, duplicates, and geocode outliers."""
import csv, json, math, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
# generous bounding box for Singapore incl. offshore islands
LAT_LO, LAT_HI, LON_LO, LON_HI = 1.15, 1.50, 103.58, 104.10

def hav(a, b, c, d):
    R = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(x))

def median(xs):
    s = sorted(xs); n = len(s)
    return s[n//2] if n % 2 else (s[n//2-1] + s[n//2]) / 2

def main():
    rows = list(csv.DictReader(open(os.path.join(DATA, "hdb_blocks.csv"))))
    src = [r for r in csv.DictReader(open(os.path.join(DATA, "hdb_property.csv")))
           if r["residential"] == "Y"]
    fails = []
    def chk(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<34} {detail}")
        if not ok:
            fails.append(name)

    print("\nDatabase QA\n" + "-" * 72)
    # 1 reconciliation against the source
    chk("Row count matches source", len(rows) == len(src), f"{len(rows)} rows")
    su = sum(int(r["total_dwelling_units"]) for r in src)
    ou = sum(int(r["total_units"]) for r in rows)
    chk("Unit total matches source", su == ou, f"{ou:,} units")
    # total_dwelling_units counts rental flats, which the *_sold columns exclude
    sold = sum(int(r[c]) for r in rows for c in
               ("units_1r","units_2r","units_3r","units_4r","units_5r",
                "units_exec","units_multigen","units_studio"))
    rent = sum(int(r["units_rental"]) for r in rows)
    chk("Sold + rental reconciles to total", sold + rent == ou,
        f"sold {sold:,} + rental {rent:,} = {sold+rent:,} vs {ou:,}")

    # 2 geocode coverage
    geo = [r for r in rows if r["lat"]]
    pct = len(geo) / len(rows) * 100
    chk("Geocode coverage >= 99%", pct >= 99, f"{len(geo):,}/{len(rows):,} ({pct:.2f}%)")
    mq = collections.Counter(r["geocode_match"] for r in rows)
    chk("No fuzzy/error matches", mq["fuzzy"] + mq["error"] == 0, dict(mq))

    # 3 bounds
    oob = [r for r in geo if not (LAT_LO <= float(r["lat"]) <= LAT_HI
                                  and LON_LO <= float(r["lon"]) <= LON_HI)]
    chk("All coords inside Singapore", not oob,
        f"{len(oob)} outside" + (f" e.g. {oob[0]['blk_no']} {oob[0]['street']}" if oob else ""))

    # 4 planning area assignment
    pa = [r for r in geo if r["planning_area"]]
    chk("Planning area for every geocode", len(pa) == len(geo), f"{len(pa):,}/{len(geo):,}")

    # 5 duplicate coordinates - a sign of a wrong match
    dup = collections.Counter((r["lat"], r["lon"]) for r in geo)
    bad = [(k, v) for k, v in dup.items() if v > 2]
    chk("No coordinate collisions >2 blocks", not bad, f"{len(bad)} coords shared by >2 blocks")

    # 6 outliers: distance from the block to its own town's centre
    bytown = collections.defaultdict(list)
    for r in geo:
        bytown[r["town"]].append(r)
    far = []
    for town, bs in bytown.items():
        mla = median([float(b["lat"]) for b in bs])
        mlo = median([float(b["lon"]) for b in bs])
        for b in bs:
            d = hav(mla, mlo, float(b["lat"]), float(b["lon"]))
            if d > 8:
                far.append((round(d, 1), town, b["blk_no"], b["street"], b["planning_area"]))
    far.sort(reverse=True)
    chk("No block >8km from its town centre", not far, f"{len(far)} outliers")
    for f in far[:12]:
        print(f"        {f[0]:>5} km  {f[1]:<16} {f[2]} {f[3]:<26} -> {f[4]}")

    # 7 town -> planning area coherence
    print("\n  HDB town -> dominant URA planning area")
    incoherent = 0
    for town, bs in sorted(bytown.items()):
        c = collections.Counter(b["planning_area"] for b in bs if b["planning_area"])
        if not c:
            continue
        top, n = c.most_common(1)[0]
        share = n / sum(c.values()) * 100
        if share < 60:
            incoherent += 1
            extra = "  <- spread across " + ", ".join(f"{k} {v}" for k, v in c.most_common(4))
        else:
            extra = ""
        print(f"    {town:<17} {top:<18} {share:5.1f}%{extra}")
    print("-" * 72)
    print(f"{'ALL CHECKS PASS' if not fails else 'FAILED: ' + ', '.join(fails)}")
    print(f"({incoherent} towns straddle multiple planning areas — expected, not a defect)\n")

if __name__ == "__main__":
    main()
