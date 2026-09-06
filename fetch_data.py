"""Download the source datasets from data.gov.sg into data/."""
import os, sys, time, requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
POLL = "https://api-open.data.gov.sg/v1/public/api/datasets/{}/poll-download"

DATASETS = [
    ("d_17f5382f26140b1fdae0ba2ef6239d2f", "hdb_property.csv",
     "HDB Property Information"),
    ("d_4765db0e87b9c86336792efe8a1f7a66", "planning_area.geojson",
     "Master Plan 2019 Planning Area Boundary (No Sea)"),
    # resale transactions, Jan 2017 onwards - republished monthly
    ("d_8b84c4ee58e3cfc0ece0d773c8ca6abc", "resale.csv",
     "Resale Flat Prices (registration date, 2017 onwards)"),
]


def poll(ds, tries=6):
    """data.gov.sg rate-limits back-to-back downloads (code 24); back off and retry."""
    delay = 10
    for attempt in range(tries):
        meta = requests.get(POLL.format(ds), timeout=90).json()
        if meta.get("code") == 0:
            return meta
        if meta.get("name") != "TOO_MANY_REQUESTS":
            sys.exit(f"poll-download failed for {ds}: {meta}")
        if attempt == tries - 1:
            sys.exit(f"poll-download still rate-limited after {tries} attempts: {ds}")
        print(f"  rate-limited, retrying in {delay}s…")
        time.sleep(delay)
        delay = min(delay * 2, 90)


# HDB has periodically closed one resale dataset and opened another (1990-1999,
# 2000-2012, 2012-2014, 2015-2016, 2017-onwards). When they open a "2027 onwards"
# dataset, the file we download simply stops growing and nothing else complains —
# the pipeline would keep publishing quietly stale prices. Watch the collection.
RESALE_COLLECTION = "189"
KNOWN_CHILDREN = {
    "d_8b84c4ee58e3cfc0ece0d773c8ca6abc",   # 2017-01 onwards  <- the one we use
    "d_43f493c6c50d54243cc1eab0df142d6a",   # 2000-01 to 2012-02
    "d_2d5ff9ea31397b66239f245f57751537",   # 2012-03 to 2014-12
    "d_ebc5ab87086db484f88045b47411ebc5",   # 1990-01 to 1999-12
    "d_ea9ed51da2787afaf8e51f827c304208",   # 2015-01 to 2016-12
}


def check_collection():
    url = ("https://api-production.data.gov.sg/v2/public/api/collections/"
           f"{RESALE_COLLECTION}/metadata")
    try:
        meta = requests.get(url, timeout=60).json()["data"]["collectionMetadata"]
    except Exception as e:
        print(f"  (could not check the resale collection: {e})")
        return
    new = set(meta.get("childDatasets", [])) - KNOWN_CHILDREN
    if new:
        print("  !! The resale collection has gained a dataset we do not read: "
              + ", ".join(sorted(new)))
        print("     HDB may have rolled over to a new period. Add it to DATASETS in "
              "fetch_data.py or new transactions will stop appearing.")
    else:
        print(f"  resale collection unchanged ({len(meta.get('childDatasets', []))} datasets)")


def main():
    os.makedirs(DATA, exist_ok=True)
    check_collection()
    changed = False
    for i, (ds, name, label) in enumerate(DATASETS):
        if i:
            time.sleep(3)          # stay under the rate limit rather than rely on retries
        meta = poll(ds)
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
