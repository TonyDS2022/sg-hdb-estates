import sys, asyncio
from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8756/"
OUT = sys.argv[2] if len(sys.argv) > 2 else "shots"

async def main():
    import os
    os.makedirs(OUT, exist_ok=True)
    errs = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1380, "height": 1000}, device_scale_factor=2)
        pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        await pg.goto(URL, wait_until="networkidle")
        await pg.wait_for_selector("#tiles .tile", timeout=20000)
        await pg.wait_for_timeout(700)
        for theme in ("light", "dark"):
            await pg.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
            await pg.wait_for_timeout(400)
            await pg.screenshot(path=f"{OUT}/full-{theme}.png", full_page=True)
            await pg.locator("#map").screenshot(path=f"{OUT}/map-{theme}.png")
        # sanity probes
        n = await pg.evaluate("document.querySelectorAll('#map circle').length")
        tiles = await pg.evaluate("[...document.querySelectorAll('.tile .v')].map(e=>e.textContent)")
        rows = await pg.evaluate("document.querySelectorAll('#tbody tr').length")
        bars = await pg.evaluate("document.querySelectorAll('#cYear path').length")
        mix = await pg.evaluate("document.querySelectorAll('#cMix rect').length")
        print("map circles:", n, "| table rows:", rows, "| year bars:", bars, "| mix segs:", mix)
        print("tiles:", tiles)
        await b.close()
    print("errors:", errs if errs else "none")

asyncio.run(main())
