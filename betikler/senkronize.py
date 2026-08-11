#!/usr/bin/env python3
"""Adalet Bakanligi mevzuat API'sinden kanunlari senkronize eder.

Varsayilan olarak yürürlükteki ve mülga kanunlari indirir. Her çalışmada
resmi kaynaktaki tam metin yeniden hash'lenir; yalnızca gerçekten değişen
dosyalar Git diff'ine girer.

Kullanım:
    python betikler/senkronize.py
    python betikler/senkronize.py --types KANUN,MULGA --workers 4
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
PUBLIC_SITE = "https://mevzuat.adalet.gov.tr/"
APP_NAME = "UyapMevzuat"
HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "AdaletApplicationName": APP_NAME,
    "Origin": "https://mevzuat.adalet.gov.tr",
    "Referer": PUBLIC_SITE,
    "User-Agent": "acik-mevzuat/2.0 (+https://github.com/onurcan-b/acik-mevzuat)",
}
SUPPORTED_TYPES = (
    "KANUN",
    "MULGA",
    "KHK",
    "CB_KARARNAME",
    "TUZUK",
    "YONETMELIK",
    "CB_YONETMELIK",
    "CB_KARAR",
    "CB_GENELGE",
    "KKY",
    "UY",
    "TEBLIGLER",
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class ApiError(RuntimeError):
    pass


def _post(endpoint: str, data: dict[str, Any], *, paging: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"data": data, "applicationName": APP_NAME}
    if paging:
        payload["paging"] = True

    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = requests.post(
                f"{BASE_URL}{endpoint}",
                headers=HEADERS,
                json=payload,
                timeout=60,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise ApiError(f"HTTP {response.status_code}")
            response.raise_for_status()
            body = response.json()
            metadata = body.get("metadata") or {}
            if metadata.get("FMTY") not in (None, "SUCCESS"):
                raise ApiError(metadata.get("FMTE") or f"API hatası: {metadata}")
            return body
        except (requests.RequestException, ValueError, ApiError) as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(min(2 ** attempt, 12))

    raise ApiError(f"{endpoint} başarısız: {last_error}")


def _list_type(mevzuat_type: str, page_size: int = 20) -> list[dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    page = 1

    while True:
        body = _post(
            "/searchDocuments",
            {
                "pageSize": page_size,
                "pageNumber": page,
                "sortFields": ["RESMI_GAZETE_TARIHI"],
                "sortDirection": "desc",
                "mevzuatTurList": [mevzuat_type],
            },
            paging=True,
        )
        data = body.get("data") or {}
        items = data.get("mevzuatList") or []
        total = int(data.get("total") or 0)

        if not items:
            break

        for item in items:
            mevzuat_id = str(item.get("mevzuatId") or "").strip()
            if not mevzuat_id:
                continue
            item["_source_type"] = mevzuat_type
            documents[mevzuat_id] = item

        if len(documents) >= total:
            break
        page += 1

    return list(documents.values())


def list_documents(types: list[str]) -> list[dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for mevzuat_type in types:
        print(f"Liste alınıyor: {mevzuat_type}")
        for item in _list_type(mevzuat_type):
            documents[str(item["mevzuatId"])] = item
    return sorted(
        documents.values(),
        key=lambda d: (
            str(d.get("_source_type") or ""),
            str(d.get("mevzuatNo") or ""),
            str(d.get("mevzuatAdi") or ""),
        ),
    )


def _decode_document(raw: str, mime_type: str) -> str:
    try:
        blob = base64.b64decode(raw, validate=False)
    except Exception:
        blob = raw.encode("utf-8", errors="replace")

    if "pdf" in mime_type.lower() or blob.startswith(b"%PDF"):
        reader = PdfReader(io.BytesIO(blob))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)

    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return blob.decode("latin-1", errors="replace")


def get_document_text(mevzuat_id: str) -> tuple[str, str]:
    body = _post(
        "/getDocumentContent",
        {"documentType": "MEVZUAT", "id": mevzuat_id},
    )
    data = body.get("data") or {}
    raw = data.get("content") or ""
    mime_type = str(data.get("mimeType") or "text/html")
    if not raw:
        raise ApiError(f"{mevzuat_id}: boş doküman")

    decoded = _decode_document(str(raw), mime_type)
    return normalize_document(decoded, mime_type), mime_type


def normalize_document(content: str, mime_type: str = "text/html") -> str:
    if "html" in mime_type.lower() or re.search(r"<(?:html|body|p|div|table|br)\b", content, re.I):
        soup = BeautifulSoup(content, "html.parser")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for tag in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"]):
            tag.insert_before("\n")
            tag.insert_after("\n")
        content = soup.get_text("\n")

    content = html.unescape(content).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    previous_blank = False
    for raw_line in content.splitlines():
        line = re.sub(r"[ \t\u00a0]+", " ", raw_line).strip()
        if not line:
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line)
        previous_blank = False

    return "\n".join(lines).strip() + "\n"


def slugify(value: str) -> str:
    translation = str.maketrans(
        {
            "ç": "c",
            "Ç": "c",
            "ğ": "g",
            "Ğ": "g",
            "ı": "i",
            "İ": "i",
            "ö": "o",
            "Ö": "o",
            "ş": "s",
            "Ş": "s",
            "ü": "u",
            "Ü": "u",
        }
    )
    value = value.translate(translation)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "isimsiz"


def normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def extract_accepted_date(text: str) -> str | None:
    patterns = (
        r"Kabul\s+Tarihi\s*[:：]?\s*(\d{1,2})[./](\d{1,2})[./](\d{4})",
        r"Kabul\s+tarihi\s*[:：]?\s*(\d{1,2})[./](\d{1,2})[./](\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            day, month, year = map(int, match.groups())
            try:
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                return None
    return None


def source_url(item: dict[str, Any]) -> str:
    raw = str(item.get("url") or "").strip()
    if not raw:
        return PUBLIC_SITE
    if raw.startswith(("http://", "https://")):
        return raw
    return urljoin(PUBLIC_SITE, raw)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_existing() -> tuple[dict[str, Path], dict[str, Path], dict[Path, dict[str, Any]]]:
    by_id: dict[str, Path] = {}
    by_number: dict[str, Path] = {}
    metadata_by_dir: dict[Path, dict[str, Any]] = {}

    for metadata_path in sorted(LAWS_DIR.glob("*/ustveri.json")):
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        directory = metadata_path.parent
        metadata_by_dir[directory] = data
        source_id = str(data.get("source_mevzuat_id") or "").strip()
        law_number = str(data.get("law_number") or "").strip()
        if source_id:
            by_id[source_id] = directory
        if law_number:
            by_number.setdefault(law_number, directory)

    return by_id, by_number, metadata_by_dir


def assign_targets(
    documents: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], Path, dict[str, Any]]]:
    by_id, by_number, metadata_by_dir = load_existing()
    used: set[Path] = set()
    tasks: list[tuple[dict[str, Any], Path, dict[str, Any]]] = []

    for item in documents:
        mevzuat_id = str(item["mevzuatId"])
        law_number = str(item.get("mevzuatNo") or "").strip()
        title = str(item.get("mevzuatAdi") or "İsimsiz mevzuat").strip()

        directory = by_id.get(mevzuat_id) or (by_number.get(law_number) if law_number else None)
        if directory is None:
            prefix = law_number or mevzuat_id[:8]
            directory = LAWS_DIR / f"{slugify(prefix)}-{slugify(title)}"

        if directory in used:
            directory = LAWS_DIR / f"{directory.name}-{mevzuat_id[:8]}"
        used.add(directory)

        tasks.append((item, directory, metadata_by_dir.get(directory, {})))

    return tasks


def build_metadata(
    item: dict[str, Any],
    directory: Path,
    previous: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    law_number = str(item.get("mevzuatNo") or "").strip()
    title = str(item.get("mevzuatAdi") or "İsimsiz mevzuat").strip()
    source_type = str(item.get("_source_type") or "KANUN")
    accepted_date = extract_accepted_date(text) or previous.get("accepted_date")

    return {
        "law_number": law_number,
        "title": title,
        "slug": directory.name,
        "accepted_date": accepted_date,
        "effective_status": "repealed" if source_type == "MULGA" else "in_force",
        "official_gazette": {
            "date": normalize_date(item.get("resmiGazeteTarihi")),
            "number": (
                str(item.get("resmiGazeteSayisi")).strip()
                if item.get("resmiGazeteSayisi") not in (None, "")
                else None
            ),
        },
        "source_url": source_url(item),
        "language": "tr",
        "tags": previous.get("tags") or [],
        "source_mevzuat_id": str(item["mevzuatId"]),
        "source_type": source_type,
        "content_sha256": content_hash(text),
        "retrieval_api": BASE_URL,
    }


def render_markdown(metadata: dict[str, Any], text: str) -> str:
    gazette = metadata["official_gazette"]
    lines = [
        f"# {metadata['title']} (No. {metadata['law_number'] or '—'})",
        "",
        f"> Kaynak: {metadata['source_url']}",
        f"> Resmî Gazete: {gazette.get('date') or 'bilinmiyor'} / {gazette.get('number') or 'bilinmiyor'}",
        f"> Kaynak kimliği: {metadata['source_mevzuat_id']}",
        "",
        "---",
        "",
        text.rstrip(),
        "",
    ]
    return "\n".join(lines)


def write_text_if_changed(path: Path, text: str) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def sync_one(
    task: tuple[dict[str, Any], Path, dict[str, Any]],
) -> tuple[dict[str, Any], Path, dict[str, Any], str]:
    item, directory, previous = task
    text, _mime_type = get_document_text(str(item["mevzuatId"]))
    metadata = build_metadata(item, directory, previous, text)
    return item, directory, metadata, text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--types",
        default="KANUN,MULGA",
        help="Virgülle ayrılmış mevzuat türleri. Varsayılan: KANUN,MULGA",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--max-errors",
        type=int,
        default=10,
        help="Bu sayıdan fazla doküman hatasında çalışmayı başarısız say.",
    )
    args = parser.parse_args()

    types = [part.strip().upper() for part in args.types.split(",") if part.strip()]
    unknown = sorted(set(types) - set(SUPPORTED_TYPES))
    if unknown:
        parser.error(f"Desteklenmeyen türler: {', '.join(unknown)}")

    LAWS_DIR.mkdir(parents=True, exist_ok=True)

    documents = list_documents(types)
    if not documents:
        raise SystemExit("Resmî API hiç doküman döndürmedi; güvenlik için repo değiştirilmedi.")

    print(f"Toplam {len(documents)} doküman bulundu.")
    tasks = assign_targets(documents)

    changed_files = 0
    errors: list[str] = []
    index_entries: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {executor.submit(sync_one, task): task for task in tasks}
        completed = 0

        for future in as_completed(future_map):
            item, directory, _previous = future_map[future]
            completed += 1
            try:
                _item, directory, metadata, text = future.result()
            except Exception as exc:
                errors.append(f"{item.get('mevzuatId')} {item.get('mevzuatAdi')}: {exc}")
                print(f"HATA [{completed}/{len(tasks)}] {errors[-1]}", file=sys.stderr)
                continue

            metadata_text = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
            markdown_text = render_markdown(metadata, text)
            if write_text_if_changed(directory / "ustveri.json", metadata_text):
                changed_files += 1
            if write_text_if_changed(directory / "metin.md", markdown_text):
                changed_files += 1

            index_entries.append(
                {
                    "law_number": metadata["law_number"],
                    "title": metadata["title"],
                    "type": metadata["source_type"],
                    "path": directory.relative_to(ROOT).as_posix(),
                    "source_mevzuat_id": metadata["source_mevzuat_id"],
                    "content_sha256": metadata["content_sha256"],
                }
            )
            print(f"OK [{completed}/{len(tasks)}] {directory.name}")

    index_entries.sort(key=lambda x: (x["type"], x["law_number"], x["title"]))
    if not errors:
        index_text = json.dumps(
            {
                "source": BASE_URL,
                "types": types,
                "documents": index_entries,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if write_text_if_changed(INDEX_PATH, index_text):
            changed_files += 1
    else:
        print("Bazı dokümanlar alınamadığı için indeks.json bu çalışmada değiştirilmedi.", file=sys.stderr)

    print(f"Değişen dosya sayısı: {changed_files}")
    if errors:
        print(f"Başarısız doküman sayısı: {len(errors)}", file=sys.stderr)
        for error in errors[:20]:
            print(f"- {error}", file=sys.stderr)

    if len(errors) > args.max_errors:
        print(
            f"Hata sayısı izin verilen eşiği ({args.max_errors}) aştı; commit yapılmamalı.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
