"""
scrape.py - ScanX News Scraper
================================
- Reads settings from config.json
- Scrapes 7 ScanX pages
- Appends new articles to news.json (dedup by URL)
- Automatically resets news.json at 3:15 PM

Run: python scrape.py
"""

import requests
from bs4 import BeautifulSoup
import json, time, re, os
from datetime import datetime
import pytz

# -- Load Config -------------------------------------------
with open("config.json", "r") as f:
    CONFIG = json.load(f)

NEWS_FILE = CONFIG["files"]["news_store"]
PAGES     = CONFIG["scraper"]["pages"]
IST       = pytz.timezone("Asia/Kolkata")

START_H = CONFIG["schedule"]["start_hour"]
START_M = CONFIG["schedule"]["start_minute"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://scanx.trade/",
}
# ----------------------------------------------------------


# -- Storage -----------------------------------------------
def load_news():
    if not os.path.exists(NEWS_FILE):
        return []
    with open(NEWS_FILE, "r", encoding="utf-8") as f:
        try:    return json.load(f)
        except: return []

def save_news(data):
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def reset_news():
    save_news([])
    print("   news.json RESET - fresh session started")

def is_session_start():
    """Returns True in first 5 minutes after 3:15 PM - triggers news.json reset"""
    now = datetime.now(IST)
    return (now.hour == START_H and
            START_M <= now.minute < START_M + 5)


# -- Title Cleaner -----------------------------------------
def clean_title(raw):
    t = raw.strip()
    # Fix jammed numbers: "FY2631 mins" -> "FY26 31 mins"
    t = re.sub(r'(\S)(\d{1,2})\s*(mins?|hrs?|hour)\s*ago',
               r'\1 \2 \3 ago', t, flags=re.IGNORECASE)
    # Remove time patterns like "25 mins ago"
    t = re.sub(r'\b\d{1,2}\s*(mins?|hrs?|hour)\s*ago\b', '', t, flags=re.IGNORECASE)
    # Remove date patterns like "11 Jun 26"
    t = re.sub(r'\b\d{1,2}\s+[A-Z][a-z]{2}\s+\d{2,4}\b', '', t)
    # Remove noise keywords
    t = re.sub(r'Q\d+\s*Results?\s*Live\s*Updates?\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'Trending\s*Live\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'Live\s*Updates?\s*', '', t, flags=re.IGNORECASE)
    # Remove repeated company name at the end
    words = t.split()
    first_words = [w.lower() for w in words[:5] if len(w) > 3]
    for i in range(len(words) - 1, len(words) // 2, -1):
        if words[i].lower() in first_words:
            words = words[:i]
            break
    t = ' '.join(words)
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'[\s\-#\d]+$', '', t).strip()
    t = t.strip("'\".,- ")
    return t if len(t) > 10 else None


# -- Scrapers ----------------------------------------------
def scrape_requests(url, source):
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        seen = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if "/stock-market-news/companies/" not in href:
                continue
            full_url = href if href.startswith("http") else "https://scanx.trade" + href
            if full_url in seen:
                continue
            title = clean_title(a_tag.get_text(separator=" ", strip=True))
            if title:
                seen.add(full_url)
                articles.append({"title": title, "url": full_url, "source": source})
        print(f"   [{source}] requests: {len(articles)} articles")
    except Exception as e:
        print(f"   [{source}] requests failed: {e}")
    return articles


def scrape_playwright(url, source):
    articles = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page    = browser.new_page(extra_http_headers=HEADERS)
            page.goto(url, wait_until="networkidle", timeout=40000)
            time.sleep(3)
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)

            links = page.query_selector_all("a[href*='/stock-market-news/companies/']")
            seen  = set()
            for link in links:
                try:
                    href     = link.get_attribute("href") or ""
                    full_url = "https://scanx.trade" + href if href.startswith("/") else href
                    if full_url in seen:
                        continue
                    headline = page.evaluate("""el => {
                        let h = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="head"]');
                        if (h && h.innerText.trim().length > 15) return h.innerText.trim();
                        return Array.from(el.childNodes)
                            .filter(n => n.nodeType === 3 && n.textContent.trim().length > 5)
                            .map(n => n.textContent.trim()).join(' ').trim();
                    }""", link.element_handle())
                    title = clean_title(str(headline)) if headline and len(str(headline)) > 15 \
                            else clean_title(link.inner_text().strip())
                    if title:
                        seen.add(full_url)
                        articles.append({"title": title, "url": full_url, "source": source})
                except:
                    continue
            browser.close()
        print(f"   [{source}] playwright: {len(articles)} articles")
    except Exception as e:
        print(f"   [{source}] playwright failed: {e}")
        print("   -> Run: playwright install chromium")
    return articles


# -- Main --------------------------------------------------
def run():
    print("\n" + "="*50)
    print("  SCRAPING SCANX - 7 PAGES")
    print("="*50)

    # Reset news.json at session start (3:15 PM)
    if is_session_start():
        print("\n[SESSION START] 3:15 PM - resetting news.json")
        reset_news()

    existing    = load_news()
    seen_urls   = {a["url"] for a in existing}
    scraped_at  = datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S")
    added_total = 0

    for pg in PAGES:
        url, source = pg["url"], pg["source"]
        print(f"\n[{source.upper()}]")

        articles = scrape_requests(url, source)
        if len(articles) < 3:
            print("   Too few results - switching to Playwright...")
            articles = scrape_playwright(url, source)

        for a in articles:
            if a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                a["scraped_at"] = scraped_at
                existing.append(a)
                added_total += 1

        time.sleep(1)

    save_news(existing)
    print(f"\nAdded: {added_total} new | Total in news.json: {len(existing)}")


if __name__ == "__main__":
    run()