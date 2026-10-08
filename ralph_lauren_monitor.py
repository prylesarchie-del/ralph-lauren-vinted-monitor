import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

from playwright.sync_api import sync_playwright
import resend


# ============================================================
# SETTINGS
# ============================================================

SEARCH_URL = (
    "https://www.vinted.com.au/catalog"
    "?search_text=ralph%20lauren"
    "&order=newest_first"
)

MAX_ITEM_PRICE = 15.00
MAX_DELIVERY_PRICE = 6.00

ACCEPTED_CONDITIONS = {
    "good",
    "very good",
    "new with tags",
    "new without tags",
}

EMAIL_INTERVAL_HOURS = 2

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

EMAIL_TO = "prylesarchie@gmail.com"
EMAIL_FROM = "onboarding@resend.dev"

SEEN_FILE = "seen_listings.json"
QUEUE_FILE = "email_queue.json"
LAST_EMAIL_FILE = "last_email.txt"


# ============================================================
# FILTERS
# ============================================================

EXCLUDED_WORDS = {
    "women",
    "woman",
    "womens",
    "women's",
    "girl",
    "girls",
    "kids",
    "kid",
    "child",
    "children",
    "boys",
    "boy",
    "baby",
    "babies",
    "toddler",
    "toddlers",
    "infant",
    "infants",
}

EXCLUDED_BRANDS = {
    "u.s. polo assn",
    "us polo assn",
    "u.s polo assn",
    "chaps",
    "polo sport",
    "polo club",
}

CLOTHING_WORDS = {
    "shirt",
    "shirts",
    "polo",
    "tshirt",
    "t-shirt",
    "tee",
    "jumper",
    "sweater",
    "hoodie",
    "sweatshirt",
    "jacket",
    "coat",
    "vest",
    "gilet",
    "cardigan",
    "knit",
    "knitted",
    "top",
    "tops",
    "trousers",
    "pants",
    "jeans",
    "shorts",
    "chinos",
    "chino",
    "tracksuit",
    "trackpants",
    "suit",
    "blazer",
    "windbreaker",
    "fleece",
    "pullover",
    "dress",
    "skirt",
    "leggings",
    "clothing",
    "clothes",
    "joggers",
    "rugby",
    "quarterzip",
    "quarter-zip",
    "quarter zip",
    "cami",
}


# ============================================================
# JSON
# ============================================================

def load_json(filename, default):

    try:

        if not os.path.exists(filename):
            return default

        with open(
            filename,
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(f)

    except Exception:

        return default


def save_json(filename, data):

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# TEXT
# ============================================================

def normalise(text):

    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip().lower()


def money(value):

    try:
        return float(value)

    except Exception:
        return None


# ============================================================
# URL TITLE
# ============================================================

def slug_to_title(url):

    try:

        path = url.split("?")[0].rstrip("/")
        slug = path.split("/")[-1]

        slug = re.sub(
            r"^\d+-",
            "",
            slug,
        )

        slug = unquote(slug)
        slug = slug.replace("-", " ")

        slug = re.sub(
            r"\s+",
            " ",
            slug,
        ).strip()

        if not slug:
            return ""

        return slug.title()

    except Exception:

        return ""


# ============================================================
# EXCLUSIONS
# ============================================================

def contains_excluded_word(text):

    text = normalise(text)

    for word in EXCLUDED_WORDS:

        pattern = (
            r"(?<![a-z])"
            + re.escape(word)
            + r"(?![a-z])"
        )

        if re.search(
            pattern,
            text,
        ):

            return word

    return None


def excluded_by_url(url):

    return contains_excluded_word(
        unquote(url)
    )


def excluded_brand(text):

    text = normalise(text)

    for brand in EXCLUDED_BRANDS:

        if brand in text:
            return brand

    return None


# ============================================================
# PRICE
# ============================================================

def extract_price(text):

    if not text:
        return None

    matches = re.findall(
        r"\$(\d+(?:\.\d{1,2})?)",
        text.replace(",", ""),
    )

    if not matches:
        return None

    values = []

    for value in matches:

        number = money(value)

        if number is not None:
            values.append(number)

    if not values:
        return None

    return values[0]


# ============================================================
# CONDITION
# ============================================================

def extract_condition(text):

    text = normalise(text)

    for condition in [
        "new without tags",
        "new with tags",
        "very good",
        "good",
    ]:

        if condition in text:
            return condition

    return None


# ============================================================
# CLOTHING
# ============================================================

def is_clothing(text):

    text = normalise(text)

    for word in CLOTHING_WORDS:

        if word in text:
            return True

    return False


# ============================================================
# DELIVERY
# ============================================================

def extract_delivery(page):

    patterns = [
        r"Shipping\s+from\s+\$(\d+(?:\.\d{1,2})?)",
        r"Shipping\s*:\s*from\s*\$(\d+(?:\.\d{1,2})?)",
        r"Shipping\s+from\s*\$(\d+(?:\.\d{1,2})?)",
    ]

    try:

        body = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        for pattern in patterns:

            match = re.search(
                pattern,
                body,
                flags=re.IGNORECASE,
            )

            if match:

                value = money(
                    match.group(1)
                )

                if value is not None:
                    return value

    except Exception:

        pass

    return None


# ============================================================
# TITLE
# ============================================================

def extract_title(page, url, card_text):

    # URL slug is the most reliable fallback
    slug_title = slug_to_title(url)

    if slug_title:
        return slug_title

    try:

        h1s = page.locator(
            "h1"
        ).all_inner_texts()

        for h1 in h1s:

            h1 = re.sub(
                r"\s+",
                " ",
                h1,
            ).strip()

            if len(h1) >= 5:
                return h1

    except Exception:

        pass

    return card_text or "Ralph Lauren listing"


# ============================================================
# CATALOGUE EXTRACTION
# ============================================================

def extract_listing_cards(page):

    results = []
    seen_urls = set()

    # --------------------------------------------------------
    # METHOD 1
    # --------------------------------------------------------

    selectors = [
        'a[href*="/items/"]',
        'a[href^="/items/"]',
        'a[href*="vinted.com.au/items/"]',
    ]

    for selector in selectors:

        try:

            links = page.locator(
                selector
            ).all()

            print(
                f"Selector {selector}: "
                f"{len(links)} links"
            )

            for link in links:

                try:

                    href = link.get_attribute(
                        "href"
                    )

                    if not href:
                        continue

                    if "/items/" not in href:
                        continue

                    if href.startswith("/"):
                        href = (
                            "https://www.vinted.com.au"
                            + href
                        )

                    href = href.split("?")[0]

                    if href in seen_urls:
                        continue

                    seen_urls.add(href)

                    card_text = ""

                    current = link

                    for _ in range(8):

                        try:

                            parent = current.locator(
                                ".."
                            )

                            text_value = parent.inner_text(
                                timeout=1000
                            )

                            if text_value:

                                cleaned = re.sub(
                                    r"\s+",
                                    " ",
                                    text_value,
                                ).strip()

                                if len(cleaned) >= 15:

                                    card_text = cleaned

                                    if "$" in cleaned:
                                        break

                            current = parent

                        except Exception:

                            break

                    results.append(
                        {
                            "url": href,
                            "card_text": card_text,
                        }
                    )

                except Exception:

                    continue

            if results:
                break

        except Exception:

            continue

    return results


# ============================================================
# DETAIL INSPECTION
# ============================================================

def inspect_listing(page, listing):

    url = listing["url"]
    card_text = listing.get(
        "card_text",
        "",
    )

    title = extract_title(
        page,
        url,
        card_text,
    )

    combined = normalise(
        title
        + " "
        + card_text
        + " "
        + url
    )

    # --------------------------------------------------------
    # URL EXCLUSION
    # --------------------------------------------------------

    excluded = excluded_by_url(url)

    if excluded:

        return {
            "qualifies": False,
            "reason": (
                f"excluded word in URL: {excluded}"
            ),
        }

    # --------------------------------------------------------
    # TEXT EXCLUSION
    # --------------------------------------------------------

    excluded = contains_excluded_word(
        title + " " + card_text
    )

    if excluded:

        return {
            "qualifies": False,
            "reason": (
                f"excluded word: {excluded}"
            ),
        }

    # --------------------------------------------------------
    # BRAND EXCLUSION
    # --------------------------------------------------------

    excluded = excluded_brand(combined)

    if excluded:

        return {
            "qualifies": False,
            "reason": (
                f"excluded brand: {excluded}"
            ),
        }

    # --------------------------------------------------------
    # RALPH LAUREN
    # --------------------------------------------------------

    if "ralph lauren" not in combined:

        return {
            "qualifies": False,
            "reason": "not Ralph Lauren",
        }

    # --------------------------------------------------------
    # CLOTHING
    # --------------------------------------------------------

    if not is_clothing(combined):

        return {
            "qualifies": False,
            "reason": "not clothing",
        }

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    item_price = extract_price(
        card_text
    )

    if item_price is None:

        try:

            body = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            item_price = extract_price(
                body
            )

        except Exception:

            pass

    if item_price is None:

        return {
            "qualifies": False,
            "reason": "item price not found",
        }

    if item_price > MAX_ITEM_PRICE:

        return {
            "qualifies": False,
            "reason": (
                f"price over A${MAX_ITEM_PRICE:.2f}"
            ),
        }

    # --------------------------------------------------------
    # CONDITION
    # --------------------------------------------------------

    condition = extract_condition(
        card_text
    )

    if condition not in ACCEPTED_CONDITIONS:

        try:

            body = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

            condition = extract_condition(
                body
            )

        except Exception:

            pass

    if condition not in ACCEPTED_CONDITIONS:

        return {
            "qualifies": False,
            "reason": "condition not accepted",
        }

    # --------------------------------------------------------
    # BRAND
    # --------------------------------------------------------

    brand = "Ralph Lauren"

    try:

        body = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        )

        match = re.search(
            r"Brand\s+(.+?)(?:\n|Size|Condition|Shipping|$)",
            body,
            flags=re.IGNORECASE,
        )

        if match:

            brand = match.group(1).strip()

    except Exception:

        pass

    excluded = excluded_brand(
        brand
    )

    if excluded:

        return {
            "qualifies": False,
            "reason": (
                f"excluded brand: {excluded}"
            ),
        }

    # --------------------------------------------------------
    # SHIPPING
    # --------------------------------------------------------

    delivery = extract_delivery(
        page
    )

    if delivery is None:

        return {
            "qualifies": False,
            "reason": (
                "shipping price not explicitly found"
            ),
        }

    if delivery >= MAX_DELIVERY_PRICE:

        return {
            "qualifies": False,
            "reason": (
                f"delivery A${delivery:.2f} "
                f"or higher"
            ),
        }

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    return {
        "qualifies": True,
        "title": title,
        "url": url,
        "item_price": item_price,
        "delivery": delivery,
        "condition": condition,
        "brand": brand,
    }


# ============================================================
# EMAIL
# ============================================================

def send_email(listings):

    if not listings:
        return False

    if not RESEND_API_KEY:

        print(
            "RESEND_API_KEY not found."
        )

        return False

    resend.api_key = RESEND_API_KEY

    rows = []

    for item in listings:

        rows.append(
            f"""
            <div style="
                border:1px solid #ddd;
                border-radius:10px;
                padding:16px;
                margin-bottom:14px;
            ">

                <h2>
                    {item["title"]}
                </h2>

                <p>
                    <b>Item:</b>
                    A${item["item_price"]:.2f}
                </p>

                <p>
                    <b>Delivery:</b>
                    A${item["delivery"]:.2f}
                </p>

                <p>
                    <b>Condition:</b>
                    {item["condition"].title()}
                </p>

                <p>
                    <b>Brand:</b>
                    {item["brand"]}
                </p>

                <p>
                    <a href="{item["url"]}">
                        View listing on Vinted
                    </a>
                </p>

            </div>
            """
        )

    html = f"""
    <html>
    <body style="
        font-family:Arial,sans-serif;
        max-width:700px;
        margin:auto;
        padding:20px;
    ">

        <h1>Ralph Lauren Vinted Deals</h1>

        <p>
            Found {len(listings)}
            new qualifying listing(s).
        </p>

        <p>
            Item price ≤ A${MAX_ITEM_PRICE:.2f}<br>
            Delivery &lt; A${MAX_DELIVERY_PRICE:.2f}<br>
            Accepted conditions only
        </p>

        {"".join(rows)}

    </body>
    </html>
    """

    try:

        result = resend.Emails.send(
            {
                "from": EMAIL_FROM,
                "to": [EMAIL_TO],
                "subject": (
                    f"{len(listings)} new Ralph Lauren "
                    f"Vinted deal"
                    + (
                        "s"
                        if len(listings) != 1
                        else ""
                    )
                ),
                "html": html,
            }
        )

        print(
            "Email sent successfully."
        )

        print(result)

        return True

    except Exception as e:

        print(
            "Email failed:"
        )

        print(e)

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 40)
    print(
        "RALPH LAUREN VINTED MONITOR"
    )
    print("=" * 40)

    print(
        f"Maximum item price: "
        f"A${MAX_ITEM_PRICE:.2f}"
    )

    print(
        f"Maximum delivery: "
        f"under A${MAX_DELIVERY_PRICE:.2f}"
    )

    print(
        "Accepted conditions: "
        + ", ".join(
            sorted(
                ACCEPTED_CONDITIONS
            )
        )
    )

    print(
        f"Email interval: "
        f"{EMAIL_INTERVAL_HOURS} hours"
    )

    print("=" * 40)

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    seen_data = load_json(
        SEEN_FILE,
        [],
    )

    if isinstance(
        seen_data,
        list,
    ):

        seen = {
            str(x)
            for x in seen_data
            if isinstance(x, str)
        }

    else:

        seen = set()

    queue = load_json(
        QUEUE_FILE,
        [],
    )

    if not isinstance(
        queue,
        list,
    ):

        queue = []

    queue = [
        item
        for item in queue
        if isinstance(item, dict)
        and item.get("url")
    ]

    rejection_reasons = {}

    catalogue_count = 0
    candidates_count = 0
    checked_count = 0
    delivery_found_count = 0
    delivery_pass_count = 0
    new_count = 0
    already_seen_count = 0

    new_items = []

    # ========================================================
    # BROWSER
    # ========================================================

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="en-AU",
        )

        print()
        print(
            "Opening Vinted..."
        )

        page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        print(
            "Waiting for Vinted catalogue..."
        )

        # Give Vinted time to render its JavaScript
        time.sleep(3)

        # Try to wait for item links
        try:

            page.wait_for_selector(
                'a[href*="/items/"]',
                timeout=15000,
            )

            print(
                "Vinted item links detected."
            )

        except Exception:

            print(
                "Normal item-link wait timed out."
            )

            # Scroll to force lazy-loaded listings
            try:

                for _ in range(5):

                    page.mouse.wheel(
                        0,
                        1500,
                    )

                    time.sleep(1)

            except Exception:

                pass

        print(
            "Finding listing cards..."
        )

        listings = extract_listing_cards(
            page
        )

        # ----------------------------------------------------
        # RETRY
        # ----------------------------------------------------

        if not listings:

            print(
                "No listings found. "
                "Refreshing catalogue..."
            )

            try:

                page.reload(
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                time.sleep(5)

                listings = (
                    extract_listing_cards(
                        page
                    )
                )

            except Exception as e:

                print(
                    "Refresh failed:",
                    e,
                )

        catalogue_count = len(
            listings
        )

        print()
        print(
            f"Found {catalogue_count} "
            f"listing links."
        )

        print(
            f"Extracted {catalogue_count} "
            f"individual listing cards."
        )

        if not listings:

            print()
            print(
                "ERROR: Vinted catalogue "
                "returned no listing links."
            )

            print(
                "The monitor will NOT modify "
                "the existing seen state."
            )

            browser.close()

            return

        # ----------------------------------------------------
        # SAMPLES
        # ----------------------------------------------------

        for i, listing in enumerate(
            listings[:10],
            start=1,
        ):

            print()
            print(
                f"========== SAMPLE {i} =========="
            )

            print(
                "URL:",
                listing["url"],
            )

            print(
                "CARD:",
                listing["card_text"][:250],
            )

            print(
                "TITLE:",
                slug_to_title(
                    listing["url"]
                ),
            )

        # ====================================================
        # FAST FILTER
        # ====================================================

        candidates = []

        for listing in listings:

            url = listing["url"]
            card = listing.get(
                "card_text",
                "",
            )

            # URL exclusions
            excluded = excluded_by_url(
                url
            )

            if excluded:

                reason = (
                    f"excluded word in URL: "
                    f"{excluded}"
                )

                rejection_reasons[reason] = (
                    rejection_reasons.get(
                        reason,
                        0,
                    ) + 1
                )

                continue

            # Card exclusions
            excluded = contains_excluded_word(
                card
            )

            if excluded:

                reason = (
                    f"excluded word: "
                    f"{excluded}"
                )

                rejection_reasons[reason] = (
                    rejection_reasons.get(
                        reason,
                        0,
                    ) + 1
                )

                continue

            # Brand exclusions
            excluded = excluded_brand(
                card + " " + url
            )

            if excluded:

                reason = (
                    f"excluded brand: "
                    f"{excluded}"
                )

                rejection_reasons[reason] = (
                    rejection_reasons.get(
                        reason,
                        0,
                    ) + 1
                )

                continue

            # Price
            price = extract_price(
                card
            )

            if (
                price is not None
                and price > MAX_ITEM_PRICE
            ):

                reason = (
                    f"price over "
                    f"A${MAX_ITEM_PRICE:.2f}"
                )

                rejection_reasons[reason] = (
                    rejection_reasons.get(
                        reason,
                        0,
                    ) + 1
                )

                continue

            candidates.append(
                listing
            )

        candidates_count = len(
            candidates
        )

        print()
        print(
            f"Candidates after fast filters: "
            f"{candidates_count}"
        )

        # ====================================================
        # DETAIL PAGES
        # ====================================================

        for listing in candidates:

            url = listing["url"]

            if url in seen:

                already_seen_count += 1

                continue

            checked_count += 1

            print()
            print(
                "Opening:",
                url,
            )

            try:

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                time.sleep(1)

                result = inspect_listing(
                    page,
                    listing,
                )

            except Exception as e:

                reason = "page error"

                rejection_reasons[reason] = (
                    rejection_reasons.get(
                        reason,
                        0,
                    ) + 1
                )

                print(
                    "Page error:",
                    e,
                )

                continue

            if not result.get(
                "qualifies"
            ):

                reason = result.get(
                    "reason",
                    "unknown",
                )

                rejection_reasons[reason] = (
                    rejection_reasons.get(
                        reason,
                        0,
                    ) + 1
                )

                continue

            delivery_found_count += 1
            delivery_pass_count += 1

            print()
            print(
                "NEW QUALIFYING LISTING!"
            )

            print(
                "  Title:",
                result["title"],
            )

            print(
                "  Item:",
                f'A${result["item_price"]:.2f}',
            )

            print(
                "  Delivery:",
                f'A${result["delivery"]:.2f}',
            )

            print(
                "  Condition:",
                result["condition"],
            )

            print(
                "  Brand:",
                result["brand"],
            )

            print(
                "  URL:",
                result["url"],
            )

            seen.add(
                result["url"]
            )

            new_items.append(
                result
            )

            new_count += 1

        browser.close()

    # ========================================================
    # QUEUE
    # ========================================================

    queue.extend(
        new_items
    )

    unique_queue = {}

    for item in queue:

        url = item.get(
            "url"
        )

        if url:
            unique_queue[url] = item

    queue = list(
        unique_queue.values()
    )

    # ========================================================
    # EMAIL
    # ========================================================

    now = datetime.now(
        timezone.utc
    )

    send_digest = False

    last_email_time = None

    if os.path.exists(
        LAST_EMAIL_FILE
    ):

        try:

            with open(
                LAST_EMAIL_FILE,
                "r",
                encoding="utf-8",
            ) as f:

                last_email_time = (
                    datetime.fromisoformat(
                        f.read().strip()
                    )
                )

        except Exception:

            last_email_time = None

    if queue:

        if last_email_time is None:

            send_digest = True

        elif (
            now - last_email_time
            >= timedelta(
                hours=EMAIL_INTERVAL_HOURS
            )
        ):

            send_digest = True

    if send_digest:

        if send_email(
            queue
        ):

            queue = []

            with open(
                LAST_EMAIL_FILE,
                "w",
                encoding="utf-8",
            ) as f:

                f.write(
                    now.isoformat()
                )

    # ========================================================
    # SAVE
    # ========================================================

    save_json(
        SEEN_FILE,
        sorted(seen),
    )

    save_json(
        QUEUE_FILE,
        queue,
    )

    # ========================================================
    # RESULTS
    # ========================================================

    print()
    print("=" * 40)
    print(
        "SCAN RESULTS"
    )
    print("=" * 40)

    print(
        "Catalogue listings:",
        catalogue_count,
    )

    print(
        "Candidates after fast filters:",
        candidates_count,
    )

    print(
        "New candidates checked:",
        checked_count,
    )

    print(
        "Delivery prices found:",
        delivery_found_count,
    )

    print(
        f"Passed delivery < "
        f"A${MAX_DELIVERY_PRICE:.2f}:",
        delivery_pass_count,
    )

    print(
        "Already seen:",
        already_seen_count,
    )

    print(
        "New qualifying listings:",
        new_count,
    )

    print(
        "Listings currently in email queue:",
        len(queue),
    )

    print()
    print(
        "TOP REJECTION REASONS"
    )

    if rejection_reasons:

        sorted_reasons = sorted(
            rejection_reasons.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        for reason, count in sorted_reasons[:15]:

            print(
                f"- {count}: {reason}"
            )

    else:

        print(
            "- None"
        )

    if queue:

        print()
        print(
            "Listings waiting for digest:"
        )

        for item in queue:

            print(
                f"- {item.get('title', 'Unknown')}"
            )

            print(
                f"  Item A${item.get('item_price', 0):.2f}"
            )

            print(
                f"  Delivery A${item.get('delivery', 0):.2f}"
            )

    else:

        print()
        print(
            "No listings waiting for email."
        )

    print()
    print(
        "Monitor finished successfully."
    )


if __name__ == "__main__":
    main()