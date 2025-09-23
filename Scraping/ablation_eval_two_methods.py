# scrape_ablation_two_methods.py
import re, time, json, asyncio
from pathlib import Path
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from playwright.async_api import async_playwright
import pandas as pd

DATA = Path("data"); DATA.mkdir(exist_ok=True)
URLS_TXT = DATA / "urls.txt"
OUT_REQ  = DATA / "scraped_data_requests.json"
OUT_PW   = DATA / "scraped_data_playwright.json"
ABL_SUM  = DATA / "ingestion_ablation_summary.csv"
ABL_PER  = DATA / "ingestion_ablation_perurl.csv"

HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_TIMEOUT = 25
PW_TIMEOUT_MS = 60000

# ---------- shared cleaner (keep ablation fair) ----------
def parse_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for el in soup(["script","style","noscript","svg","header","footer","nav"]):
        el.decompose()
    # optional: drop common hero-ish sections if present
    def drop_by_heading(needle: str):
        h = soup.find(lambda tag: tag.name in ["h1","h2","h3"] and needle in (tag.get_text() or ""))
        if h:
            p = h.find_parent()
            if p: p.decompose()
    for key in ["Our Products", "Why JioPay?", "Digital payment acceptance made easy"]:
        drop_by_heading(key)
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()

def word_tokens(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+", (text or "").lower())

BOILER = set("""
jio jiopay business products partner program contact us about us privacy policy terms conditions grievance redressal policy
merchant onboarding kyc aml billpay point of sale upi hub biller centre payment gateway business app explore help center
""".split())

def noise_ratio(tokens: List[str]) -> float:
    if not tokens: return 1.0
    return sum(1 for t in tokens if t in BOILER) / max(1, len(tokens))

# ---------- pipeline A: requests+bs4 ----------
def run_requests(urls: List[str]) -> List[Dict]:
    rows = []
    t0 = time.time()
    for u in tqdm(urls, desc="Requests+BS4"):
        try:
            r = requests.get(u, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            text = parse_text_from_html(r.text)
        except Exception:
            text = ""
        rows.append({"url": u, "text": text})
    elapsed = time.time() - t0
    OUT_REQ.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Requests pipeline -> {OUT_REQ} | elapsed {elapsed:.2f}s")
    return rows, elapsed

# ---------- pipeline B: headless (Playwright) ----------
async def run_playwright_async(urls: List[str]) -> (List[Dict], float):
    rows = []
    t0 = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0")
        for u in tqdm(urls, desc="Playwright"):
            try:
                await page.goto(u, wait_until="networkidle", timeout=PW_TIMEOUT_MS)
                # gentle scroll for lazy content
                try:
                    await page.evaluate("""async () => {
                      let h=document.body.scrollHeight, y=0;
                      while (y<h){ y+=Math.max(300, Math.floor(window.innerHeight*0.9));
                        window.scrollTo(0,y); await new Promise(r=>setTimeout(r,80));
                        h=document.body.scrollHeight;}
                    }""")
                except: pass
                html = await page.content()
                text = parse_text_from_html(html)
            except Exception:
                text = ""
            rows.append({"url": u, "text": text})
        await browser.close()
    elapsed = time.time() - t0
    OUT_PW.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Playwright pipeline -> {OUT_PW} | elapsed {elapsed:.2f}s")
    return rows, elapsed

def evaluate(name: str, rows: List[Dict], elapsed_sec: float, total_attempted: int) -> (Dict, List[Dict]):
    per = []
    success = 0
    total_tokens = 0
    noise_vals = []
    for r in rows:
        u, text = r["url"], r.get("text","")
        toks = word_tokens(text)
        nz = noise_ratio(toks) if toks else None
        if text: 
            success += 1
            total_tokens += len(toks)
            if nz is not None: noise_vals.append(nz)
        per.append({
            "pipeline": name, "url": u,
            "has_text": int(bool(text)),
            "chars": len(text),
            "tokens": len(toks),
            "noise_ratio": round(nz, 4) if nz is not None else None
        })
    failures = total_attempted - success
    throughput = success / max(1e-9, elapsed_sec)  # pages/sec
    summary = {
        "Pipeline": name,
        "#Pages": success,                     # pages with non-empty text
        "#Tokens": total_tokens,               # sum of tokens across successes
        "Noise %": round(100*(sum(noise_vals)/len(noise_vals)) if noise_vals else 0.0, 2),
        "Throughput": round(throughput, 2),    # pages per second
        "Failures (%)": round(100*failures/max(1,total_attempted), 2),
    }
    return summary, per

def main():
    if not URLS_TXT.exists():
        raise SystemExit("Missing data/urls.txt")

    urls = [u.strip() for u in URLS_TXT.read_text(encoding="utf-8").splitlines() if u.strip()]
    total = len(urls)
    print(f"Evaluating {total} URLs")

    req_rows, req_elapsed = run_requests(urls)
    pw_rows,  pw_elapsed  = asyncio.run(run_playwright_async(urls))

    req_summary, req_per = evaluate("BS4 (requests)", req_rows, req_elapsed, total)
    pw_summary,  pw_per  = evaluate("Headless (Playwright)", pw_rows, pw_elapsed, total)

    # save tables
    pd.DataFrame([req_summary, pw_summary]).to_csv(ABL_SUM, index=False)
    pd.DataFrame(req_per + pw_per).to_csv(ABL_PER, index=False)

    print("\n=== Ingestion/Scraper Ablation (summary) ===")
    print(pd.DataFrame([req_summary, pw_summary]).to_string(index=False))
    print(f"\nWrote summary -> {ABL_SUM}")
    print(f"Wrote per-URL -> {ABL_PER}")

if __name__ == "__main__":
    main()
