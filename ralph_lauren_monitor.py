import os
import json
import re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright
import resend


# ============================================================
# SETTINGS
# ============================================================

SEARCH_URL = (
    "https://www.vinted.com.au/catalog"
    "?search_text=Ralph+Lauren"
    "&order=newest_first"
)

MAX_PRICE = 15.00
MAX_DELIVERY = 6.00

EMAIL_TO = "prylesarchie@gmail.com"
EMAIL_FROM = "onboarding@resend.dev"

SEEN_FILE = "seen_listings.json"
QUEUE_FILE = "email_queue.json"

# Send a digest at most once every 2 hours
EMAIL_INTERVAL_HOURS = 2


# ============================================================
# ACCEPTED CONDITIONS
# ============================================================

ACCEPTED_CONDITIONS = {
    "good",
    "very good",
    "new with tags",
    "new without tags",
}


# ============================================================
# EXCLUSIONS
# ============================================================

EXCLUDED_WORDS = [
    "women",
    "woman",
    "womens",
    "women's",
    "girls",
    "girl",
    "baby",
    "babies",
    "kids",
    "kid",
    "child",
    "children",
    "boy",
    "boys",
    "boy's",
    "maternity",
    "dress",
    "skirt",
    "leggings",
    "bra",
    "lingerie",
    "swimwear",
    "bikini",
    "toddler",
]

EXCLUDED_BRANDS = [
    "u.s. polo assn",
    "us polo assn",
    "u.s polo assn",
    "chaps",
    "polo sport",
    "polo club",
]

MEN_WORDS = [
    "men",
    "mens",
    "men's",
    "male",
    "man",
]

ADULT_CLOTHING_WORDS = [
    "shirt",
    "t-shirt",
    "tshirt",
    "tee",
    "polo",
    "jumper",
    "sweater",
    "hoodie",
    "jacket",
    "coat",
    "vest",
    "trousers",
    "pants",
    "jeans",
    "shorts",
    "blazer",
    "cardigan",
    "sweatshirt",
    "top",
]


# ============================================================
# FILE HELPERS
# ============================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def extract_price(text):
    """
    Finds the first Australian dollar price.
    """
    match = re.search(
        r"(?:A\$\s*|\$\s*)(\d+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def extract_condition(text):
    lower = text.lower()

    # Check longer conditions first
    for condition in [
        "new without tags",
        "new with tags",
        "very good",
        "good",
    ]:
        if f"condition: {condition}" in lower:
            return condition

        if condition in lower:
            return condition

    return None


def extract_delivery(text):
    """
    Only returns a delivery price if the text explicitly associates
    an Australian dollar amount with delivery/postage/shipping.

    We deliberately do NOT assume that the second price in a Vinted
    title is delivery.
    """

    patterns = [
        r"(?:delivery|postage|shipping|shipping fee)[^A$]{0,30}"
        r"A\$\s*(\d+(?:\.\d{1,2})?)",

        r"A\$\s*(\d+(?:\.\d{1,2})?)[^A$]{0,30}"
        r"(?:delivery|postage|shipping|shipping fee)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

    return None


def strip_vinted_metadata(title):
    """
    Turns:
    Ralph Lauren Polo, Brand: Ralph Lauren, Condition: Good, Size: M

    into:
    Ralph Lauren Polo
    """

    title = re.split(
        r",\s*(?:Brand|Condition|Size|Category|Material)\s*:",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    return clean_text(title)


def looks_like_kids(title):
    lower = title.lower()

    patterns = [
        r"\bage\s*\d+\b",
        r"\b\d+\s*-\s*\d+\s*years?\b",
        r"\b\d+\s*years?\s*old\b",
        r"\b\d+\s*y/o\b",
    ]

    return any(re.search(pattern, lower) for pattern in patterns)


# ============================================================
# LISTING FILTER
# ============================================================

def qualifies_listing(title, price, delivery, condition):
    lower = title.lower()

    # Price
    if price is None or price > MAX_PRICE:
        return False

    # Delivery must actually be known
    if delivery is None:
        return False

    if delivery >= MAX_DELIVERY:
        return False

    # Condition
    if condition not in ACCEPTED_CONDITIONS:
        return False

    # Kids
    if looks_like_kids(title):
        return False

    # Excluded words
    for word in EXCLUDED_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", lower):
            return False

    # Excluded brands
    for brand in EXCLUDED_BRANDS:
        if brand in lower:
            return False

    # Must look like men's clothing
    has_men_word = any(
        re.search(r"\b" + re.escape(word) + r"\b", lower)
        for word in MEN_WORDS
    )

    has_clothing_word = any(
        word in lower for word in ADULT_CLOTHING_WORDS
    )

    if not has_men_word:
        return False

    if not has_clothing_word:
        return False

    # Ralph Lauren must be present
    if "ralph lauren" not in lower:
        return False

    return True


# ============================================================
# EMAIL
# ============================================================

def send_digest(listings):
    if not listings:
        return False

    api_key = os.environ.get("RESEND_API_KEY")

    if not api_key:
        print("ERROR: RESEND_API_KEY is not set.")
        return False

    resend.api_key = api_key

    html_items = []
    text_items = []

    for item in listings:
        title = item["title"]
        price = item["price"]
        delivery = item["delivery"]
        condition = item["condition"]
        url = item["url"]

        html_items.append(
            f"""
            <div style="margin-bottom:24px;">
                <h3 style="margin-bottom:6px;">
                    {title}
                </h3>

                <div>
                    💰 <strong>A${price:.2f}</strong>
                </div>

                <div>
                    🚚 Delivery: <strong>A${delivery:.2f}</strong>
                </div>

                <div>
                    ⭐ Condition: <strong>{condition.title()}</strong>
                </div>

                <div style="margin-top:8px;">
                    <a href="{url}">🔗 View listing</a>
                </div>
            </div>
            """
        )

        text_items.append(
            f"{title}\n"
            f"Price: A${price:.2f}\n"
            f"Delivery: A${delivery:.2f}\n"
            f"Condition: {condition.title()}\n"
            f"Link: {url}\n"
        )

    html = f"""
    <html>
    <body>
        <h2>🔥 Ralph Lauren Vinted Finds</h2>

        <p>
            {len(listings)} new qualifying listing(s) found.
        </p>

        {"".join(html_items)}

        <hr>

        <p>
            Filters: men's adult Ralph Lauren · item ≤ A$15 ·
            delivery &lt; A$6
        </p>
    </body>
    </html>
    """

    text = (
        "🔥 Ralph Lauren Vinted Finds\n\n"
        + "\n--------------------\n\n".join(text_items)
        + "\n\nFilters: men's adult Ralph Lauren, "
          "item ≤ A$15, delivery < A$6"
    )

    try:
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [EMAIL_TO],
            "subject": f"🔥 {len(listings)} new Ralph Lauren Vinted find(s)",
            "html": html,
            "text": text,
        })

        print(f"Email sent with {len(listings)} listing(s).")
        return True

    except Exception as e:
        print(f"Email failed: {e}")
        return False


# ============================================================
# MAIN
# ============================================================

def main():

    seen = load_json(SEEN_FILE, [])
    queue = load_json(QUEUE_FILE, {
        "listings": [],
        "last_email": None,
    })

    seen = set(seen)

    queued_listings = queue.get("listings", [])
    last_email = queue.get("last_email")

    print("========================================")
    print("Ralph Lauren Vinted Monitor")
    print("========================================")
    print(f"Maximum item price: A${MAX_PRICE:.2f}")
    print(f"Maximum delivery: A${MAX_DELIVERY:.2f}")
    print("Email interval: 2 hours")
    print("")

    found = []

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

        print("Opening Vinted...")

        page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        # Scroll so Vinted loads more listings
        for _ in range(5):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1000)

        links = page.locator("a[title]")
        count = links.count()

        print(f"Found {count} possible listings.")

        for i in range(count):

            try:
                link = links.nth(i)

                raw_title = link.get_attribute("title")
                url = link.get_attribute("href")

                if not raw_title or not url:
                    continue

                raw_title = clean_text(raw_title)

                price = extract_price(raw_title)
                condition = extract_condition(raw_title)
                delivery = extract_delivery(raw_title)

                title = strip_vinted_metadata(raw_title)

                if not qualifies_listing(
                    title,
                    price,
                    delivery,
                    condition,
                ):
                    continue

                if url.startswith("/"):
                    url = "https://www.vinted.com.au" + url

                listing_id_match = re.search(
                    r"/items/(\d+)",
                    url
                )

                if listing_id_match:
                    listing_id = listing_id_match.group(1)
                else:
                    listing_id = url

                if listing_id in seen:
                    continue

                item = {
                    "id": listing_id,
                    "title": title,
                    "price": price,
                    "delivery": delivery,
                    "condition": condition,
                    "url": url,
                    "found_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }

                found.append(item)
                seen.add(listing_id)

            except Exception:
                continue

        browser.close()

    print(
        f"New qualifying listings this scan: {len(found)}"
    )

    # Add newly found listings to the 2-hour queue
    queued_listings.extend(found)

    # Remove duplicates from queue
    unique_queue = {}

    for item in queued_listings:
        unique_queue[item["id"]] = item

    queued_listings = list(unique_queue.values())

    # Determine whether it is time for an email
    now = datetime.now(timezone.utc)

    should_send = False

    if queued_listings:

        if not last_email:
            should_send = True

        else:
            try:
                previous = datetime.fromisoformat(last_email)

                if now - previous >= timedelta(
                    hours=EMAIL_INTERVAL_HOURS
                ):
                    should_send = True

            except Exception:
                should_send = True

    if should_send:

        print(
            f"Sending 2-hour digest with "
            f"{len(queued_listings)} listing(s)..."
        )

        success = send_digest(
            queued_listings
        )

        if success:
            queued_listings = []
            last_email = now.isoformat()

    else:
        if queued_listings:
            print(
                f"Keeping {len(queued_listings)} listing(s) "
                f"in queue until next 2-hour email."
            )
        else:
            print("No listings waiting for email.")

    # Save state
    save_json(
        SEEN_FILE,
        sorted(seen),
    )

    save_json(
        QUEUE_FILE,
        {
            "listings": queued_listings,
            "last_email": last_email,
        },
    )

    print("Done.")


if __name__ == "__main__":
    main()