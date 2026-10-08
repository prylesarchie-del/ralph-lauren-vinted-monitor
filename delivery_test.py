from playwright.sync_api import sync_playwright

URL = "https://www.vinted.com.au/items/10286721040-ralph-lauren-v-neck-brown-jumper"

with sync_playwright() as p:

    browser = p.chromium.launch(headless=True)

    page = browser.new_page()

    print("Opening listing...")

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=30000
    )

    page.wait_for_timeout(3000)

    print()
    print("=" * 60)
    print("PAGE TEXT")
    print("=" * 60)

    text = page.locator("body").inner_text()

    print(text[:15000])

    print()
    print("=" * 60)
    print("LINKS CONTAINING DELIVERY/SHIPPING/POSTAGE")
    print("=" * 60)

    links = page.locator("a")

    for i in range(min(links.count(), 500)):

        try:

            link = links.nth(i)

            link_text = link.inner_text().strip()

            if any(
                word in link_text.lower()
                for word in [
                    "delivery",
                    "shipping",
                    "postage",
                    "send",
                    "buyer",
                    "protection"
                ]
            ):

                print(
                    repr(link_text)
                )

        except Exception:
            pass

    browser.close()