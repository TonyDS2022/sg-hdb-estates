"""URA Master Plan 2025 zoning: a light national map layer, plus an exact per-block zone.

Two outputs with different accuracy requirements:
  * site/zoning.geojson   - dissolved and simplified for drawing. 190 MB of parcels
                            becomes ~2 MB, and at ~5m tolerance the block-level zone
                            assignment still agrees with the raw polygons 99.99% of
                            the time. Only NON-residential land is emitted: 99.8% of
                            HDB blocks sit on RESIDENTIAL, so painting it would wash
                            the whole inhabited map in one colour and say nothing.
  * data/block_zoning.json - each block's own zone and GPR, computed against the RAW
                            polygons. Numbers in the panel stay exact; only the
                            picture is simplified.
"""
import csv, json, os, sys, time
import requests
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(DATA, "mp2025_landuse.geojson")
DS = "d_a8c3546b26712e35021f3a681d0353ae"          # Master Plan 2025 Land Use Layer
SIMPLIFY = 0.00005                                  # ~5 m
RES_FOR_LABEL = {'RESIDENTIAL', 'RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY',
                 'RESIDENTIAL / INSTITUTION', 'COMMERCIAL & RESIDENTIAL'}

# 33 URA categories -> the handful a resident actually reacts to. Only four can be
# painted: exactly four saturated hues pass the colour-vision checks all-pairs in both
# themes, and blue is already the block dots.
GROUP = {
    'COMMERCIAL':'com','COMMERCIAL / INSTITUTION':'com','HOTEL':'com','WHITE':'com',
    'COMMERCIAL & RESIDENTIAL':'com',
    'BUSINESS 1':'biz','BUSINESS 2':'biz','BUSINESS PARK':'biz','BUSINESS 1 - WHITE':'biz',
    'BUSINESS 2 - WHITE':'biz','BUSINESS PARK - WHITE':'biz','SPECIAL USE':'biz',
    'PARK':'park','OPEN SPACE':'park','BEACH AREA':'park','SPORTS & RECREATION':'park',
    'RESERVE SITE':'reserve',
}
# kept for the per-block field, but never painted
UNPAINTED = {
    'RESIDENTIAL':'res','RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY':'res',
    'RESIDENTIAL / INSTITUTION':'res',
    'CIVIC & COMMUNITY INSTITUTION':'civ','EDUCATIONAL INSTITUTION':'civ',
    'HEALTH & MEDICAL CARE':'civ','PLACE OF WORSHIP':'civ','CEMETERY':'civ',
}


def fetch():
    if os.path.exists(SRC):
        print(f"  using cached {os.path.basename(SRC)} ({os.path.getsize(SRC)/1e6:.0f} MB)")
        return
    for _ in range(6):
        m = requests.get(f"https://api-open.data.gov.sg/v1/public/api/datasets/{DS}/poll-download",
                         timeout=90).json()
        if m.get("code") == 0:
            break
        print("  rate-limited, waiting…"); time.sleep(12)
    else:
        sys.exit("could not obtain a download URL for the land use layer")
    r = requests.get(m["data"]["url"], timeout=1200, stream=True); r.raise_for_status()
    with open(SRC, "wb") as f:
        for c in r.iter_content(1 << 20):
            f.write(c)
    print(f"  downloaded {os.path.getsize(SRC)/1e6:.0f} MB")


def main():
    fetch()
    d = json.load(open(SRC))
    feats = d["features"]
    print(f"  {len(feats):,} parcels, {len({f['properties'].get('LU_DESC') for f in feats})} URA categories")

    # ---- visual layer: dissolve by group, then simplify ----
    by = {}
    for f in feats:
        g = GROUP.get(f["properties"].get("LU_DESC"))
        if not g:
            continue
        try:
            by.setdefault(g, []).append(shape(f["geometry"]).buffer(0))
        except Exception:
            pass
    out = []
    for g, polys in sorted(by.items()):
        merged = unary_union(polys).simplify(SIMPLIFY, preserve_topology=True)
        out.append({"type": "Feature", "properties": {"z": g}, "geometry": mapping(merged)})
    p = os.path.join(HERE, "site", "zoning.geojson")
    with open(p, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": out}, fh, separators=(",", ":"))
    print(f"  wrote {p}  {os.path.getsize(p)/1e6:.2f} MB  ({', '.join(sorted(by))})")

    # ---- plot-ratio layer ----
    # GPR is a number for only 29% of parcels: LND is landed housing and EVA/SDP mean
    # density is decided case by case. Those are not low values on a scale, they are
    # not-a-number, so they get their own neutral swatches rather than a ramp step.
    def band(v):
        try:
            g = float(v)
        except (TypeError, ValueError):
            if v == "LND":
                return "lnd"
            return "eva" if v in ("EVA", "SDP") else None
        if g <= 1.4: return "g1"
        if g <= 2.1: return "g2"
        if g <= 2.8: return "g3"
        if g <= 3.5: return "g4"
        return "g5"

    gby = {}
    for f in feats:
        k = band(f["properties"].get("GPR"))
        if not k:
            continue
        try:
            gby.setdefault(k, []).append(shape(f["geometry"]).buffer(0))
        except Exception:
            pass
    gout = []
    for k, polys in sorted(gby.items()):
        merged = unary_union(polys).simplify(SIMPLIFY, preserve_topology=True)
        gout.append({"type": "Feature", "properties": {"g": k}, "geometry": mapping(merged)})
    gp = os.path.join(HERE, "site", "gpr.geojson")
    with open(gp, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": gout}, fh, separators=(",", ":"))
    print(f"  wrote {gp}  {os.path.getsize(gp)/1e6:.2f} MB  "
          + ", ".join(f"{k}:{len(v):,}" for k, v in sorted(gby.items())))

    # ---- plot-ratio labels ----
    # One label per PARCEL, not per dissolved band: a dissolved band has a single
    # centroid for the whole island. The median residential parcel is 260 m2 — an
    # individual terrace plot — so small ones are dropped; labelling 84k of them would
    # be noise that collision detection discards anyway. representative_point() rather
    # than centroid, which can fall outside a concave parcel.
    MIN_AREA = 1000
    labels = []
    for f in feats:
        if f["properties"].get("LU_DESC") not in RES_FOR_LABEL:
            continue
        try:
            if float(f["properties"].get("SHAPE.AREA") or 0) < MIN_AREA:
                continue
        except (TypeError, ValueError):
            continue
        v = f["properties"].get("GPR")
        k = band(v)
        if not k:
            continue
        txt = str(float(v)) if k.startswith("g") else ("LND" if k == "lnd" else "EVA")
        try:
            pt = shape(f["geometry"]).buffer(0).representative_point()
        except Exception:
            continue
        labels.append({"type": "Feature",
                       "properties": {"t": txt, "b": k},
                       "geometry": {"type": "Point",
                                    "coordinates": [round(pt.x, 5), round(pt.y, 5)]}})
    lp = os.path.join(HERE, "site", "gpr_labels.geojson")
    with open(lp, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": labels}, fh, separators=(",", ":"))
    print(f"  wrote {lp}  {os.path.getsize(lp)/1e3:.0f} KB  {len(labels):,} parcel labels "
          f"(>= {MIN_AREA} m2)")

    # ---- per-block zone + GPR, from the RAW polygons ----
    geoms, props = [], []
    for f in feats:
        lu = f["properties"].get("LU_DESC")
        z = GROUP.get(lu) or UNPAINTED.get(lu) or "other"
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        parts = g.geoms if g.geom_type == "MultiPolygon" else [g]
        for part in parts:
            geoms.append(part)
            props.append((z, lu, f["properties"].get("GPR")))
    tree = STRtree(geoms)

    rows = list(csv.DictReader(open(os.path.join(DATA, "hdb_blocks.csv"))))
    res, hit = {}, 0
    for r in rows:
        if not r["lat"]:
            continue
        pt = Point(float(r["lon"]), float(r["lat"]))
        for i in tree.query(pt):
            if geoms[i].contains(pt):
                z, lu, gpr = props[i]
                res[f'{r["blk_no"]}|{r["street"]}'] = {"z": z, "lu": lu, "gpr": gpr}
                hit += 1
                break
    q = os.path.join(DATA, "block_zoning.json")
    with open(q, "w") as fh:
        json.dump(res, fh, separators=(",", ":"), sort_keys=True)
    print(f"  wrote {q}  {hit:,}/{len(rows):,} blocks matched to a parcel")


if __name__ == "__main__":
    main()
