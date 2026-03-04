"""
dm.de Product Detail Scraper (Selenium)
========================================
Extracts brand, product name, price, base price, and ingredients
from dm.de product detail pages.

Usage:
    python dm_productpage.py --input dm_gesichtspflege.csv --output dm_products_detail.csv
    python dm_productpage.py --diagnose --url "https://www.dm.de/balea-med-..."

Selectors confirmed via DevTools inspection:
    data-dmid="product-brand"                     → brand (e.g. "Balea med")
    data-dmid="detail-page-headline-product-title"→ h1 with product name inside <span>
    data-dmid="buybox"                             → price container
    data-dmid="Inhaltsstoffe-content"              → ingredients div (inside <details>)
    data-dmid="price-localized"                    → current price
    data-dmid="price-infos"                        → base price

Requirements:
    pip install selenium beautifulsoup4 pandas webdriver-manager
"""

import argparse
import logging
import re
import time
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("dm_productpage")
logger.setLevel(logging.DEBUG)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(ch)

fh = logging.FileHandler("dm_errors.log", mode="a", encoding="utf-8")
fh.setLevel(logging.ERROR)
fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(fh)
# ─────────────────────────────────────────────────────────────────────────────


def build_driver(headless=True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=de-DE,de;q=0.9")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
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
        logger.info("  🍪 Cookie banner dismissed.")
        time.sleep(1.5)
    except Exception:
        pass


def expand_ingredients(driver):
    """
    Ingredients are inside a <details> element with a <summary>Inhaltsstoffe</summary>.
    Click the summary to expand it so the content is accessible in the DOM.
    """
    try:
        summary = driver.find_element(
            By.XPATH, "//summary[contains(., 'Inhaltsstoffe')]"
        )
        driver.execute_script("arguments[0].click();", summary)
        time.sleep(0.8)
    except NoSuchElementException:
        pass


def parse_product(html: str, url: str) -> dict:
    """
    Parse a dm.de product detail page using confirmed data-dmid selectors.

    Confirmed from DevTools:
      h1[data-dmid="detail-page-headline-product-title"]
        └── span  → product name text
      [data-dmid="product-brand"]          → brand
      [data-dmid="price-localized"]        → current price e.g. "4,45 €"
      [data-dmid="price-infos"]            → base price e.g. "0,05 l (89,00 € je 1 l)"
      [data-dmid="buybox"]                 → price container (fallback)
      [data-dmid="Inhaltsstoffe-content"]  → ingredients div
        └── div.whitespace-pre-line        → full ingredients text
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── Brand ─────────────────────────────────────────────────────────────────
    brand = ""
    brand_el = soup.find(attrs={"data-dmid": "product-brand"})
    if brand_el:
        brand = brand_el.get_text(strip=True)

    # ── Product name ──────────────────────────────────────────────────────────
    product_name = ""
    h1 = soup.find("h1", attrs={"data-dmid": "detail-page-headline-product-title"})
    if h1:
        # Name is inside the first <span> child
        span = h1.find("span")
        product_name = span.get_text(strip=True) if span else h1.get_text(strip=True)

    # ── Price ─────────────────────────────────────────────────────────────────
    price = ""
    price_el = soup.find(attrs={"data-dmid": "price-localized"})
    if price_el:
        price = price_el.get_text(strip=True)
    else:
        # Fallback: find price inside buybox
        buybox = soup.find(attrs={"data-dmid": "buybox"})
        if buybox:
            # Look for text matching price pattern e.g. "4,45 €"
            m = re.search(r'\d+[.,]\d+\s*€', buybox.get_text())
            if m:
                price = m.group(0).strip()

    # ── Base price ────────────────────────────────────────────────────────────
    base_price = ""
    base_el = soup.find(attrs={"data-dmid": "price-infos"})
    if base_el:
        base_price = base_el.get_text(strip=True)

    # ── Ingredients ───────────────────────────────────────────────────────────
    # Inside <details> → <summary>Inhaltsstoffe</summary>
    #                  → <div data-dmid="Inhaltsstoffe-content">
    #                       → <div class="whitespace-pre-line"> ← actual text
    ingredients = ""
    ing_content = soup.find(attrs={"data-dmid": "Inhaltsstoffe-content"})
    if ing_content:
        # Try the whitespace-pre-line div first (confirmed in DevTools)
        pre_div = ing_content.find("div", class_=lambda c: c and "whitespace-pre-line" in c)
        if pre_div:
            ingredients = pre_div.get_text(strip=True)
        else:
            ingredients = ing_content.get_text(separator=" ", strip=True)

    # ── Rating ────────────────────────────────────────────────────────────────
    rating       = ""
    review_count = ""
    rating_el = soup.find(attrs={"data-dmid": "product-tile-rating"}) \
             or soup.find(attrs={"data-dmid": "product-rating"})
    if rating_el:
        source = rating_el.get("aria-label") or rating_el.get_text()
        m = re.search(r'(\d[.,]\d)\s*von\s*5', source)
        if m:
            rating = m.group(1).replace(",", ".")
        m2 = re.search(r'bei\s*(\d+)\s*Bewertung', source)
        if m2:
            review_count = m2.group(1)

    return {
        "url":          url,
        "brand":        brand,
        "product_name": product_name,
        "price":        price,
        "base_price":   base_price,
        "rating":       rating,
        "review_count": review_count,
        "ingredients":  ingredients,
    }


COOKIE_DISMISSED = False


def scrape_urls(urls: list[str], delay: float = 2.0) -> list[dict]:
    global COOKIE_DISMISSED
    results = []
    driver = build_driver(headless=True)
    logger.info("🚀 Chrome ready.\n")

    try:
        for i, url in enumerate(urls, 1):
            logger.info(f"[{i}/{len(urls)}] {url}")
            try:
                driver.get(url)

                if not COOKIE_DISMISSED:
                    time.sleep(2)
                    accept_cookies(driver)
                    COOKIE_DISMISSED = True

                # Wait for product title
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((
                            By.CSS_SELECTOR,
                            "h1[data-dmid='detail-page-headline-product-title']"
                        ))
                    )
                except TimeoutException:
                    logger.warning("  ⚠️  Title not found — parsing whatever loaded.")

                # Expand ingredients <details> block
                expand_ingredients(driver)

                html = driver.page_source
                row  = parse_product(html, url)

                has_data = row["brand"] or row["product_name"] or row["ingredients"]
                if has_data:
                    logger.info(
                        f"  ✅ {row['brand']} | {row['product_name']} | "
                        f"{'ingredients ✓' if row['ingredients'] else 'no ingredients'}"
                    )
                else:
                    logger.warning("  ⚠️  No data extracted.")
                    logger.error(f"No data extracted: {url}")

                results.append(row)

            except WebDriverException as e:
                logger.error(f"  ❌ WebDriver error: {e}")
                results.append(_empty_row(url))
            except Exception as e:
                logger.error(f"  ❌ Unexpected error: {e}")
                results.append(_empty_row(url))

            # Checkpoint every 25 URLs
            if i % 25 == 0:
                pd.DataFrame(results).to_csv(
                    "dm_detail_checkpoint.csv", index=False, encoding="utf-8-sig"
                )
                logger.info(f"\n💾 Checkpoint saved ({i} URLs done)\n")

            time.sleep(delay)

    finally:
        driver.quit()
        logger.info("🏁 Browser closed.")

    return results


def _empty_row(url):
    return {
        "url": url, "brand": "", "product_name": "",
        "price": "", "base_price": "", "rating": "",
        "review_count": "", "ingredients": ""
    }


def diagnose(url: str):
    """Load a single product URL and print all data-dmid values + key field values."""
    driver = build_driver(headless=False)
    print(f"\n🔍 DIAGNOSE — {url}")
    try:
        driver.get(url)
        accept_cookies(driver)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "h1[data-dmid='detail-page-headline-product-title']"
                ))
            )
        except TimeoutException:
            print("  ⚠️  Timed out waiting for h1.")

        expand_ingredients(driver)
        html = driver.page_source

        # Print all data-dmid values
        dmids = sorted(set(re.findall(r'data-dmid=["\']([^"\']+)["\']', html)))
        print(f"\n  data-dmid values found ({len(dmids)}):")
        for d in dmids:
            print(f"    • {d}")

        # Parse and show result
        row = parse_product(html, url)
        print(f"\n  Extracted fields:")
        for k, v in row.items():
            if k == "url":
                continue
            val = (v[:120] + "...") if v and len(v) > 120 else v
            print(f"    {k:<15} : {val}")
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",      default=None,
                        help="Input CSV with product URLs.")
    parser.add_argument("--output",     default="dm_products_detail.csv")
    parser.add_argument("--delay",      type=float, default=2.0)
    parser.add_argument("--url-column", default="product_url")
    parser.add_argument("--diagnose",   action="store_true",
                        help="Inspect a single URL and exit.")
    parser.add_argument("--url",        default=None,
                        help="Single URL to use with --diagnose.")
    args = parser.parse_args()

    if args.diagnose:
        target = args.url or "https://www.dm.de/balea-med-gesichtscreme-barriereschutz-ultra-sensitive-p4067796175059.html"
        diagnose(target)
        return

    if not args.input:
        print("ERROR: --input is required (or use --diagnose --url <url>)")
        return

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        return

    df_input = pd.read_csv(input_path)
    if args.url_column not in df_input.columns:
        print(f"ERROR: Column '{args.url_column}' not found. Available: {', '.join(df_input.columns)}")
        return

    urls = df_input[args.url_column].dropna().str.strip().tolist()
    urls = [u for u in urls if u]
    logger.info(f"📋 Loaded {len(urls)} URLs from '{args.input}'.\n")

    results = scrape_urls(urls, delay=args.delay)

    columns = ["url", "brand", "product_name", "price", "base_price",
               "rating", "review_count", "ingredients"]
    df_out = pd.DataFrame(results, columns=columns)

    # Strip newlines from all text fields
    str_cols = df_out.select_dtypes(include="object").columns
    df_out[str_cols] = df_out[str_cols].apply(
        lambda col: col.str.replace(r'\n', ' ', regex=True).str.strip()
    )

    df_out.to_csv(args.output, index=False, encoding="utf-8-sig")

    success = df_out[df_out["brand"].ne("") | df_out["product_name"].ne("") | df_out["ingredients"].ne("")]
    failed  = df_out[df_out["brand"].eq("") & df_out["product_name"].eq("") & df_out["ingredients"].eq("")]

    logger.info(f"\n✅ Done! Saved to '{args.output}'.")
    logger.info(f"   Successful : {len(success)} / {len(results)}")
    if len(failed):
        logger.info(f"   Failed     : {len(failed)} — see dm_errors.log for details")


if __name__ == "__main__":
    main()
