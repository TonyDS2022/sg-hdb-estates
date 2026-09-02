"""Aggregate HDB resale transactions into per-block and per-town summaries.

The raw file is ~240k rows; shipping it to the browser is not an option. Two
aggregates carry the useful signal instead:
  * per (block, flat type)      - what flats in THIS block actually sold for
  * per (town, flat type, year) - a trend line small enough to filter live
"""
import csv, json, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SQM_TO_SQFT = 10.763910417

TYPE_KEY = {
    "1 ROOM": "u1", "2 ROOM": "u2", "3 ROOM": "u3", "4 ROOM": "u4",
    "5 ROOM": "u5", "EXECUTIVE": "uex", "MULTI-GENERATION": "uoth",
}


def med(xs):
    return round(st.median(xs)) if xs else None


def main():
    rows = list(csv.DictReader(open(os.path.join(DATA, "resale.csv"))))
    months = sorted({r["month"] for r in rows})
    latest, base = months[-1], months[0]
    # a rolling 12-month window ending at the newest month in the file
    y, m = int(latest[:4]), int(latest[5:7])
    cutoff = f"{y - 1:04d}-{m:02d}"

    def midx(mo):
        """Months since the first month in the file — cheaper than shipping strings."""
        return (int(mo[:4]) - int(base[:4])) * 12 + (int(mo[5:7]) - int(base[5:7]))

    per_block, per_town = {}, {}
    skipped = 0
    for r in rows:
        key = TYPE_KEY.get(r["flat_type"])
        if not key:
            skipped += 1
            continue
        price = float(r["resale_price"])
        area = float(r["floor_area_sqm"] or 0)
        rec = per_block.setdefault((r["block"].upper(), r["street_name"].upper(), key),
                                   {"n": 0, "ltm": [], "psf": [], "last": "", "lastp": 0.0})
        rec["n"] += 1
        if r["month"] > cutoff:
            rec["ltm"].append(price)
            if area:
                rec["psf"].append(price / (area * SQM_TO_SQFT))
        if r["month"] > rec["last"]:
            rec["last"], rec["lastp"] = r["month"], price
        per_town.setdefault((r["town"], key, r["month"][:4]), []).append(price)

    # The headline is the last-twelve-month median. A median across the whole 2017-2026
    # span understates current value by ~23% (p25 +13%, p75 +33%) because the market rose
    # sharply from 2020 — it averages two different markets. Where a pair has no sale in
    # the window, the most recent actual sale is carried instead, dated so it reads as stale.
    blocks = {}
    for (blk, street, key), v in per_block.items():
        blocks.setdefault(f"{blk}|{street}", {})[key] = [
            len(v["ltm"]),                                       # sales in the LTM window
            round(med(v["ltm"]) / 1000) if v["ltm"] else 0,      # LTM median, S$ thousands
            round(med(v["psf"])) if v["psf"] else 0,             # LTM median S$ per sqft
            v["n"],                                              # sales since 2017 (context)
            round(v["lastp"] / 1000),                            # most recent sale price
            midx(v["last"]),                                     # months since base
        ]

    towns = [[t, k, int(yr), len(ps), round(med(ps) / 1000)]
             for (t, k, yr), ps in sorted(per_town.items())]

    out = {
        "base_month": base, "latest_month": latest, "window_from": cutoff,
        "transactions": len(rows) - skipped,
        "blocks": blocks, "towns": towns,
    }
    p = os.path.join(DATA, "resale_agg.json")
    with open(p, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"wrote {p}  {os.path.getsize(p)/1e6:.2f} MB")
    print(f"  {len(rows)-skipped:,} transactions  {base} → {latest}  (12m window from {cutoff})")
    pairs = sum(len(v) for v in blocks.values())
    ltm = sum(1 for b in blocks.values() for a in b.values() if a[0])
    print(f"  {len(blocks):,} blocks with sales, {pairs:,} block×type pairs")
    print(f"  {ltm:,} pairs ({ltm/pairs*100:.0f}%) sold within the LTM window; the rest carry their last sale")
    print(f"  {len(towns):,} town×type×year rows for the trend chart")
    if skipped:
        print(f"  {skipped} rows skipped (unmapped flat_type)")


if __name__ == "__main__":
    main()
