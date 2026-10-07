import os
import json
import re
from playwright.sync_api import sync_playwright
import resend


# ============================================================
# RALPH LAUREN VINTED MONITOR
# ============================================================

SEARCH_URL = (
    "https://www.vinted.com.au/catalog"
    "?search_text=Ralph+Lauren"
    "&order=newest_first"
)

# Maximum LISTING price
MAX_PRICE = 15.00

# Temporary email destination for Resend testing
# Once everything works, we can change this to your
# Carey email after verifying a sending domain.
EMAIL_TO = "prylesarchie@gmail.com"

# Resend's test sender
EMAIL_FROM = "onboarding@resend.dev"

# File used to remember listings already seen
SEEN_FILE = "seen_listings.json"


# ============================================================
# LOAD SEEN LISTINGS
# ============================================================

def load_seen():

    if not os.path.exists(SEEN_FILE):
        return set()

    try:

        with open(SEEN_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return set(data)

    except Exception:

        return set()


# ============================================================
# SAVE SEEN LISTINGS
# ============================================================

def save_seen(seen):

    with open(SEEN_FILE, "w", encoding="utf-8") as file:
        json.dump(
            list(seen),
            file,
            indent=2
        )


# ============================================================
# CHECK IF LISTING IS MEN'S ADULT CLOTHING
# ============================================================

def is_mens_listing(title, url):

    text = (title + " " + url).lower()

    # --------------------------------------------------------
    # EXCLUDE DEFINITELY WRONG CATEGORIES
    # --------------------------------------------------------

    excluded_words = [
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
        "maternity",
        "dress",
        "skirt",
        "heels",
        "handbag",
        "purse"
    ]

    for word in excluded_words:

        if word in text:
            return False

    # --------------------------------------------------------
    # EXCLUDE OTHER BRANDS THAT CONTAIN "RALPH"
    # --------------------------------------------------------

    excluded_brands = [
        "u.s. polo assn",
        "us polo assn",
        "u.s polo assn",
        "chaps",
        "polo sport",
        "polo club"
    ]

    for brand in excluded_brands:

        if brand in text:
            return False

    # --------------------------------------------------------
    # REQUIRE ACTUAL RALPH LAUREN BRAND
    # --------------------------------------------------------

    ralph_lauren_present = (
        "ralph lauren" in text
        or "polo ralph lauren" in text
    )

    if not ralph_lauren_present:
        return False

    # --------------------------------------------------------
    # STRONG MEN'S INDICATORS
    # --------------------------------------------------------

    mens_words = [
        "men",
        "mens",
        "men's",
        "male",
        "man",
        "boys",
        "boy"
    ]

    for word in mens_words:

        if word in text:
            return True

    # --------------------------------------------------------
    # COMMON ADULT MEN'S CLOTHING
    #
    # If the listing doesn't explicitly say men's,
    # allow common Ralph Lauren adult clothing.
    # --------------------------------------------------------

    clothing_words = [
        "polo",
        "shirt",
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
        "cardigan"
    ]

    for word in clothing_words:

        if word in text:
            return True

    return False


# ============================================================
# GET VINTED LISTINGS
# ============================================================

def get_listings():

    listings = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1000
            }
        )

        print("Opening Vinted...")

        page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        # Give Vinted time to load
        page.wait_for_timeout(5000)

        # Scroll to load additional listings
        for _ in range(4):

            page.mouse.wheel(
                0,
                1500
            )

            page.wait_for_timeout(1000)

        # Find product links
        links = page.locator(
            'a[data-testid*="product-item"][href*="/items/"]'
        ).all()

        print(
            f"Found {len(links)} possible listings."
        )

        used_ids = set()

        for link in links:

            try:

                # ------------------------------------------------
                # GET URL
                # ------------------------------------------------

                url = link.get_attribute(
                    "href"
                )

                if not url:
                    continue

                # ------------------------------------------------
                # GET VINTED TITLE ATTRIBUTE
                # ------------------------------------------------

                title = link.get_attribute(
                    "title"
                )

                if not title:
                    continue

                # ------------------------------------------------
                # GET UNIQUE LISTING ID
                # ------------------------------------------------

                id_match = re.search(
                    r"/items/(\d+)",
                    url
                )

                if not id_match:
                    continue

                listing_id = id_match.group(1)

                if listing_id in used_ids:
                    continue

                used_ids.add(
                    listing_id
                )

                # ------------------------------------------------
                # EXTRACT PRICE
                #
                # Example:
                # "29.00 A$, 31.45 A$"
                #
                # The first price is the listing price.
                # ------------------------------------------------

                price_match = re.search(
                    r"([0-9]+(?:[.,][0-9]{1,2})?)\s*A\$",
                    title
                )

                if not price_match:
                    continue

                price = float(
                    price_match.group(1).replace(
                        ",",
                        "."
                    )
                )

                # ------------------------------------------------
                # PRICE FILTER
                # ------------------------------------------------

                if price > MAX_PRICE:
                    continue

                # ------------------------------------------------
                # MEN'S FILTER
                # ------------------------------------------------

                if not is_mens_listing(
                    title,
                    url
                ):
                    continue

                # ------------------------------------------------
                # CREATE FULL URL
                # ------------------------------------------------

                if url.startswith("/"):

                    full_url = (
                        "https://www.vinted.com.au"
                        + url
                    )

                else:

                    full_url = url

                # ------------------------------------------------
                # SAVE LISTING
                # ------------------------------------------------

                listings.append(
                    {
                        "id": listing_id,
                        "title": title,
                        "price": price,
                        "url": full_url
                    }
                )

            except Exception as error:

                print(
                    "Listing error:",
                    error
                )

        browser.close()

    return listings


# ============================================================
# SEND EMAIL WITH RESEND
# ============================================================

def send_email(listings):

    api_key = os.environ.get(
        "RESEND_API_KEY"
    )

    if not api_key:

        print(
            "ERROR: RESEND_API_KEY is not set."
        )

        return

    resend.api_key = api_key

    # --------------------------------------------------------
    # CREATE EMAIL HTML
    # --------------------------------------------------------

    html = """
    <html>

    <body>

    <h2>🔥 Ralph Lauren Vinted Bargain</h2>

    <p>
    A new men's Ralph Lauren listing
    under A$15 was found on Vinted Australia.
    </p>
    """

    for listing in listings:

        html += f"""

        <hr>

        <h3>
        {listing["title"]}
        </h3>

        <p>
        <strong>
        A${listing["price"]:.2f}
        </strong>
        </p>

        <p>
        <a href="{listing["url"]}">
        🛒 View listing on Vinted
        </a>
        </p>

        """

    html += """

    </body>

    </html>
    """

    # --------------------------------------------------------
    # SEND
    # --------------------------------------------------------

    try:

        result = resend.Emails.send(
            {
                "from": EMAIL_FROM,
                "to": [EMAIL_TO],
                "subject": (
                    "🔥 Ralph Lauren bargain "
                    "found on Vinted"
                ),
                "html": html
            }
        )

        print(
            "Email sent successfully!"
        )

        print(
            result
        )

    except Exception as error:

        print(
            "EMAIL ERROR:"
        )

        print(
            error
        )


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    print("=" * 60)

    print(
        "RALPH LAUREN VINTED MONITOR"
    )

    print("=" * 60)

    print()

    print(
        f"Maximum price: "
        f"A${MAX_PRICE:.2f}"
    )

    print()

    # --------------------------------------------------------
    # LOAD PREVIOUSLY SEEN LISTINGS
    # --------------------------------------------------------

    old_seen = load_seen()

    # --------------------------------------------------------
    # SEARCH VINTED
    # --------------------------------------------------------

    listings = get_listings()

    print()

    print(
        f"Matching men's listings "
        f"under A${MAX_PRICE:.2f}: "
        f"{len(listings)}"
    )

    print()

    if not listings:

        print(
            "No matching listings found."
        )

        return

    # --------------------------------------------------------
    # FIND NEW LISTINGS
    # --------------------------------------------------------

    new_listings = []

    current_seen = set(
        old_seen
    )

    for listing in listings:

        listing_id = listing["id"]

        if listing_id not in old_seen:

            new_listings.append(
                listing
            )

        current_seen.add(
            listing_id
        )

    # --------------------------------------------------------
    # SAVE SEEN LISTINGS
    # --------------------------------------------------------

    save_seen(
        current_seen
    )

    print(
        f"New listings: "
        f"{len(new_listings)}"
    )

    print()

    # --------------------------------------------------------
    # DISPLAY MATCHES
    # --------------------------------------------------------

    for listing in listings:

        print(
            f'A${listing["price"]:.2f} | '
            f'{listing["title"]}'
        )

        print(
            listing["url"]
        )

        print()

    # --------------------------------------------------------
    # SEND EMAIL ONLY FOR NEW LISTINGS
    # --------------------------------------------------------

    if new_listings:

        print(
            "Sending email for "
            "new listings..."
        )

        send_email(
            new_listings
        )

    else:

        print(
            "No new listings since "
            "the previous check."
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()