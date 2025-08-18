# modules/web/search_and_answer.py
from __future__ import annotations
import re, requests
from typing import List, Dict, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup

try:
    import trafilatura  # optional, better extraction
except Exception:
    trafilatura = None

from googlesearch import search as gsearch  # pip install googlesearch-python
try:
    from ..ollama.ollama import humanize_search  # package run: python -m ...
except ImportError:
    # script run: python modules/google_search/search_for_answers.py
    import sys, pathlib
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))  # add .../src
    from modules.ollama.ollama import humanize_search

UA = {"User-Agent": "Mozilla/5.0 (compatible; JarvisAI/1.0)"}

def google_search(query: str, num_results: int = 6, lang: str = "en") -> List[str]:
    urls = [u for u in gsearch(query, num_results=num_results, lang=lang) if u.startswith("http")]
    seen, out = set(), []
    for u in urls:
        key = (urlparse(u).netloc, urlparse(u).path)
        if key not in seen:
            seen.add(key); out.append(u)
    return out

def _is_html(resp: requests.Response) -> bool:
    ctype = resp.headers.get("content-type", "").lower()
    return ("html" in ctype) or ctype == ""

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def fetch_page(url: str, timeout: float = 8.0) -> Tuple[str, str]:
    """Return (title, text) or ('','') on failure/non-HTML."""
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        if not _is_html(r):
            return "", ""
        html = r.text
    except Exception:
        return "", ""

    title = ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string or "").strip() if soup.title else ""
    except Exception:
        pass

    text = ""
    if trafilatura:
        try:
            text = trafilatura.extract(html, include_comments=False, url=url) or ""
        except Exception:
            text = ""
    if not text:
        try:
            soup = BeautifulSoup(html, "html.parser")
            ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
            ps = [p for p in ps if len(p.split()) > 5]
            text = "\n".join(ps[:8])
        except Exception:
            text = ""
    return _clean(title), _clean(text)

def gather_context(urls: List[str], per_source_chars: int = 1000, min_words: int = 40) -> List[Dict[str, str]]:
    ctx = []
    for u in urls:
        title, text = fetch_page(u)
        if not text or len(text.split()) < min_words:
            continue
        if len(text) > per_source_chars:
            text = text[:per_source_chars].rsplit(" ", 1)[0] + "…"
        ctx.append({"url": u, "title": title or u, "text": text})
    return ctx

def _is_topic_query(q: str) -> bool:
    q = q.lower().strip()
    return ("?" not in q) and any(t in q for t in ["news","update","latest","today","this week"])

def answer_with_search(question: str,
                       num_results: int = 6,
                       per_source_chars: int = 1000) -> Dict[str, object]:
    urls = google_search(question, num_results=num_results)
    ctx = gather_context(urls, per_source_chars=per_source_chars)
    if not ctx:
        return {"answer": "No suitable sources found.", "sources": []}

    bundle = "\n\n".join(f"[{i+1}] {c['title']} — {c['url']}\n{c['text']}"
                         for i, c in enumerate(ctx[:5]))

    answer = humanize_search(question, bundle, is_topic=_is_topic_query(question))

    sources = [{"n": i+1, "title": c["title"], "url": c["url"]} for i, c in enumerate(ctx[:5])]
    return {"answer": answer, "sources": sources}

# CLI demo
if __name__ == "__main__":
    q = "UK primeminister 2025"
    res = answer_with_search(q)
    print(res["answer"])
