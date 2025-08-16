import ollama
import datetime
from urllib.parse import urlparse
import re

def humanize_search(question: str, bundle: str, is_topic: bool) -> str:
    today = datetime.datetime.now().strftime("%B %d, %Y")

    # --- helpers ---
    SEPS = (" — ", " – ", " - ", " | ", " :: ")

    def _brand_from_title(title: str) -> str | None:
        if not title:
            return None
        for sep in SEPS:
            if sep in title:
                tail = title.rsplit(sep, 1)[-1].strip()
                if 2 <= len(tail) <= 60:
                    return tail
        return None

    def _brand_from_url(url: str) -> str:
        host = urlparse(url).netloc.lower()
        host = re.sub(r"^www\.", "", host)
        parts = host.split(".")
        # use second-level domain as a readable fallback
        sld = parts[-2] if len(parts) >= 2 else parts[0]
        return sld.replace("-", " ").title()

    # parse [n] lines in bundle → {n: site_name}
    site_map: dict[int, str] = {}
    for line in bundle.splitlines():
        m = re.match(r"\[(\d+)]\s+(.*?)\s+—\s+(https?://\S+)", line)
        if m:
            n_str, title, url = m.groups()
            n = int(n_str)
            brand = _brand_from_title(title) or _brand_from_url(url)
            site_map[n] = brand

    sys = (
        f"You are a real-time assistant. The current date is {today}. "
        "Use the provided sources as up-to-date context. "
        "If reasoning is needed (e.g., election cycles, term lengths), combine sources with general world knowledge. "
        "Always give the most likely answer and keep it concise. "
        if not is_topic else
        f"You are a real-time assistant. The current date is {today}. "
        "Summarize the most recent information into 3–5 bullet points. "
        "One sentence per bullet. Cite sources website name"
    )

    user = (
        f"Topic: {question}\n\nSources:\n{bundle}\n\nSummarize now."
        if is_topic else
        f"Question: {question}\n\nContext with ids:\n{bundle}\n\nAnswer directly."
    )

    r = ollama.chat(
        model="llama3.2:3b-instruct-q4_K_M",
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": user}
        ],
        options={"num_ctx": 4096}
    )
    answer = r["message"]["content"].strip()

    # Replace [n] with site names (leave brackets out)
    def _replace_cite(match: re.Match) -> str:
        n = int(match.group(1))
        return site_map.get(n, f"source {n}")

    answer = re.sub(r"\[(\d+)\]", _replace_cite, answer)

    # For non-topic answers, prepend "According to X and Y, ..."
    if not is_topic:
        # first two unique site names in numeric order
        unique_sites = []
        for n in sorted(site_map.keys()):
            name = site_map[n]
            if name not in unique_sites:
                unique_sites.append(name)
            if len(unique_sites) == 2:
                break
        if unique_sites:
            if len(unique_sites) == 1:
                prefix = f"According to {unique_sites[0]}, "
            else:
                prefix = f"According to {unique_sites[0]} and {unique_sites[1]}, "
            # avoid double "According to" if model added one
            if not answer.lower().startswith("according to"):
                answer = prefix + answer

    return answer
