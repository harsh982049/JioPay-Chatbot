# --- Structural chunking (HTML) + Ablation update ---
# -------------------- imports & setup --------------------
import os, re, json, time, math, statistics
from typing import List, Dict, Tuple
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tqdm import tqdm

# sentence/paragraph + similarity merges
# import nltk
# try:
#     nltk.data.find("tokenizers/punkt")
# except LookupError:
#     nltk.download("punkt", quiet=True)
from nltk.tokenize import sent_tokenize

from transformers import AutoTokenizer
import pandas as pd

# light-weight similarity for semantic merges
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Gemini (LLM-based chunking)
import google.generativeai as genai

# Playwright (for structural HTML fallback on SPA)
from playwright.sync_api import sync_playwright

from pathlib import Path

DATA = Path(r"C:\\Users\\harsh\\OneDrive\\Desktop\\LLM Assignment 2\\Chunking")
SECTIONS_JSON = Path(r"C:\\Users\\harsh\\OneDrive\\Desktop\\LLM Assignment 2\\Scraping\\data\\jiopay_sections.json")
OUT_DIR = Path(r"C:\\Users\\harsh\\OneDrive\\Desktop\\LLM Assignment 2\\Chunking\\chunks")
ABLATION_CSV = Path(r"C:\\Users\\harsh\\OneDrive\\Desktop\\LLM Assignment 2\\Chunking\\chunking_ablation.csv")

tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")

def tok_count(text: str) -> int:
    return len(tokenizer.encode(text or "", add_special_tokens=False))

# ---------- HTML fetchers ----------
def _looks_like_spa_shell(html: str) -> bool:
    if not html:
        return True
    # quick heuristic: very few headings or "enable javascript"
    soup = BeautifulSoup(html, "lxml")
    head_cnt = len(soup.find_all(["h1","h2","h3"]))
    txt_head = " ".join(soup.stripped_strings)[:600].lower()
    return ("enable javascript" in txt_head) or (head_cnt == 0)

def fetch_html_requests(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=25)
        r.raise_for_status()
        return r.text
    except Exception:
        return ""

def fetch_html_playwright(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("Playwright not available:", e)
        return ""
    html = ""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0")
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            try:
                page.evaluate("""async () => {
                  let h=document.body.scrollHeight, y=0;
                  while (y<h){ y+=Math.max(300, Math.floor(window.innerHeight*0.9));
                    window.scrollTo(0,y); await new Promise(r=>setTimeout(r,80));
                    h=document.body.scrollHeight;}
                }""")
            except:
                pass
            html = page.content()
        except Exception:
            html = ""
        finally:
            page.close()
            browser.close()
    return html

def fetch_structural_html(url: str) -> str:
    html = fetch_html_requests(url)
    if _looks_like_spa_shell(html):
        html = fetch_html_playwright(url)
    return html or ""

# ---------- Structural chunker (preserve hierarchy) ----------
def structural_chunks_from_html(html: str) -> List[str]:
    """
    Produce chunks with heading context:
    "H1 > H2 > H3\nparagraph/list block"
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    for el in soup(["script","style","noscript","svg","header","footer","nav"]):
        el.decompose()

    elements = soup.find_all(["h1","h2","h3","p","li"], recursive=True)
    h = {1: None, 2: None, 3: None}
    buf, out = [], []

    def flush():
        nonlocal buf
        if not buf:
            return
        heading_path = " > ".join([x for x in [h[1], h[2], h[3]] if x])
        prefix = (heading_path + "\n") if heading_path else ""
        chunk = (prefix + " ".join(buf)).strip()
        if chunk:
            out.append(chunk)
        buf = []

    for el in elements:
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name in ("h1","h2","h3"):
            flush()
            lvl = int(el.name[1])
            h[lvl] = txt
            for k in range(lvl+1, 4):
                h[k] = None
        else:
            buf.append(txt)
    flush()
    # remove empty/tiny
    out = [c for c in out if tok_count(c) > 0]
    return out

# ---------- Run structural chunking over jiopay_sections.json ----------
cfg_name = "structural_html"
rows = []
t0 = time.time()

docs = json.loads(SECTIONS_JSON.read_text(encoding="utf-8"))
for d in docs:
    url = d.get("url","")
    section = d.get("section","")
    if not url:
        continue
    html = fetch_structural_html(url)
    chunks = structural_chunks_from_html(html)
    for ch in chunks:
        rows.append({
            "strategy": "structural",
            "config": cfg_name,
            "url": url,
            "section": section,
            "text": ch,
            "tokens": tok_count(ch)
        })

elapsed = round(time.time() - t0, 2)

# Save chunks
out_jsonl = OUT_DIR / f"chunks_{cfg_name}.jsonl"
out_jsonl.parent.mkdir(parents=True, exist_ok=True)
with out_jsonl.open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# Compute ablation row
if rows:
    toks = [r["tokens"] for r in rows]
    ablation_row = {
        "strategy": "structural",
        "config": cfg_name,
        "#chunks": len(rows),
        "tokens_total": int(sum(toks)),
        "avg_tokens": round(sum(toks)/len(toks), 2),
        "std_tokens": round(statistics.pstdev(toks), 2) if len(toks) > 1 else 0.0,
        "time_sec": elapsed,
        "redundancy_pct": 0.0
    }
else:
    ablation_row = {
        "strategy": "structural",
        "config": cfg_name,
        "#chunks": 0,
        "tokens_total": 0,
        "avg_tokens": 0.0,
        "std_tokens": 0.0,
        "time_sec": elapsed,
        "redundancy_pct": 0.0
    }

# Update/replace row in ablation CSV
if ABLATION_CSV.exists():
    df = pd.read_csv(ABLATION_CSV)
    # drop prior structural row(s)
    df = df[~((df["strategy"]=="structural") & (df["config"]==cfg_name))].copy()
    df = pd.concat([df, pd.DataFrame([ablation_row])], ignore_index=True)
else:
    df = pd.DataFrame([ablation_row])

df.to_csv(ABLATION_CSV, index=False)

print(f"Structural chunks written -> {out_jsonl}")
print("Ablation row:")
print(pd.DataFrame([ablation_row]))
print(f"Ablation CSV updated -> {ABLATION_CSV}")
