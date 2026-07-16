"""Scrapes configured web sources and subpages, returning normalized documents."""
import hashlib
import os
from urllib.parse import urljoin, urlparse
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

KEYWORDS = [
    "admission", "academic", "program", "tuition", "fee", "waiver",
    "faculty", "department", "undergraduate", "postgraduate", "graduate",
    "requirement", "scholarship", "notice", "contact", "about", "degree"
]


def read_source_list(path: str) -> list[str]:
    if not os.path.isfile(path):
        print(f"[web_loader] source list not found, skipping web scraping: {path}")
        return []

    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",") if p.strip()]
            for part in parts:
                part = part.replace(" ", "")
                if not part.startswith("http://") and not part.startswith("https://"):
                    part = "https://" + part
                urls.append(part)
    return urls


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_relevant_sublinks(html: str, base_url: str, max_sublinks: int = 3) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc
    found_links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc == base_domain and parsed.scheme in ["http", "https"]:
            path_lower = parsed.path.lower()
            text_lower = a.text.lower()
            if any(kw in path_lower or kw in text_lower for kw in KEYWORDS):
                clean_link = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if clean_link != base_url and not clean_link.endswith((".pdf", ".jpg", ".png", ".zip", ".docx")):
                    found_links.add(clean_link)
                    if len(found_links) >= max_sublinks:
                        break

    return list(found_links)


def load_web_sources(urls: list[str], max_pages_per_domain: int = 3):
    visited_urls = set()

    for idx, seed_url in enumerate(urls, 1):
        print(f"[web_loader] ({idx}/{len(urls)}) Crawling domain: {seed_url}")
        urls_to_crawl = [seed_url]
        pages_crawled_for_domain = 0

        while urls_to_crawl and pages_crawled_for_domain < max_pages_per_domain:
            url = urls_to_crawl.pop(0)
            if url in visited_urls:
                continue
            visited_urls.add(url)

            try:
                resp = requests.get(url, headers=HEADERS, timeout=8, verify=False)
                resp.raise_for_status()
            except Exception as e:
                if url.startswith("https://"):
                    http_url = "http://" + url[8:]
                    try:
                        resp = requests.get(http_url, headers=HEADERS, timeout=8)
                        resp.raise_for_status()
                        url = http_url
                    except Exception as e2:
                        print(f"[web_loader] failed to fetch {url}: {e2}")
                        continue
                else:
                    print(f"[web_loader] failed to fetch {url}: {e}")
                    continue

            pages_crawled_for_domain += 1
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else url
            raw_text = _clean_text(resp.text)

            if len(raw_text) > 100:
                content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
                yield {
                    "source_type": "web",
                    "source_ref": url,
                    "title": title,
                    "raw_text": raw_text,
                    "content_hash": content_hash,
                }

            if url == seed_url and pages_crawled_for_domain < max_pages_per_domain:
                sublinks = _extract_relevant_sublinks(resp.text, url, max_sublinks=max_pages_per_domain - 1)
                for sl in sublinks:
                    if sl not in visited_urls:
                        urls_to_crawl.append(sl)

