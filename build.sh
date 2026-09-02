#!/usr/bin/env bash
# Cloudflare Pages build step.
#
# Everything under site/ is committed except config.js, which carries the Mapbox
# token and is deliberately kept out of git. Set MAPBOX_TOKEN as an environment
# variable in the Pages project settings and this regenerates it at deploy time,
# so the token lives in Cloudflare's secret store rather than in the repo.
set -euo pipefail

TOKEN="${MAPBOX_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  echo "WARNING: MAPBOX_TOKEN is not set — the map will fall back to the plain SVG scatter." >&2
fi

# config.js is served to every visitor, so only a PUBLIC (pk.) token may go in it.
# A secret (sk.*) token carries account privileges and cannot be URL-restricted;
# publishing one would expose the Mapbox account. Fail the build rather than leak it.
case "$TOKEN" in
  sk.*)
    echo "ERROR: MAPBOX_TOKEN is a secret token (sk.*)." >&2
    echo "       config.js is public — a secret token must never be deployed." >&2
    echo "       Use a public token (pk.*) from Mapbox > Account > Tokens." >&2
    exit 1
    ;;
esac

python3 - <<'PY'
import json, os
cfg = {
    "token": os.environ.get("MAPBOX_TOKEN", ""),
    "styles": {"light": "mapbox://styles/mapbox/light-v11",
               "dark": "mapbox://styles/mapbox/dark-v11"},
}
with open("site/config.js", "w") as f:
    f.write("window.MAP_CONFIG = " + json.dumps(cfg) + ";\n")
print("wrote site/config.js  token=" + ("present" if cfg["token"] else "MISSING"))
PY
