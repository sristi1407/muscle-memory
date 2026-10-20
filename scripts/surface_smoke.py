"""Drive MockCore with the Surface driver so you can watch it work.

Start MockCore first in another terminal:
    python targets/mockcore/app.py

Then:
    python scripts/surface_smoke.py          # headful — you SEE the browser
    HEADLESS=1 python scripts/surface_smoke.py   # headless (CI/quick check)
"""
import os
import time

from cua.surface import PlaywrightWebSurface

URL = "http://127.0.0.1:5001/members"
HEADLESS = os.environ.get("HEADLESS", "0") == "1"


def main() -> None:
    with PlaywrightWebSurface(headless=HEADLESS) as s:
        s.navigate(URL)
        print("=== OBSERVE (member lookup) ===")
        print(s.observe().render())

        print("\n=== TYPE '12345' into Member ID ===")
        r = s.do_type("Member ID", "12345")
        print("strategies:", [st.model_dump() for st in r.strategies])

        print("\n=== CLICK Search ===")
        r = s.do_click("Search")
        print("strategies:", [st.model_dump() for st in r.strategies])
        s.page.wait_for_load_state("domcontentloaded")

        print("\n=== OBSERVE (member detail) ===")
        print(s.observe().render())

        print("\n=== READ Savings ===")
        r = s.do_read("Savings")
        print("savings_balance =", repr(r.value))
        print("strategies:", [st.model_dump() for st in r.strategies])

        if not HEADLESS:
            print("\n(keeping the window open for 3s...)")
            time.sleep(3)


if __name__ == "__main__":
    main()
