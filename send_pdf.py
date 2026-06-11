"""
send_pdf.py - PDF Generator + Telegram Sender
===============================================
- Reads settings from config.json
- Reads articles from news.json
- Generates PDF (8 sections)
- Sends SINGLE message to Telegram - PDF + caption together
- Caption format:
    Daily Market Brief - 11 Jun 2026 | Pre-open Edition
    Session: 3:15 PM, 10 Jun to 8:45 AM, 11 Jun 2026
    32 news captured

Run: python send_pdf.py
"""

import requests
from fpdf import FPDF
import json, os, time
from datetime import datetime, timedelta
import pytz

# -- Load Config -------------------------------------------
with open("config.json", "r") as f:
    CONFIG = json.load(f)

# Telegram - read from env var (GitHub Actions), fallback to config.json
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or CONFIG["telegram"]["bot_token"]
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")   or CONFIG["telegram"]["chat_id"]

NEWS_FILE = CONFIG["files"]["news_store"]
IST       = pytz.timezone("Asia/Kolkata")
# ----------------------------------------------------------


# -- Helpers -----------------------------------------------
def safe(text):
    return (str(text)
            .replace("\u2013", "-").replace("\u2014", "-")
            .replace("\u2018", "'").replace("\u2019", "'")
            .replace("\u20b9", "Rs").replace("\u2022", "-")
            .replace("**", "")
            .encode("latin-1", "ignore").decode("latin-1"))

def fmt_time(ts):
    try:    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").strftime("%I:%M %p").lstrip("0")
    except: return ""

def categorize(title, source):
    if source == "global":      return "Global"
    if source == "commodities": return "Commodities"
    if source == "orders":      return "Orders & Deals"
    t = title.lower()
    if any(w in t for w in ["result","profit","revenue","earnings","q4","q3","q2","q1",
                              "fy26","fy25","pat","ebitda","net profit"]):
        return "Earnings"
    if any(w in t for w in ["dividend","bonus","split","rights","esop","buyback",
                              "tds","preferential","warrant"]):
        return "Corporate Actions"
    if any(w in t for w in ["agm","egm","board meeting","conference call","investor meet",
                              "postal ballot","book closure","analyst meeting"]):
        return "Events"
    if any(w in t for w in ["acquisition","merger","deal","block trade","stake",
                              "acquires","block deal","buys shares"]):
        return "Orders & Deals"
    if any(w in t for w in ["nasdaq","dow","nikkei","hang seng","asia-pacific",
                              "us market","wall street","ftse"]):
        return "Global"
    if any(w in t for w in ["crude","oil","gold","silver","rupee","dollar","brent"]):
        return "Commodities"
    return "General"

def get_sentiment(title):
    t = title.lower()
    avoid = ["loss","deficit","cirp","insolvency","fraud","penalty","falls","declines",
             "net loss","suspended","ban","delisting","resigns","dips","drops","default"]
    pos   = ["profit","growth","record","expansion","acquisition","strong","surge",
             "rises","gains","dividend","award","contract","beats","exceeds",
             "subscribed","commences","launches","approves","up","higher"]
    if any(w in t for w in avoid): return "Avoid"
    if sum(1 for w in pos if w in t) >= 2: return "Positive"
    return "Neutral"

def parse(title):
    if " - " in title:
        parts = title.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    words = title.split()
    cut = len(words)
    for i, w in enumerate(words):
        if i > 1 and w.lower() in ["reports","launches","signs","gets","seeks","approves",
                                    "opens","increases","appoints","commences","completes",
                                    "publishes","corrects","acquires","outlines","releases",
                                    "records","dips","falls","holds","gains","rises",
                                    "schedules","declares","announces","issues","posts"]:
            cut = i; break
        if i > 0 and i <= 4 and len(w) > 1 and w[0].islower():
            cut = i; break
    return " ".join(words[:cut]), " ".join(words[cut:])

def make_session_label(articles):
    """Returns: '3:15 PM, 10 Jun  to  8:45 AM, 11 Jun 2026'"""
    if not articles:
        return "No data"
    try:
        first = datetime.strptime(articles[0]["scraped_at"],  "%Y-%m-%dT%H:%M:%S")
        last  = datetime.strptime(articles[-1]["scraped_at"], "%Y-%m-%dT%H:%M:%S")
        return (f"{first.strftime('%I:%M %p, %d %b').lstrip('0')}"
                f"  to  {last.strftime('%I:%M %p, %d %b %Y').lstrip('0')}")
    except:
        return "Session data"


# -- PDF Class ---------------------------------------------
class MarketBriefPDF(FPDF):

    def __init__(self, session_label, total_news):
        super().__init__()
        self.session_label = session_label
        self.total_news    = total_news

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 30, 30)
        self.cell(0, 9, "Daily Market Brief", align="C", ln=True)

        self.set_font("Helvetica", "", 9)
        self.set_text_color(100, 100, 100)
        now = datetime.now(IST)
        self.cell(0, 5,
                  now.strftime("%A, %d %B %Y") + "  |  Pre-open Edition",
                  align="C", ln=True)

        self.set_font("Helvetica", "I", 8)
        self.set_text_color(21, 101, 192)
        self.cell(0, 5,
                  safe(f"Session: {self.session_label}  |  {self.total_news} news captured"),
                  align="C", ln=True)

        self.ln(2)
        self.set_draw_color(180, 180, 180)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8,
                  f"Auto-generated by MarketBriefBot | Page {self.page_no()}",
                  align="C")

    def section_title(self, title, bg=(240,240,240), fg=(30,30,30)):
        self.set_font("Helvetica", "B", 10)
        self.set_fill_color(*bg)
        self.set_text_color(*fg)
        self.cell(0, 7, f"  {title}", ln=True, fill=True)
        self.ln(1)

    def body_text(self, text):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5.5, safe(text))
        self.ln(1)

    def summary_line(self, company, detail, sentiment):
        self.set_font("Helvetica", "", 9)
        if sentiment == "Positive":  self.set_text_color(21, 128, 61)
        elif sentiment == "Avoid":   self.set_text_color(185, 28, 28)
        else:                        self.set_text_color(50, 50, 50)
        d = detail[:85] if len(detail) > 85 else detail
        self.multi_cell(0, 5.5, safe(f"- {company} - {d} - {sentiment}"))
        self.ln(0.3)

    def plain_line(self, text, sentiment="Neutral"):
        self.set_font("Helvetica", "", 9)
        if sentiment == "Positive":  self.set_text_color(21, 128, 61)
        elif sentiment == "Avoid":   self.set_text_color(185, 28, 28)
        else:                        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5.5, safe(f"- {text}"))
        self.ln(0.3)


# -- Generate PDF ------------------------------------------
def generate_pdf(articles):
    print("[PDF] Generating...")

    session_label = make_session_label(articles)

    # Classify articles into sections
    actionable=[]; events=[]; market=[]; results=[]; corp=[]; orders=[]; globl=[]; commod=[]

    for a in articles:
        title  = a.get("title", "").strip()
        source = a.get("source", "")
        if not title: continue

        sent           = get_sentiment(title)
        cat            = categorize(title, source)
        company, detail = parse(title)

        if cat == "Global":
            sg = "Positive" if any(w in title.lower() for w in ["up","gains","rises","surges","higher","adds"]) \
                 else "Avoid" if any(w in title.lower() for w in ["falls","down","drops","declines","dips"]) \
                 else "Neutral"
            globl.append((company, detail, sg))
            continue

        if cat == "Commodities":
            sc = "Avoid"    if any(w in title.lower() for w in ["dips","falls","down","drops","declines"]) \
                 else "Positive" if any(w in title.lower() for w in ["rises","up","gains","surges","higher"]) \
                 else "Neutral"
            commod.append((company, detail, sc))
            continue

        if cat == "Orders & Deals": orders.append((company, detail, sent))
        market.append((company, detail, sent))
        if cat == "Events":              events.append((company, detail, sent))
        elif cat == "Corporate Actions": corp.append((company, detail, sent))
        elif cat == "Earnings":          results.append((company, detail, sent))
        if sent == "Positive":           actionable.append((company, detail, sent))

    filename = f"market_brief_{datetime.now(IST).strftime('%d-%m-%Y')}.pdf"
    pdf = MarketBriefPDF(session_label, len(articles))
    pdf.add_page()
    pdf.set_margins(12, 15, 12)

    # 1. ACTIONABLE
    pdf.section_title("Actionable")
    if actionable:
        parts = [f"{c} ({d[:55]})" for c, d, s in actionable[:8]]
        pdf.body_text(", ".join(parts))
    else:
        pdf.body_text("No strong actionable signals in this session.")
    pdf.ln(2)

    # 2. EVENTS
    pdf.section_title("Events")
    if events:
        for c, d, s in events: pdf.plain_line(f"{c} - {d[:100]}", "Neutral")
    else:
        pdf.body_text("No events in this session.")
    pdf.ln(2)

    # 3. MARKET SUMMARY
    pdf.section_title("Market Summary")
    if market:
        for c, d, s in market[:40]: pdf.summary_line(c, d, s)
    else:
        pdf.body_text("No market updates.")
    pdf.ln(2)

    # 4. RESULTS TODAY
    pdf.section_title("Results Today")
    if results:
        for c, d, s in results[:15]: pdf.plain_line(f"{c} - {d[:120]}", s)
    else:
        pdf.body_text("")
    pdf.ln(2)

    # 5. CORPORATE ACTIONS
    pdf.section_title("Corporate Actions")
    if corp:
        for c, d, s in corp[:15]: pdf.plain_line(f"{c} - {d[:120]}", "Neutral")
    else:
        pdf.body_text("No corporate actions.")
    pdf.ln(2)

    # 6. ORDERS & DEALS - green header
    pdf.section_title("Orders & Deals", bg=(232,245,233), fg=(39,80,10))
    if orders:
        for c, d, s in orders[:12]: pdf.plain_line(f"{c} - {d[:120]}", "Neutral")
    else:
        pdf.body_text("No orders & deals in this session.")
    pdf.ln(2)

    # 7. GLOBAL MARKETS - blue header
    pdf.section_title("Global Markets", bg=(227,240,255), fg=(12,68,124))
    if globl:
        for c, d, s in globl[:10]: pdf.plain_line(f"{c} - {d[:120]}", s)
    else:
        pdf.body_text("No global market news in this session.")
    pdf.ln(2)

    # 8. COMMODITIES - yellow header
    pdf.section_title("Commodities", bg=(255,248,225), fg=(99,56,6))
    if commod:
        for c, d, s in commod[:10]: pdf.plain_line(f"{c} - {d[:120]}", s)
    else:
        pdf.body_text("No commodity news in this session.")

    pdf.output(filename)
    print(f"[PDF] Saved: {filename}")
    return filename, session_label


# -- Telegram - SINGLE message with PDF -------------------
def send_telegram(pdf_path, session_label, total):
    """
    Sends ONE message - PDF file with caption below it.
    Caption example:
      Daily Market Brief - 11 Jun 2026 | Pre-open Edition
      Session: 3:15 PM, 10 Jun to 8:45 AM, 11 Jun 2026
      32 news captured
    """
    print("\n[TELEGRAM] Sending...")

    if "YOUR_BOT_TOKEN" in BOT_TOKEN or not BOT_TOKEN:
        print("[TELEGRAM] ERROR: Bot token missing! Add it in config.json")
        return
    if "YOUR_NUMERIC" in CHAT_ID or not CHAT_ID:
        print("[TELEGRAM] ERROR: Chat ID missing!")
        print("  Fix: Send /start to @userinfobot on Telegram to get your numeric ID")
        return

    now      = datetime.now(IST)
    date_str = now.strftime("%d %b %Y")

    caption = (
        f"Daily Market Brief - {date_str} | Pre-open Edition\n"
        f"Session: {session_label}\n"
        f"{total} news captured"
    )

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                data={
                    "chat_id": CHAT_ID,
                    "caption": caption,
                },
                files={"document": f},
                timeout=30
            )
        res = r.json()
        if res.get("ok"):
            print("[TELEGRAM] Successfully sent!")
        else:
            print(f"[TELEGRAM] Error: {res.get('description')}")
            _help(res)
    except Exception as e:
        print(f"[TELEGRAM] Failed: {e}")


def _help(res):
    desc = res.get("description", "")
    if "403" in str(res.get("error_code", "")):
        print("""
  FIX - Wrong TELEGRAM_CHAT_ID:
  1. Send /start to @userinfobot on Telegram
  2. It will give your numeric ID: 123456789
  3. Set "chat_id": "123456789" in config.json
        """)
    elif "chat not found" in desc:
        print("  FIX - Send /start to your bot on Telegram first, then run the script.")


# -- Main --------------------------------------------------
if __name__ == "__main__":
    if not os.path.exists(NEWS_FILE):
        print(f"ERROR: news.json not found! Run python scrape.py first.")
        exit(1)

    with open(NEWS_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"Loaded {len(articles)} articles from {NEWS_FILE}")

    if not articles:
        print("ERROR: news.json is empty! Run python scrape.py first.")
        exit(1)

    pdf_path, session_label = generate_pdf(articles)
    send_telegram(pdf_path, session_label, len(articles))

    # Reset news.json after sending - ready for next session
    with open(NEWS_FILE, "w") as f:
        json.dump([], f)
    print("news.json reset - ready for next session.")
    print("\nDone!")