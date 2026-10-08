from playwright.sync_api import sync_playwright
import time

URL = "https://www.vinted.com.au/catalog?search_text=ralph%20lauren&order=newest_first"

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False
    )

    page = browser.new_page(
        viewport={"width": 1440, "height": 1000},
        locale="en-AU",
        timezone_id="Australia/Melbourne",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/154.0.0.0 Safari/537.36"
        )
    )

    print("Opening Vinted...")
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    print("URL:", page.url)
    print("Title:", page.title())

    time.sleep(8)

    print("\n--- PAGE TEXT ---")
    print(page.locator("body").inner_text()[:10000])

    print("\n--- LINKS ---")

    links = page.locator("a")
    count = links.count()

    print("Total <a> elements:", count)

    for i in range(min(count, 200)):
        href = links.nth(i).get_attribute("href")
        text = links.nth(i).inner_text().strip()

        if href:
            print(i, repr(text[:100]), "=>", href)

    print("\n--- ITEM URL SEARCH ---")

    html = page.content()

    for keyword in [
        "/items/",
        "vinted.com.au/items/",
        "catalog",
        "Ralph Lauren",
        "Cloudflare",
        "captcha",
        "verify",
        "robot",
    ]:
        print(keyword, "=>", html.lower().count(keyword.lower()))

    page.screenshot(path="vinted_debug.png", full_page=True)

    print("\nScreenshot saved as:")
    print("vinted_debug.png")

    print("\nBrowser will stay open for 30 seconds.")
    time.sleep(30)

    browser.close()