"""Smoke test: the MAIN page must render. Asserting only on the panel missed a
crash in boot() because the panel is a sibling of #app and survived it."""
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8642/'
async def m():
    ok = True
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=['--use-gl=swiftshader','--enable-unsafe-swiftshader'])
        for label, u in [('plain', URL), ('deep link', URL + '#b=18%7CCANTONMENT%20CL')]:
            pg = await b.new_page(viewport={'width':1380,'height':1000})
            errs = []
            pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
            pg.on('console', lambda m2: errs.append('console.error: ' + m2.text[:120]) if m2.type == 'error' else None)
            await pg.goto(u, wait_until='networkidle', timeout=90000)
            await pg.wait_for_timeout(12000)
            checks = await pg.evaluate("""(()=>({
              errorCard: !!document.querySelector('#app .card h2') &&
                         /went wrong|Could not load/.test(document.querySelector('#app .card h2').textContent),
              tiles:  document.querySelectorAll('#tiles .tile').length,
              charts: document.querySelectorAll('#cYear path').length,
              srcRows:document.querySelectorAll('#src tr').length,
              tblRows:document.querySelectorAll('#tbody tr').length,
              mapDots:document.querySelectorAll('#map canvas').length,
            }))()""")
            bad = (checks['errorCard'] or checks['tiles'] < 5 or checks['charts'] < 10
                   or checks['srcRows'] < 3 or checks['tblRows'] < 10 or errs)
            ok = ok and not bad
            print(f"  [{'FAIL' if bad else 'PASS'}] {label:<10} {checks}")
            if errs: print('          errors:', errs[:3])
            await pg.close()
        await b.close()
    print('  SMOKE:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1
sys.exit(asyncio.run(m()))
