"""Geocode every residential HDB block via OneMap. Resumable: appends to cache.jsonl."""
import csv, json, os, queue, threading, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "geocode_cache.jsonl")

TOKEN = os.environ.get("ONEMAP_TOKEN", "").strip()
FLOOR = 1.0 / (4.5 if TOKEN else 2.6)   # min seconds between calls
CEIL = 1.0
THREADS = 6
MAX_TRIES = 7

_lock = threading.Lock()
_next_at = [0.0]
_interval = [FLOOR]
_ok_streak = [0]

def throttle():
    """Global pacer, adaptive: widens on 429, decays back toward FLOOR on success."""
    with _lock:
        now = time.monotonic()
        wait = max(0.0, _next_at[0] - now)
        _next_at[0] = max(now, _next_at[0]) + _interval[0]
    if wait:
        time.sleep(wait)

def penalise():
    with _lock:
        _interval[0] = min(_interval[0] * 1.25, CEIL)
        _ok_streak[0] = 0

def reward():
    with _lock:
        _ok_streak[0] += 1
        if _ok_streak[0] >= 30 and _interval[0] > FLOOR:
            _interval[0] = max(_interval[0] * 0.85, FLOOR)
            _ok_streak[0] = 0

URL = "https://www.onemap.gov.sg/api/common/elastic/search"
_tl = threading.local()


class RateLimited(Exception):
    pass


def session():
    """Per-thread pooled session: keep-alive avoids a TLS handshake per call."""
    if not hasattr(_tl, "s"):
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0", "Connection": "keep-alive"})
        if TOKEN:
            s.headers["Authorization"] = TOKEN
        s.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=8))
        _tl.s = s
    return _tl.s


def onemap(term):
    r = session().get(URL, params={"searchVal": term, "returnGeom": "Y",
                                   "getAddrDetails": "Y", "pageNum": 1}, timeout=30)
    if r.status_code == 429:
        raise RateLimited()
    r.raise_for_status()
    return r.json()


ABBR = {
    "AVE": "AVENUE", "ST": "STREET", "RD": "ROAD", "DR": "DRIVE", "CL": "CLOSE",
    "CRES": "CRESCENT", "PL": "PLACE", "LOR": "LORONG", "BT": "BUKIT", "JLN": "JALAN",
    "TG": "TANJONG", "UPP": "UPPER", "CTRL": "CENTRAL", "GDNS": "GARDENS",
    "TER": "TERRACE", "HTS": "HEIGHTS", "PK": "PARK", "WK": "WALK", "MKT": "MARKET",
    "NTH": "NORTH", "STH": "SOUTH", "KG": "KAMPONG", "C'WEALTH": "COMMONWEALTH",
    "SQ": "SQUARE", "CTR": "CENTRE", "IND": "INDUSTRIAL", "EST": "ESTATE",
}

def expand(s):
    return " ".join(ABBR.get(w, w) for w in s.upper().replace(",", " ").split())

def pick(res, blk, street):
    """Choose best OneMap hit: exact block + road match wins, then exact block, then first."""
    if not res:
        return None, "none"
    want_road = expand(street)
    exact = [r for r in res if r.get("BLK_NO", "").strip().upper() == blk.strip().upper()]
    for r in exact:
        if r.get("ROAD_NAME", "").strip().upper() == want_road:
            return r, "exact"
    if exact:
        return exact[0], "block"
    return res[0], "fuzzy"

def load_done():
    done = set()
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["key"])
                except Exception:
                    pass
    return done

def main():
    rows = [r for r in csv.DictReader(open(os.path.join(DATA, "hdb_property.csv")))
            if r["residential"] == "Y"]
    done = load_done()
    todo = [r for r in rows if f'{r["blk_no"]}|{r["street"]}' not in done]
    print(f"total={len(rows)} cached={len(done)} todo={len(todo)}", flush=True)

    q = queue.Queue()
    for r in todo:
        q.put(r)
    out_lock = threading.Lock()
    fh = open(CACHE, "a")
    counter = [0]
    t0 = time.time()

    def worker():
        while True:
            try:
                r = q.get_nowait()
            except queue.Empty:
                return
            blk, street = r["blk_no"], r["street"]
            term = f"{blk} {street}"
            rec = {"key": f"{blk}|{street}", "blk_no": blk, "street": street}
            for attempt in range(MAX_TRIES):
                try:
                    throttle()
                    d = onemap(term)
                    hit, how = pick(d.get("results", []), blk, street)
                    if hit is None and attempt == 0:
                        # retry once with expanded street name
                        throttle()
                        d = onemap(f"{blk} {expand(street)}")
                        hit, how = pick(d.get("results", []), blk, street)
                    if hit:
                        rec.update(lat=float(hit["LATITUDE"]), lon=float(hit["LONGITUDE"]),
                                   postal=hit.get("POSTAL", ""), address=hit.get("ADDRESS", ""),
                                   match=how)
                    else:
                        rec.update(match="none")
                    reward()
                    break
                except RateLimited:
                    penalise()
                    if attempt == MAX_TRIES - 1:
                        rec.update(match="error", error="HTTP 429")
                    else:
                        time.sleep(min(2 ** attempt * 1.0, 30))
                except Exception as e:
                    if attempt == MAX_TRIES - 1:
                        rec.update(match="error", error=str(e)[:120])
                    else:
                        time.sleep(min(2 ** attempt * 0.8, 20))
            with out_lock:
                fh.write(json.dumps(rec) + "\n")
                counter[0] += 1
                if counter[0] % 250 == 0:
                    el = time.time() - t0
                    rem = (len(todo) - counter[0]) / max(counter[0] / el, 0.01)
                    print(f"{counter[0]}/{len(todo)}  {el/60:.1f}m elapsed  ~{rem/60:.1f}m left  interval={_interval[0]:.2f}s", flush=True)
                    fh.flush()

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(THREADS)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    fh.close()
    print(f"DONE in {(time.time()-t0)/60:.1f}m", flush=True)

if __name__ == "__main__":
    main()
