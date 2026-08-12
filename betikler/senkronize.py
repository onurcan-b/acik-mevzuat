#!/usr/bin/env python3
"""Türkiye kanunlarını doğrudan Adalet Bakanlığı UYAP Mevzuat kaynaklarından senkronize eder."""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import random
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "kanunlar"
INDEX_PATH = ROOT / "indeks.json"
BASE_URL = "https://bedesten.adalet.gov.tr/mevzuat"
PUBLIC_SITE = "https://mevzuat.adalet.gov.tr"
APP_NAME = "UyapMevzuat"
SUPPORTED_TYPES = ("KANUN", "MULGA", "KHK", "CB_KARARNAME", "TUZUK", "YONETMELIK", "CB_YONETMELIK", "CB_KARAR", "CB_GENELGE", "KKY", "UY", "TEBLIGLER")
USER_AGENT = "acik-mevzuat/3.1 (+https://github.com/onurcan-b/acik-mevzuat)"
POST_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "AdaletApplicationName": APP_NAME,
    "Origin": PUBLIC_SITE,
    "Referer": f"{PUBLIC_SITE}/",
    "User-Agent": USER_AGENT,
    "Connection": "close",
}
GET_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/pdf", "Referer": f"{PUBLIC_SITE}/", "User-Agent": USER_AGENT, "Connection": "close"}
LAST_REQUEST_AT = 0.0
REQUEST_DELAY_SECONDS = 0.30

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class ApiError(RuntimeError):
    pass


def _retry_after_seconds(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
            return max(0.0, (retry_at - datetime.now(retry_at.tzinfo)).total_seconds())
        except Exception:
            return None


def _pace_requests() -> None:
    global LAST_REQUEST_AT
    elapsed = time.monotonic() - LAST_REQUEST_AT
    if elapsed < REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS - elapsed)


def _retry_sleep(attempt: int, response: requests.Response | None = None) -> None:
    retry_after = _retry_after_seconds(response) if response is not None else None
    delay = retry_after if retry_after is not None else min(2 ** (attempt + 1), 60)
    time.sleep(delay + random.uniform(0.2, 1.0))


def _post(endpoint: str, data: dict[str, Any], *, paging: bool = False) -> dict[str, Any]:
    global LAST_REQUEST_AT
    payload: dict[str, Any] = {"data": data, "applicationName": APP_NAME}
    if paging:
        payload["paging"] = True
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            _pace_requests()
            response = requests.post(f"{BASE_URL}{endpoint}", headers=POST_HEADERS, json=payload, timeout=(20, 90))
            LAST_REQUEST_AT = time.monotonic()
            if response.status_code == 429:
                _retry_sleep(attempt, response)
                continue
            if response.status_code >= 500:
                raise ApiError(f"HTTP {response.status_code}")
            response.raise_for_status()
            body = response.json()
            metadata = body.get("metadata") or {}
            if metadata.get("FMTY") not in (None, "SUCCESS"):
                raise ApiError(metadata.get("FMTE") or f"API hatası: {metadata}")
            return body
        except (requests.RequestException, ValueError, ApiError) as exc:
            last_error = exc
            if attempt == 7:
                break
            _retry_sleep(attempt)
    raise ApiError(f"{endpoint} başarısız: {last_error}")


def _get(url: str, label: str) -> requests.Response:
    global LAST_REQUEST_AT
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            _pace_requests()
            response = requests.get(url, headers=GET_HEADERS, timeout=(20, 120))
            LAST_REQUEST_AT = time.monotonic()
            if response.status_code == 429:
                _retry_sleep(attempt, response)
                continue
            if response.status_code >= 500:
                raise ApiError(f"HTTP {response.status_code}")
            response.raise_for_status()
            if len(response.content) < 100:
                raise ApiError("beklenenden kısa yanıt")
            return response
        except (requests.RequestException, ApiError) as exc:
            last_error = exc
            if attempt == 7:
                break
            print(f"Resmî kaynak hatası ({label}): {exc}; tekrar deneniyor.", file=sys.stderr)
            _retry_sleep(attempt)
    raise ApiError(f"{url} başarısız: {last_error}")


def _list_type(mevzuat_type: str, page_size: int = 20) -> list[dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    page = 1
    total = 0
    while True:
        body = _post("/searchDocuments", {
            "pageSize": page_size,
            "pageNumber": page,
            "sortFields": ["RESMI_GAZETE_TARIHI"],
            "sortDirection": "desc",
            "mevzuatTurList": [mevzuat_type],
        }, paging=True)
        data = body.get("data") or {}
        items = data.get("mevzuatList") or []
        total = int(data.get("total") or total or 0)
        if not items:
            break
        for item in items:
            mevzuat_id = str(item.get("mevzuatId") or "").strip()
            if mevzuat_id:
                item["_source_type"] = mevzuat_type
                docs[mevzuat_id] = item
        print(f"Katalog {mevzuat_type}: {len(docs)}/{total or '?'}", flush=True)
        if total and len(docs) >= total:
            break
        page += 1
    if total and len(docs) != total:
        raise ApiError(f"{mevzuat_type} katalog eksik: {len(docs)}/{total}")
    return list(docs.values())


def list_documents(types: list[str]) -> list[dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for mevzuat_type in types:
        for item in _list_type(mevzuat_type):
            docs[str(item["mevzuatId"])] = item
    return sorted(docs.values(), key=lambda d: (str(d.get("_source_type") or ""), str(d.get("mevzuatNo") or ""), str(d.get("mevzuatAdi") or ""), str(d.get("mevzuatId") or "")))


def normalize_document(content: str, mime_type: str = "text/html") -> str:
    if "html" in mime_type.lower() or re.search(r"<(?:html|body|p|div|table|br)\b", content, re.I):
        soup = BeautifulSoup(content, "html.parser")
        for node in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "button", "input"]):
            node.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for tag in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th"]):
            tag.insert_before("\n")
            tag.insert_after("\n")
        content = soup.get_text("\n")
    content = html.unescape(content).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    blank = False
    for raw in content.splitlines():
        line = re.sub(r"[ \t\u00a0]+", " ", raw).strip()
        if not line:
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    return "\n".join(lines).strip() + "\n"


def extract_public_document(page_html: str, law_number: str, title: str) -> str:
    text = normalize_document(page_html, "text/html")
    starts: list[int] = []
    for pattern in (r"Kanun\s+Numarası\s*[:：]", r"Kanun\s+No\.?\s*[:：]", re.escape(title)):
        match = re.search(pattern, text, re.I)
        if match:
            starts.append(match.start())
    if starts:
        text = text[min(starts):]
    if law_number and law_number not in text[:10000]:
        raise ApiError(f"kanun numarası sayfada doğrulanamadı: {law_number}")
    if len(text) < 120:
        raise ApiError("belge metni beklenenden kısa")
    return text.strip() + "\n"


def _catalog_url(item: dict[str, Any]) -> str | None:
    raw = str(item.get("url") or "").strip()
    if not raw:
        return None
    return raw if raw.startswith(("http://", "https://")) else urljoin(f"{PUBLIC_SITE}/", raw)


def _pdf_text(blob: bytes) -> str:
    reader = PdfReader(io.BytesIO(blob))
    text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    if len(text.strip()) < 80:
        raise ApiError("PDF metni çıkarılamadı")
    return normalize_document(text, "text/plain")


def get_document_text(item: dict[str, Any]) -> tuple[str, str]:
    mevzuat_id = str(item["mevzuatId"])
    law_number = str(item.get("mevzuatNo") or "").strip()
    title = str(item.get("mevzuatAdi") or "İsimsiz mevzuat").strip()
    errors: list[str] = []
    catalog_url = _catalog_url(item)
    if catalog_url:
        try:
            response = _get(catalog_url, f"{mevzuat_id} katalog URL")
            ctype = response.headers.get("Content-Type", "").lower()
            if "pdf" in ctype or response.content.startswith(b"%PDF"):
                return _pdf_text(response.content), catalog_url
            text = normalize_document(response.text, ctype or "text/html")
            if len(text) >= 120:
                return text, catalog_url
            raise ApiError("katalog URL içeriği kısa")
        except Exception as exc:
            errors.append(f"katalog URL: {exc}")
    page_url = f"{PUBLIC_SITE}/mevzuat/{mevzuat_id}"
    try:
        response = _get(page_url, f"{mevzuat_id} HTML")
        return extract_public_document(response.text, law_number, title), page_url
    except Exception as exc:
        errors.append(f"HTML: {exc}")
    raise ApiError("; ".join(errors))


def slugify(value: str) -> str:
    value = value.translate(str.maketrans({"ç":"c","Ç":"c","ğ":"g","Ğ":"g","ı":"i","İ":"i","ö":"o","Ö":"o","ş":"s","Ş":"s","ü":"u","Ü":"u"}))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "isimsiz"


def directory_slug(prefix: str, title: str, mevzuat_id: str, max_length: int = 150) -> str:
    prefix_slug, title_slug = slugify(prefix), slugify(title)
    base = f"{prefix_slug}-{title_slug}"
    if len(base) <= max_length:
        return base
    suffix = f"-{mevzuat_id[:8]}"
    available = max(24, max_length - len(prefix_slug) - len(suffix) - 2)
    return f"{prefix_slug}-{title_slug[:available].rstrip('-')}{suffix}"


def normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def extract_accepted_date(text: str) -> str | None:
    match = re.search(r"Kabul\s+[Tt]arihi\s*[:：]?\s*(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_existing() -> tuple[dict[str, Path], dict[str, Path], dict[Path, dict[str, Any]]]:
    by_id: dict[str, Path] = {}
    by_number: dict[str, Path] = {}
    metadata_by_dir: dict[Path, dict[str, Any]] = {}
    for path in sorted(LAWS_DIR.glob("*/ustveri.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        directory = path.parent
        metadata_by_dir[directory] = data
        source_id = str(data.get("source_mevzuat_id") or "").strip()
        law_number = str(data.get("law_number") or "").strip()
        if source_id.isdigit():
            by_id[source_id] = directory
        if law_number:
            by_number.setdefault(law_number, directory)
    return by_id, by_number, metadata_by_dir


def assign_targets(documents: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Path, dict[str, Any]]]:
    by_id, by_number, metadata_by_dir = load_existing()
    used: set[Path] = set()
    tasks = []
    for item in documents:
        mevzuat_id = str(item["mevzuatId"])
        law_number = str(item.get("mevzuatNo") or "").strip()
        title = str(item.get("mevzuatAdi") or "İsimsiz mevzuat").strip()
        directory = by_id.get(mevzuat_id) or (by_number.get(law_number) if law_number else None)
        if directory is None:
            directory = LAWS_DIR / directory_slug(law_number or mevzuat_id[:8], title, mevzuat_id)
        if directory in used:
            directory = LAWS_DIR / directory_slug(law_number or mevzuat_id[:8], title, f"{mevzuat_id}-{hashlib.sha1(title.encode()).hexdigest()[:8]}")
        used.add(directory)
        tasks.append((item, directory, metadata_by_dir.get(directory, {})))
    return tasks


def build_metadata(item: dict[str, Any], directory: Path, previous: dict[str, Any], text: str, source_url: str) -> dict[str, Any]:
    source_type = str(item.get("_source_type") or "KANUN")
    return {
        "law_number": str(item.get("mevzuatNo") or "").strip(),
        "title": str(item.get("mevzuatAdi") or "İsimsiz mevzuat").strip(),
        "slug": directory.name,
        "accepted_date": extract_accepted_date(text) or previous.get("accepted_date"),
        "effective_status": "repealed" if source_type == "MULGA" else "in_force",
        "official_gazette": {
            "date": normalize_date(item.get("resmiGazeteTarihi")),
            "number": str(item.get("resmiGazeteSayisi")).strip() if item.get("resmiGazeteSayisi") not in (None, "") else None,
        },
        "source_url": source_url,
        "language": "tr",
        "tags": previous.get("tags") or [],
        "source_mevzuat_id": str(item["mevzuatId"]),
        "source_type": source_type,
        "content_sha256": content_hash(text),
        "retrieval_api": f"{BASE_URL}/searchDocuments",
    }


def render_markdown(metadata: dict[str, Any], text: str) -> str:
    gazette = metadata["official_gazette"]
    return "\n".join([
        f"# {metadata['title']} (No. {metadata['law_number'] or '—'})", "",
        f"> Resmî kaynak: {metadata['source_url']}",
        f"> Resmî Gazete: {gazette.get('date') or 'bilinmiyor'} / {gazette.get('number') or 'bilinmiyor'}",
        f"> UYAP Mevzuat kimliği: {metadata['source_mevzuat_id']}", "", "---", "", text.rstrip(), "",
    ])


def write_text_if_changed(path: Path, text: str) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--types", default="KANUN,MULGA")
    parser.add_argument("--delay", type=float, default=0.30)
    parser.add_argument("--max-errors", type=int, default=0)
    parser.add_argument("--min-documents", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    global REQUEST_DELAY_SECONDS
    REQUEST_DELAY_SECONDS = max(0.15, args.delay)
    types = [x.strip().upper() for x in args.types.split(",") if x.strip()]
    unknown = sorted(set(types) - set(SUPPORTED_TYPES))
    if unknown:
        parser.error(f"Desteklenmeyen türler: {', '.join(unknown)}")

    LAWS_DIR.mkdir(parents=True, exist_ok=True)
    documents = list_documents(types)
    if len(documents) < args.min_documents:
        raise SystemExit(f"Güvenlik kontrolü: {len(documents)} belge döndü; en az {args.min_documents} bekleniyordu.")

    tasks = assign_targets(documents)
    desired_dirs: set[Path] = set()
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    changed = 0
    for i, (item, directory, previous) in enumerate(tasks, 1):
        desired_dirs.add(directory)
        try:
            text, fetched_url = get_document_text(item)
            metadata = build_metadata(item, directory, previous, text, fetched_url)
        except Exception as exc:
            error = f"{item.get('mevzuatId')} {item.get('mevzuatAdi')}: {exc}"
            errors.append(error)
            print(f"HATA [{i}/{len(tasks)}] {error}", file=sys.stderr, flush=True)
            continue
        if write_text_if_changed(directory / "ustveri.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"):
            changed += 1
        if write_text_if_changed(directory / "metin.md", render_markdown(metadata, text)):
            changed += 1
        entries.append({"law_number": metadata["law_number"], "title": metadata["title"], "type": metadata["source_type"], "path": directory.relative_to(ROOT).as_posix(), "source_mevzuat_id": metadata["source_mevzuat_id"], "content_sha256": metadata["content_sha256"]})
        print(f"OK [{i}/{len(tasks)}] {directory.name}", flush=True)

    if len(errors) > args.max_errors:
        for error in errors[:30]:
            print(f"- {error}", file=sys.stderr)
        print(f"Eksik snapshot: {len(errors)} hata; commit edilmeyecek.", file=sys.stderr)
        return 1

    entries.sort(key=lambda x: (x["type"], x["law_number"], x["title"], x["source_mevzuat_id"]))
    index = {"source": PUBLIC_SITE, "catalog_api": f"{BASE_URL}/searchDocuments", "types": types, "documents_total": len(entries), "documents": entries}
    if write_text_if_changed(INDEX_PATH, json.dumps(index, ensure_ascii=False, indent=2) + "\n"):
        changed += 1
    if not errors:
        for directory in sorted(p for p in LAWS_DIR.iterdir() if p.is_dir()):
            if directory not in desired_dirs:
                shutil.rmtree(directory)
                changed += 1
    print(f"Değişen dosya/dizin sayısı: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
