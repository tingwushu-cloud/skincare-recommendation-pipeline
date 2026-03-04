"""
dm.de Gesichtspflege Subcategory Scraper
==========================================
Scrapes all product tiles across multiple Gesichtspflege subcategories.

Usage:
    python dm_searchpage.py                            # scrape all subcategories
    python dm_searchpage.py --subcategory tagescreme   # one subcategory only
    python dm_searchpage.py --diagnose                 # print raw tile fields
    python dm_searchpage.py --visible                  # show browser window

Requirements:
    pip install selenium pandas webdriver-manager
"""

import os
import re
import time
import random
import argparse
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
from webdriver_manager.chrome import ChromeDriverManager

# ── Subcategories ─────────────────────────────────────────────────────────────
SUBCATEGORIES = [
    ("tagescreme",          "Tagescreme"),
    ("nachtcreme",          "Nachtcreme"),
    ("augenpflege",         "Augenpflege"),
    ("gesichtscreme",       "Gesichtscreme"),
    ("serum",               "Serum"),
    ("feuchtigkeitspflege", "Feuchtigkeitspflege"),
    ("gesichtsmasken",      "Gesichtsmasken"),
    ("lippenpflege",        "Lippenpflege"),
    ("sonnenschutz",        "Sonnenschutz"),
    ("gesichtsreinigung",   "Gesichtsreinigung"),
]

BASE_URL   = "https://www.dm.de/pflege-und-parfum/gesichtspflege"
DM_ROOT    = "https://www.dm.de"
MAX_CLICKS = 60

OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dm_gesichtspflege.csv"
)
# ─────────────────────────────────────────────────────────────────────────────

# Strips trailing "\n(480)" or "\n(480 Bewertungen)" from product name
TRAILING_REVIEW_RE = re.compile(r'\s*\n\s*\(\d+[^)]*\)\s*$')


def create_driver(headless=True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    options.add_argument("--lang=de-DE,de;q=0.9")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def accept_cookies(driver):
    try:
        btn = WebDriverWait(driver, 6).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(., 'Alle akzeptieren') "
                "or contains(., 'Akzeptieren') "
                "or contains(., 'Accept all')]"
            ))
        )
        btn.click()
        print("  ✔ Cookie banner accepted.")
        time.sleep(1.5)
    except Exception:
        print("  ℹ No cookie banner found.")


def get_tile_count(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, "[data-dmid='product-tile']"))


def load_all_products(driver):
    """Click 'Mehr laden' repeatedly until it disappears."""
    clicks = 0
    while clicks < MAX_CLICKS:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(1.0, 1.5))
        try:
            btn = WebDriverWait(driver, 6).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-dmid='load-more-products-button']")
                )
            )
            if not btn.is_displayed():
                break
            count_before = get_tile_count(driver)
            driver.execute_script("arguments[0].click();", btn)
            clicks += 1
            try:
                WebDriverWait(driver, 8).until(
                    lambda d: get_tile_count(d) > count_before
                )
            except TimeoutException:
                pass
            print(f"    ↻ Click #{clicks} — {get_tile_count(driver)} tiles loaded")
        except TimeoutException:
            break
        except ElementClickInterceptedException:
            time.sleep(1)
            continue

    total = get_tile_count(driver)
    print(f"  ✔ All products loaded: {total} tiles ({clicks} load-more clicks)")


def clean_name(raw_name, brand):
    """
    1. Strip leading brand prefix (product-description includes it).
    2. Strip trailing review count like '\n(480)' or '\n(480 Bewertungen)'.
    """
    name = raw_name or ""

    # Strip brand prefix
    if brand and name.startswith(brand):
        name = name[len(brand):].lstrip("\n ").strip()

    # Strip trailing "\n(480)" artifact
    name = TRAILING_REVIEW_RE.sub("", name).strip()

    return name or None


def parse_tile(tile, subcategory_label):
    def dmid_text(dmid):
        try:
            return tile.find_element(
                By.CSS_SELECTOR, f"[data-dmid='{dmid}']"
            ).text.strip() or None
        except Exception:
            return None

    # ── Identifiers ───────────────────────────────────────────────────────────
    gtin = tile.get_attribute("data-gtin") or None
    dan  = tile.get_attribute("data-dan")  or None

    # ── Brand & name ──────────────────────────────────────────────────────────
    brand    = dmid_text("product-brand")
    raw_name = dmid_text("product-description")
    name     = clean_name(raw_name, brand)

    # ── Price ─────────────────────────────────────────────────────────────────
    price      = dmid_text("price-localized")
    base_price = dmid_text("price-infos")

    # ── Rating (NaN accepted for new/unrated products) ────────────────────────
    rating       = None
    review_count = None
    try:
        rating_el = tile.find_element(By.CSS_SELECTOR, "[data-dmid='product-tile-rating']")
        source = rating_el.get_attribute("aria-label") or rating_el.text or ""
        m = re.search(r'(\d[.,]\d)\s*von\s*5', source)
        if m:
            rating = m.group(1).replace(",", ".")
        m2 = re.search(r'bei\s*(\d+)\s*Bewertung', source)
        if m2:
            review_count = m2.group(1)
    except Exception:
        pass

    # ── Availability ──────────────────────────────────────────────────────────
    availability = dmid_text("overview-availability-container")

    # ── Product URL ───────────────────────────────────────────────────────────
    product_url = None
    try:
        for a in tile.find_elements(By.CSS_SELECTOR, "a[href]"):
            href = a.get_attribute("href") or ""
            if href and "cart" not in href and "wishlist" not in href and "shoppinglist" not in href:
                product_url = href if href.startswith("http") else DM_ROOT + href
                break
    except Exception:
        pass

    # ── Image ─────────────────────────────────────────────────────────────────
    image_url = None
    try:
        img = tile.find_element(
            By.CSS_SELECTOR, "[data-dmid='product-image-container'] img"
        )
        image_url = img.get_attribute("src") or img.get_attribute("data-src")
    except Exception:
        try:
            img = tile.find_element(By.TAG_NAME, "img")
            image_url = img.get_attribute("src") or img.get_attribute("data-src")
        except Exception:
            pass

    if not gtin and not product_url:
        return None

    return {
        "subcategory":  subcategory_label,
        "brand":        brand,
        "name":         name,
        "price":        price,
        "base_price":   base_price,
        "rating":       rating,
        "review_count": review_count,
        "availability": availability,
        "gtin":         gtin,
        "dan":          dan,
        "product_url":  product_url,
        "image_url":    image_url,
    }


def scrape_subcategory(driver, slug, label, cookie_dismissed):
    url = f"{BASE_URL}/{slug}"
    print(f"\n{'─'*55}")
    print(f"Subcategory : {label}")
    print(f"URL         : {url}")

    driver.get(url)

    if not cookie_dismissed:
        accept_cookies(driver)
        cookie_dismissed = True
    else:
        time.sleep(2)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-dmid='product-tile']")
            )
        )
    except TimeoutException:
        print(f"  ✘ No tiles loaded for '{label}' — skipping.")
        return [], cookie_dismissed

    load_all_products(driver)

    tiles    = driver.find_elements(By.CSS_SELECTOR, "[data-dmid='product-tile']")
    products = [p for t in tiles for p in [parse_tile(t, label)] if p]
    print(f"  ✔ {len(products)} products extracted")

    return products, cookie_dismissed


def diagnose(driver, url):
    print(f"\n🔍 DIAGNOSE — {url}")
    driver.get(url)
    accept_cookies(driver)
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-dmid='product-tile']")
            )
        )
    except TimeoutException:
        print("  ✘ No tiles found.")
        return

    tiles = driver.find_elements(By.CSS_SELECTOR, "[data-dmid='product-tile']")
    print(f"\n  {len(tiles)} tiles. First 3:\n")
    for i, tile in enumerate(tiles[:3], 1):
        print(f"  ── Tile {i}  gtin={tile.get_attribute('data-gtin')} ───────────")
        for child in tile.find_elements(By.CSS_SELECTOR, "[data-dmid]"):
            dmid = child.get_attribute("data-dmid")
            txt  = child.text.strip().replace("\n", " | ")[:90]
            aria = (child.get_attribute("aria-label") or "")[:60]
            if txt or aria:
                print(f"    [{dmid}]")
                if txt:  print(f"      text : {txt}")
                if aria: print(f"      aria : {aria}")
        try:
            a = tile.find_element(By.CSS_SELECTOR, "a[href]")
            print(f"    [link] {a.get_attribute('href')}")
        except Exception:
            pass
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subcategory", default=None)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--visible",  action="store_true")
    args = parser.parse_args()

    if args.subcategory:
        targets = [(s, l) for s, l in SUBCATEGORIES if s == args.subcategory]
        if not targets:
            print(f"Unknown: '{args.subcategory}'. Available: {', '.join(s for s,_ in SUBCATEGORIES)}")
            return
    else:
        targets = SUBCATEGORIES

    driver = create_driver(headless=not args.visible)

    if args.diagnose:
        slug, _ = targets[0]
        try:
            diagnose(driver, f"{BASE_URL}/{slug}")
        finally:
            driver.quit()
        return

    all_products     = []
    cookie_dismissed = False

    try:
        for slug, label in targets:
            products, cookie_dismissed = scrape_subcategory(
                driver, slug, label, cookie_dismissed
            )
            all_products.extend(products)
            time.sleep(random.uniform(2, 4))
    finally:
        driver.quit()

    print(f"\n{'═'*55}")
    print(f"Total products scraped: {len(all_products)}")

    df = pd.DataFrame(all_products, columns=[
        "subcategory", "brand", "name", "price", "base_price",
        "rating", "review_count", "availability",
        "gtin", "dan", "product_url", "image_url"
    ])

    print("\nProducts per subcategory:")
    for label, count in df.groupby("subcategory", sort=False).size().items():
        print(f"  {label:<25} {count}")

    # Strip newlines from all text fields so each product = exactly one CSV line
    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(
        lambda col: col.str.replace(r'\n', ' ', regex=True).str.strip()
    )

    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\nCSV saved to: {OUTPUT_FILE}")
    print("\nPreview (first 5 rows):")
    print(df[["subcategory", "brand", "name", "price", "rating"]].head())


if __name__ == "__main__":
    main()
