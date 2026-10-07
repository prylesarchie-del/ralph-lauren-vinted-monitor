import asyncio
import json
import os
import re
from pathlib import Path

import resend
from playwright.async_api import async_playwright


# ============================================================
# SETTINGS
# ============================================================

SEARCH_URL = (
    "https://www.vinted.com.au/catalog"
    "?search_text=Ralph+Lauren"
    "&order=newest_first"
)

MAX_PRICE = 15.00

# Resend test email
EMAIL_TO = "prylesarchie@gmail.com"
EMAIL_FROM = "onboarding@resend.dev"

SEEN_FILE = Path("seen_listings.json")


# ============================================================
# RESEND
# ============================================================

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

if not RESEND_API_KEY:
    print("ERROR: RESEND_API_KEY is missing.")
    raise SystemExit(1)

resend.api_key = RESEND_API_KEY


# ============================================================
# FILTERS
# ============================================================

EXCLUDED_WORDS = [
    "women",
    "womens",
    "women's",
    "woman",
    "ladies",
    "lady",

    "girl",
    "girls",

    "baby",
    "babies",
    "toddler",
    "infant",

    "kids",
    "kid",
    "child",
    "children",

    "boy",
    "boys",

    "maternity",

    "dress",
    "dresses",
    "skirt",
    "skirts",
    "heels",
    "handbag",
    "purse",
]

EXCLUDED_BRANDS = [
    "u.s. polo assn",
    "us polo assn",
    "u.s polo assn",
    "chaps",
    "polo sport",
    "polo club",
]

MENS_WORDS = [
    "men",
    "mens",
    "men's",
    "male",
    "man",
]

ADULT_CLOTHING_WORDS = [
    "polo",
    "shirt",
    "button up",
    "button-up",
    "jumper",
    "sweater",
    "hoodie",
    "jacket",
    "coat",
    "quarter zip",
    "quarter-zip",
    "tracksuit",
    "shorts",
    "trousers",
    "pants",
    "jeans",
    "gilet",
    "bodywarmer",
    "vest",
    "blazer",
    "cardigan",
    "rugby",
    "oxford",
    "crewneck",
    "crew neck",
]

KIDS_PATTERNS = [
    r"\bage\s*\d+\b",
    r"\bage\s*\d+\s*[-–]\s*\d+\b",
    r"\b\d+\s*[-–]\s*\d+\s*years?\b",
    r"\b\d+\s*years?\s*old\b",
    r"\by\/?o\b",
]


# ============================================================
# SEEN LISTINGS
# ============================================================

def load_seen():
    if not SEEN_FILE.exists():
        return set()

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as file:
            return set(json.load(file))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(seen), file, indent=2)


# ============================================================
# LISTING INFORMATION
# ============================================================

def extract_listing_id(url):
    match = re.search(r"/items/(\d+)", url)

    if match:
        return match.group(1)

    return None


def extract_price(title):
    match = re.search(
        r"([0-9]+(?:[.,][0-9]{1,2})?)\s*A\$",
        title,
        re.IGNORECASE,
    )

    if not match:
        return None

    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


# ============================================================
# MEN'S FILTER
# ============================================================

def is_mens_listing(title, url):

    text = f"{title} {url}".lower()

    # Must contain Ralph Lauren.
    if "ralph lauren" not in text:
        return False

    # Remove other brands.
    for brand in EXCLUDED_BRANDS:
        if brand in text:
            return False

    # Remove obvious women's / children's listings.
    for word in EXCLUDED_WORDS:
        if word in text:
            return False

    # Remove children's age descriptions.
    for pattern in KIDS_PATTERNS:
        if re.search(pattern, text):
            return False

    # Explicit men's wording.
    for word in MENS_WORDS:
        if word in text:
            return True

    # Otherwise allow likely adult clothing.
    for word in ADULT_CLOTHING_WORDS:
        if word in text:
            return True

    return False


# ============================================================
# EMAIL
# ============================================================

def send_email(listings):

    if not listings:
        return

    html_parts = [
        "<h2>🔥 New Ralph Lauren Find</h2>",
        (
            f"<p>Found {len(listings)} new men's Ralph Lauren "
            f"listing(s) under A${MAX_PRICE:.2f}.</p>"
        ),
    ]

    text_parts = [
        "🔥 NEW RALPH LAUREN FIND",
        "",
    ]

    for listing in listings:

        title = listing["title"]

        # Remove Vinted's extra information.
        if ", Brand:" in title:
            title = title.split(", Brand:")[0]

        price = f"A${listing['price']:.2f}"
        url = listing["url"]

        # HTML email.
        html_parts.append(
            f"""
            <div style="margin-bottom: 30px;">
                <h3>{title}</h3>
                <p>
                    <strong>💰 {price}</strong>
                </p>
                <p>
                    <a href="{url}">
                        🔗 View listing
                    </a>
                </p>
            </div>
            """
        )

        # Plain-text fallback.
        text_parts.append(f"Title: {title}")
        text_parts.append(f"Price: {price}")
        text_parts.append(f"Link: {url}")
        text_parts.append("")
        text_parts.append("-" * 50)
        text_parts.append("")

    html_body = "\n".join(html_parts)
    text_body = "\n".join(text_parts)

    try:

        response = resend.Emails.send(
            {
                "from": EMAIL_FROM,
                "to": [EMAIL_TO],
                "subject": (
                    f"🔥 New Ralph Lauren find "
                    f"under A${MAX_PRICE:.0f}"
                ),
                "html": html_body,
                "text": text_body,
            }
        )

        print("EMAIL SENT")
        print(response)

    except Exception as error:
        print("EMAIL ERROR:")
        print(error)


# ============================================================
# VINTED SCANNER
# ============================================================

async def scan_vinted():

    print("=" * 60)
    print("RALPH LAUREN VINTED MONITOR")
    print("=" * 60)
    print()
    print(f"Maximum price: A${MAX_PRICE:.2f}")
    print("Search: Ralph Lauren")
    print("Country: Australia")
    print("Sort: Newest first")
    print()

    seen = load_seen()

    listings = []

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True
        )

        page = await browser.new_page(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36"
            ),
        )

        print("Opening Vinted...")

        try:

            await page.goto(
                SEARCH_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(5000)

        except Exception as error:

            print("Could not open Vinted:")
            print(error)

            await browser.close()
            return

        links = await page.locator(
            "a[href*='/items/']"
        ).all()

        print(
            f"Found {len(links)} possible listings."
        )

        checked_ids = set()

        for link in links:

            try:

                url = await link.get_attribute("href")
                title = await link.get_attribute("title")

                if not url or not title:
                    continue

                listing_id = extract_listing_id(url)

                if not listing_id:
                    continue

                if listing_id in checked_ids:
                    continue

                checked_ids.add(listing_id)

                price = extract_price(title)

                if price is None:
                    continue

                if price > MAX_PRICE:
                    continue

                if not is_mens_listing(title, url):
                    continue

                if url.startswith("/"):
                    url = (
                        "https://www.vinted.com.au"
                        + url
                    )

                listings.append(
                    {
                        "id": listing_id,
                        "title": title,
                        "price": price,
                        "url": url,
                    }
                )

            except Exception:
                continue

        await browser.close()

    print()
    print(
        f"Matching men's listings under "
        f"A${MAX_PRICE:.2f}: {len(listings)}"
    )

    new_listings = []

    for listing in listings:

        if listing["id"] not in seen:
            new_listings.append(listing)

        seen.add(listing["id"])

    save_seen(seen)

    print(
        f"New listings: {len(new_listings)}"
    )

    print()

    if new_listings:

        print("NEW LISTINGS:")

        for listing in new_listings:

            title = listing["title"]

            if ", Brand:" in title:
                title = title.split(", Brand:")[0]

            print()
            print(f"Title: {title}")
            print(
                f"Price: A${listing['price']:.2f}"
            )
            print(
                f"Link: {listing['url']}"
            )

        send_email(new_listings)

    else:

        print(
            "No new listings since the previous check."
        )

    print()
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    asyncio.run(scan_vinted())