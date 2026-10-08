from playwright.sync_api import sync_playwright

URL = "https://www.vinted.com.au/catalog?search_text=Ralph+Lauren&order=newest_first"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    page = browser.new_page(
        viewport={
            "width": 1440,
            "height": 1000
        }
    )

    print("Opening Vinted...")
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    page.wait_for_timeout(5000)

    links = page.locator('a[href*="/items/"]').all()

    print(f"Found {len(links)} listings")

    for i, link in enumerate(links[:20], 1):
        try:
            print("\n" + "=" * 50)
            print(f"LISTING {i}")
            print("=" * 50)
            print("URL:", link.get_attribute("href"))
            print("TEXT:")
            print(link.inner_text())
        except:
            pass

    input("\nPress ENTER to close...")

    browser.close()