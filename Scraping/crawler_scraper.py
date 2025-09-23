import asyncio, json, re
from pathlib import Path
from hashlib import md5
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

START_URL = "https://www.jiopay.com/business"
OUT_DIR = Path("data"); OUT_DIR.mkdir(exist_ok=True)
OUT_JSON = OUT_DIR / "jiopay_sections.json"

# Sections visible in your screenshot – click by text:
SECTION_LABELS = [
    # General
    "About Us", "Help Center", "Investor Relations", "Complaint Resolution", "JioPay Business Partner Program",
    # Products
    "Payment Gateway", "Point of Sale", "UPI Hub", "Biller Centre", "JioPay Business App",
    # Legal (these may open new routes; we still handle them)
    "Privacy Policy", "Terms & Conditions", "Grievance Redressal Policy",
    "Merchant Onboarding & KYC-AML Policy", "BillPay Terms & Conditions",
]

def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script","style","noscript","svg","nav","header","footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()

async def expand_all_faqs(page):
    """
    Expand accordion-style FAQs the site uses (div[tabindex='0'] + chevron).
    Then return a list of {"question","answer"}.
    """
    faqs = []
    try:
        # Click all toggle chevrons if present
        toggles = await page.query_selector_all("div[tabindex='0']")
        for t in toggles:
            try:
                chev = await t.query_selector("div.css-146c3p1.r-kb43wt")
                if chev:
                    await chev.click()
                    await page.wait_for_timeout(100)
            except:
                pass

        # Extract Q/A
        toggles = await page.query_selector_all("div[tabindex='0']")
        for t in toggles:
            try:
                qel = await t.query_selector("div.css-146c3p1.r-op4f77")
                q = (await qel.inner_text()).strip() if qel else ""
                ans = await page.evaluate(
                    """(el) => {
                        const w = el.parentElement?.parentElement;
                        if (!w) return "";
                        const a = w.querySelector("div[data-testid='ViewTestId'], div.css-146c3p1.r-1xt3ije");
                        return a ? a.innerText : "";
                    }""",
                    t
                )
                if q and ans:
                    faqs.append({"question": q, "answer": ans.strip()})
            except:
                continue
    except:
        pass
    return faqs

async def get_body_hash(page) -> str:
    try:
        txt = await page.evaluate("() => document.body.innerText || ''")
        return md5(txt.encode("utf-8", errors="ignore")).hexdigest()
    except:
        return ""

async def click_by_text(page, text: str) -> bool:
    """
    Click an element showing the exact visible text (div-based nav).
    Tries get_by_text first, then a generic query.
    Returns True if we think the click was delivered.
    """
    try:
        loc = page.get_by_text(text, exact=True).first
        await loc.scroll_into_view_if_needed(timeout=1000)
        try:
            await loc.click(timeout=800)
        except:
            # fallback: JS click
            await page.evaluate("(el) => el.click()", await loc.element_handle())
        await page.wait_for_timeout(200)
        return True
    except:
        # fallback query for divs with dir="auto"
        try:
            locs = await page.query_selector_all("div[dir='auto'], span[dir='auto'], div[role='button']")
            for el in locs:
                try:
                    t = (await el.inner_text()).strip()
                    if t == text:
                        await el.scroll_into_view_if_needed(timeout=1000)
                        try:
                            await el.click(timeout=800)
                        except:
                            await page.evaluate("(el)=>el.click()", el)
                        await page.wait_for_timeout(200)
                        return True
                except:
                    continue
        except:
            pass
    return False

async def scrape_sections():
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0")
        await page.goto(START_URL, wait_until="networkidle", timeout=60000)

        # Scroll fully to ensure bottom grid is rendered
        try:
            await page.evaluate("""async () => {
              let h = document.body.scrollHeight, y=0;
              while (y < h) {
                y += Math.max(400, Math.floor(window.innerHeight*0.9));
                window.scrollTo(0,y);
                await new Promise(r=>setTimeout(r,90));
                h = document.body.scrollHeight;
              }
            }""")
        except:
            pass

        # Capture the default/landing state
        html0 = await page.content()
        results.append({
            "section": "Landing",
            "url": START_URL,
            "text": clean_text(html0),
            "faqs": []
        })

        # Visit each bottom-tile section by clicking its DIV text
        for label in SECTION_LABELS:
            before_hash = await get_body_hash(page)

            clicked = await click_by_text(page, label)
            if not clicked:
                # Couldn't find/click the tile; record as skipped
                results.append({"section": label, "url": page.url, "text": "", "faqs": [], "note": "click failed"})
                continue

            # Wait for either URL change OR visible content change (hash change)
            changed = False
            try:
                await page.wait_for_function(
                    "(prev) => (document.body.innerText||'').length > 0 && prev !== (document.body.innerText||'')",
                    arg=await page.evaluate("() => document.body.innerText || ''"),
                    timeout=2500
                )
                changed = True
            except PWTimeout:
                # maybe content swaps but text hash is similar; proceed anyway
                pass

            # If this click navigated to a different route, we’re still fine
            url_now = page.url
            html = await page.content()
            text = clean_text(html)

            faqs = []
            if label.lower().strip() == "help center":
                faqs = await expand_all_faqs(page)

            results.append({
                "section": label,
                "url": url_now,
                "text": text,
                "faqs": faqs
            })

            # If route changed, best-effort go back to the main page for the next tile
            if url_now != START_URL:
                try:
                    await page.go_back(wait_until="networkidle", timeout=60000)
                except:
                    await page.goto(START_URL, wait_until="networkidle", timeout=60000)

        await browser.close()
    return results

if __name__ == "__main__":
    data = asyncio.run(scrape_sections())
    OUT_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(data)} section snapshots -> {OUT_JSON}")
