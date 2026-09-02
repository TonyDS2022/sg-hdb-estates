"""Download the source datasets from data.gov.sg into data/."""
import os, sys, requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
POLL = "https://api-open.data.gov.sg/v1/public/api/datasets/{}/poll-download"

DATASETS = [
    ("d_17f5382f26140b1fdae0ba2ef6239d2f", "hdb_property.csv",
     "HDB Property Information"),
    ("d_4765db0e87b9c86336792efe8a1f7a66", "planning_area.geojson",
     "Master Plan 2019 Planning Area Boundary (No Sea)"),
]


def main():
    os.makedirs(DATA, exist_ok=True)
    changed = False
    for ds, name, label in DATASETS:
        meta = requests.get(POLL.format(ds), timeout=90).json()
        if meta.get("code") != 0:
            sys.exit(f"poll-download failed for {ds}: {meta}")
        # the S3 URL is presigned - it must be requested verbatim, so do not let
        # anything re-encode it (urllib.request re-quotes it and gets a 403)
        r = requests.get(meta["data"]["url"], timeout=600)
        r.raise_for_status()
        path = os.path.join(DATA, name)
        old = open(path, "rb").read() if os.path.exists(path) else None
        if old == r.content:
            print(f"  unchanged  {name:26s} {len(r.content)/1e6:.2f} MB  ({label})")
            continue
        with open(path, "wb") as f:
            f.write(r.content)
        changed = True
        delta = "" if old is None else f"  ({len(r.content)-len(old):+,} bytes)"
        print(f"  updated    {name:26s} {len(r.content)/1e6:.2f} MB{delta}  ({label})")
    print("sources changed" if changed else "sources already current")


if __name__ == "__main__":
    main()
