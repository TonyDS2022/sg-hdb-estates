"""Subset Noto Sans SC to exactly the characters the site renders.

A full Simplified Chinese face is ~15 MB; Google Fonts' hosted version is split into
202 unicode-range chunks, and 391 scattered glyphs would pull down a large share of
them. The Chinese text here is a fixed set of dictionary strings, so the exact glyph
set is knowable at build time — which turns the problem into one small file.
"""
import os, re, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "data", "NotoSansSC-VF.otf")
OUT_DIR = os.path.join(HERE, "site", "vendor")
URL = ("https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/"
       "Sans/Variable/OTF/Subset/NotoSansSC-VF.otf")
# Weights the page uses: body text and the semibold used by headings and figures.
WEIGHTS = [("400", "NotoSansSC-400"), ("600", "NotoSansSC-600")]


def glyphs():
    """Every CJK / fullwidth character that appears in the built page."""
    s = open(os.path.join(HERE, "site", "index.html"), encoding="utf-8").read()
    # CJK and fullwidth punctuation only. Latin and digits are deliberately excluded:
    # the @font-face restricts this face to CJK via unicode-range, so Latin keeps using
    # the system stack and any ASCII glyphs here would be downloaded but never drawn.
    return "".join(sorted(set(re.findall(r"[　-〿一-鿿＀-￯]", s))))


def verify(path, text):
    """Every character the page renders must be in the subset, or it silently falls
    back to a system font mid-sentence. Adding a translation invalidates the subset,
    so this is checked rather than remembered."""
    from fontTools.ttLib import TTFont
    cmap = set()
    for t in TTFont(path)["cmap"].tables:
        cmap |= set(t.cmap.keys())
    missing = [c for c in text if ord(c) not in cmap]
    if missing:
        raise SystemExit(f"FONT SUBSET INCOMPLETE: {len(missing)} characters missing "
                         f"from {os.path.basename(path)}: {''.join(missing[:20])}")


def main():
    if not os.path.exists(SRC):
        os.makedirs(os.path.dirname(SRC), exist_ok=True)
        print("downloading Noto Sans SC (~15 MB, cached)…")
        urllib.request.urlretrieve(URL, SRC)
    os.makedirs(OUT_DIR, exist_ok=True)
    text = glyphs()
    print(f"subsetting to {len(text)} characters")
    for wght, name in WEIGHTS:
        out = os.path.join(OUT_DIR, name + ".woff2")
        # A variable font must be pinned to a static weight first; pyftsubset has no
        # instancing flag of its own.
        static = os.path.join(OUT_DIR, f".{name}.tmp.otf")
        subprocess.run([sys.executable, "-m", "fontTools.varLib.instancer",
                        SRC, f"wght={wght}", "-o", static], check=True,
                       capture_output=True)
        subprocess.run([sys.executable, "-m", "fontTools.subset", static,
                        f"--text={text}",
                        "--flavor=woff2", "--layout-features=*",
                        "--desubroutinize", "--no-hinting",
                        f"--output-file={out}"], check=True)
        os.remove(static)
        verify(out, text)
        print(f"  {name}.woff2  {os.path.getsize(out)/1024:.0f} KB "
              f"({os.path.getsize(SRC)/os.path.getsize(out):.0f}x smaller than the source)")


if __name__ == "__main__":
    main()
