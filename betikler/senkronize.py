#!/usr/bin/env python3
"""Adalet Bakanlığı UYAP/Bedesten servislerinden mevzuat senkronizasyonu.

Kaynaklar yalnızca resmî Adalet Bakanlığı servisleridir:
- katalog: https://bedesten.adalet.gov.tr/mevzuat/searchDocuments
- içerik:  https://bedesten.adalet.gov.tr/mevzuat/getDocumentContent

Günlük mod tüm corpus'u yeniden indirmez. Katalog farklarını, eksik kayıtların
küçük bir bölümünü ve aktif kanunların dönen bir doğrulama kovasını yeniler.
İlk tam backfill için shard modu GitHub Actions matrix ile kullanılır.
"""
from __future__ import annotations

import argparse
import base64
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
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "kanunlar"
INDEX_PATH = ROOT / "indeks.json"
STATE_PATH = ROOT / ".mevzuat-catalog.json"

BASE_URL = "https://bedesten.adalet.gov.tr/mevzuat"
PUBLIC_SITE = "https://mevzuat.adalet.gov.tr"
APP_NAME = "UyapMevzuat"
SUPPORTED_TYPES = {
    "KANUN", "MULGA", "KHK", "CB_KARARNAME", "TUZUK", "YONETMELIK",
    "CB_YONETMELIK", "CB_KARAR", "CB_GENELGE", "KKY", "UY", "TEBLIGLER",
}
USER_AGENT = "acik-mevzuat/4.0 (+https://github.com/onurcan-b/acik-mevzuat)"
HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "AdaletApplicationName": APP_NAME,
    "Origin": PUBLIC_SITE,
    "Referer": f"{PUBLIC_SITE}/",
    "User-Agent": USER_AGENT,
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
LAST_REQUEST_AT = 0.0
REQUEST_DELAY_SECONDS = 0.35

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class ApiError(RuntimeError):
    pass


def _pace() -> None:
    global LAST_REQUEST_AT
    elapsed = time.monotonic() - LAST_REQUEST_AT
    if elapsed < REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS - elapsed)


def _post(
    endpoint: str,
    data: dict[str, Any],
    *,
    paging: bool = False,
    attempts: int = 5,
    timeout: tuple[int, int] = (10, 45),
) -> dict[str, Any]:
    global LAST_REQUEST_AT
    payload: dict[str, Any] = {"data": data, "applicationName": APP_NAME}
    if paging:
        payload["paging"] = True

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            _pace()
            response = SESSION.post(
                f"{BASE_URL}{endpoint}",
                json=payload,
                timeout=timeout,
            )
            LAST_REQUEST_AT = time.monotonic()

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2 ** (attempt + 1)
                except ValueError:
                    delay = 2 ** (attempt + 1)
                time.sleep(min(delay, 30) + random.uniform(0.2, 0.8))
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
            if attempt + 1 >= attempts:
                break
            time.sleep(min(2 ** (attempt + 1), 15) + random.uniform(0.2, 0.8))
    raise ApiError(f"{endpoint} başarısız: {last_error}")


def _list_type(mevzuat_type: str, page_size: int = 20) -> list[dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    page = 1
    total = 0
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
            attempts=8,
            timeout=(10, 60),
        )
        data = body.get("data") or {}
        items = data.get("mevzuatList") or []
        total = int(data.get("total") or total or 0)
        if not items:
            break
        for item in items:
            mevzuat_id = str(item.get("mevzuatId") or "").strip()
            if mevzuat_id:
                clean = dict(item)
                clean["_source_type"] = mevzuat_type
                docs[mevzuat_id] = clean
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
    return sorted(
        docs.values(),
        key=lambda d: (
            str(d.get("_source_type") or ""),
            str(d.get("mevzuatNo") or ""),
            str(d.get("mevzuatAdi") or ""),
            str(d.get("mevzuatId") or ""),
        ),
    )


def catalog_projection(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "mevzuatId": str(item.get("mevzuatId") or ""),
        "mevzuatNo": str(item.get("mevzuatNo") or ""),
        "mevzuatAdi": str(item.get("mevzuatAdi") or ""),
        "resmiGazeteTarihi": item.get("resmiGazeteTarihi"),
        "resmiGazeteSayisi": item.get("resmiGazeteSayisi"),
        "url": item.get("url"),
        "source_type": str(item.get("_source_type") or ""),
    }


def catalog_state(documents: list[dict[str, Any]]) -> dict[str, Any]:
    projected = [catalog_projection(d) for d in documents]
    return {
        "source": PUBLIC_SITE,
        "catalog_api": f"{BASE_URL}/searchDocuments",
        "types": sorted({str(d.get("_source_type") or "") for d in documents}),
        "documents_total": len(projected),
        "documents": projected,
    }


def fingerprint(item: dict[str, Any]) -> str:
    blob = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _decode_document(raw: str, mime_type: str) -> str:
    try:
        blob = base64.b64decode(raw, validate=False)
    except Exception:
        blob = raw.encode("utf-8", errors="replace")

    if "pdf" in mime_type.lower() or blob.startswith(b"%PDF"):
        reader = PdfReader(io.BytesIO(blob))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)

    for encoding in ("utf-8", "windows-1254", "latin-1"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            pass
    return blob.decode("utf-8", errors="replace")


def normalize_document(content: str, mime_type: str = "text/html") -> str:
    if "html" in mime_type.lower() or re.search(r"<(?:html|body|p|div|table|br)\b", content, re.I):
        soup = BeautifulSoup(content, "html.parser")
        for node in soup(["script", "style", "noscript", "svg", "nav", "header", "footer"]):
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


def get_document_text(mevzuat_id: str, attempts: int = 3) -> tuple[str, str]:
    body = _post(
        "/getDocumentContent",
        {"documentType": "MEVZUAT", "id": mevzuat_id},
        attempts=attempts,
        timeout=(10, 45),
    )
    data = body.get("data") or {}
    raw = data.get("content") or ""
    mime_type = str(data.get("mimeType") or "text/html")
    if not raw:
        raise ApiError(f"{mevzuat_id}: boş doküman")
    text = normalize_document(_decode_document(str(raw), mime_type), mime_type)
    if len(text.strip()) < 80:
        raise ApiError(f"{mevzuat_id}: metin beklenenden kısa")
    return text, mime_type


def slugify(value: str) -> str:
    value = value.translate(str.maketrans({
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower() or "isimsiz"


def directory_name(item: dict[str, Any]) -> str:
    mevzuat_id = str(item.get("mevzuatId") or "")
    number = str(item.get("mevzuatNo") or "").strip()
    title = str(item.get("mevzuatAdi") or "İsimsiz mevzuat").strip()
    prefix = slugify(number or mevzuat_id[:8])
    title_slug = slugify(title)
    base = f"{prefix}-{title_slug}"
    if len(base) <= 145:
        return base
    suffix = f"-{slugify(mevzuat_id)[:12]}"
    available = max(20, 145 - len(prefix) - len(suffix) - 1)
    return f"{prefix}-{title_slug[:available].rstrip('-')}{suffix}"


def normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_accepted_date(text: str) -> str | None:
    match = re.search(
        r"Kabul\s+[Tt]arihi\s*[:：]?\s*(\d{1,2})[./](\d{1,2})[./](\d{4})",
        text,
    )
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def source_url(item: dict[str, Any]) -> str:
    mevzuat_id = str(item.get("mevzuatId") or "")
    return f"{PUBLIC_SITE}/mevzuat/{mevzuat_id}"


def build_metadata(item: dict[str, Any], slug: str, text: str, fetched: bool) -> dict[str, Any]:
    source_type = str(item.get("_source_type") or item.get("source_type") or "KANUN")
    return {
        "law_number": str(item.get("mevzuatNo") or "").strip(),
        "title": str(item.get("mevzuatAdi") or "İsimsiz mevzuat").strip(),
        "slug": slug,
        "accepted_date": extract_accepted_date(text) if fetched else None,
        "effective_status": "repealed" if source_type == "MULGA" else "in_force",
        "official_gazette": {
            "date": normalize_date(item.get("resmiGazeteTarihi")),
            "number": str(item.get("resmiGazeteSayisi")).strip()
            if item.get("resmiGazeteSayisi") not in (None, "") else None,
        },
        "source_url": source_url(item),
        "language": "tr",
        "tags": [] if fetched else ["official-fetch-unavailable"],
        "source_mevzuat_id": str(item.get("mevzuatId") or ""),
        "source_type": source_type,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "retrieval_api": f"{BASE_URL}/getDocumentContent",
    }


def render_markdown(meta: dict[str, Any], text: str) -> str:
    gazette = meta["official_gazette"]
    return "\n".join([
        f"# {meta['title']} (No. {meta['law_number'] or '—'})",
        "",
        f"> Resmî kaynak: {meta['source_url']}",
        f"> Resmî Gazete: {gazette.get('date') or 'bilinmiyor'} / {gazette.get('number') or 'bilinmiyor'}",
        f"> UYAP Mevzuat kimliği: {meta['source_mevzuat_id']}",
        "",
        "---",
        "",
        text.rstrip(),
        "",
    ])


def stub_text(item: dict[str, Any], reason: str) -> str:
    return (
        "_Bu kayıt Adalet Bakanlığı UYAP Mevzuat resmî kataloğunda yer alıyor, "
        "ancak bu çalışmada tam metin resmî içerik API'sinden alınamadı. "
        "Otomatik senkronizasyon sonraki çalışmalarda yeniden deneyecektir._\n\n"
        f"Resmî kayıt: {source_url(item)}\n"
        f"Geçici hata: {reason}\n"
    )


def existing_by_id(root: Path = LAWS_DIR) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not root.exists():
        return result
    for meta_path in root.glob("*/ustveri.json"):
        data = load_json(meta_path, {})
        source_id = str(data.get("source_mevzuat_id") or "").strip()
        if source_id:
            result[source_id] = meta_path.parent
    return result


def write_document(item: dict[str, Any], out_laws: Path, *, preserve_good_on_error: bool) -> tuple[str, bool]:
    source_id = str(item["mevzuatId"])
    slug = directory_name(item)
    target = out_laws / slug

    try:
        text, _ = get_document_text(source_id)
        fetched = True
    except Exception as exc:
        if preserve_good_on_error:
            current = existing_by_id(out_laws).get(source_id)
            if current:
                previous = load_json(current / "ustveri.json", {})
                if str(previous.get("retrieval_api") or "").startswith(BASE_URL) and "official-fetch-unavailable" not in (previous.get("tags") or []):
                    print(f"KEEP [{source_id}] geçici API hatası: {exc}", file=sys.stderr, flush=True)
                    return current.name, False
        fetched = False
        text = stub_text(item, str(exc))
        print(f"::warning title=Resmî tam metin alınamadı::{source_id}: {exc}", flush=True)

    target.mkdir(parents=True, exist_ok=True)
    meta = build_metadata(item, slug, text, fetched)
    save_json(target / "ustveri.json", meta)
    (target / "metin.md").write_text(render_markdown(meta, text), encoding="utf-8")
    print(f"{'OK' if fetched else 'STUB'} {source_id} {slug}", flush=True)
    return slug, fetched


def rebuild_index(root: Path = LAWS_DIR) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    failures = 0
    for meta_path in sorted(root.glob("*/ustveri.json")):
        meta = load_json(meta_path, {})
        if not meta:
            continue
        tags = meta.get("tags") or []
        if "official-fetch-unavailable" in tags:
            failures += 1
        entries.append({
            "law_number": meta.get("law_number", ""),
            "title": meta.get("title", ""),
            "type": meta.get("source_type", ""),
            "path": meta_path.parent.relative_to(ROOT).as_posix() if root == LAWS_DIR else f"kanunlar/{meta_path.parent.name}",
            "source_mevzuat_id": meta.get("source_mevzuat_id", ""),
            "content_sha256": meta.get("content_sha256", ""),
            "fetch_status": "stub" if "official-fetch-unavailable" in tags else "ok",
        })
    entries.sort(key=lambda x: (x["type"], x["law_number"], x["title"], x["source_mevzuat_id"]))
    return {
        "source": PUBLIC_SITE,
        "catalog_api": f"{BASE_URL}/searchDocuments",
        "content_api": f"{BASE_URL}/getDocumentContent",
        "documents_total": len(entries),
        "fetch_failures": failures,
        "documents": entries,
    }


def types_arg(raw: str) -> list[str]:
    types = [x.strip().upper() for x in raw.split(",") if x.strip()]
    unknown = sorted(set(types) - SUPPORTED_TYPES)
    if unknown:
        raise SystemExit(f"Desteklenmeyen türler: {', '.join(unknown)}")
    return types


def mode_catalog(args: argparse.Namespace) -> int:
    docs = list_documents(types_arg(args.types))
    if len(docs) < args.min_documents:
        raise SystemExit(f"Güvenlik kontrolü: katalog {len(docs)} belge döndürdü; en az {args.min_documents} bekleniyor.")
    out = Path(args.catalog_out)
    save_json(out, {"documents": docs, "state": catalog_state(docs)})
    print(f"Katalog yazıldı: {len(docs)} belge -> {out}")
    return 0


def mode_shard(args: argparse.Namespace) -> int:
    payload = load_json(Path(args.catalog_file), {})
    docs = payload.get("documents") or []
    if len(docs) < args.min_documents:
        raise SystemExit(f"Katalog eksik: {len(docs)}")
    shard_docs = [d for i, d in enumerate(docs) if i % args.shard_count == args.shard_index]
    out_root = Path(args.output_root)
    out_laws = out_root / "kanunlar"
    if out_root.exists():
        shutil.rmtree(out_root)
    out_laws.mkdir(parents=True, exist_ok=True)

    ok = 0
    stub = 0
    for i, item in enumerate(shard_docs, 1):
        _, fetched = write_document(item, out_laws, preserve_good_on_error=False)
        ok += int(fetched)
        stub += int(not fetched)
        print(f"Shard {args.shard_index}: {i}/{len(shard_docs)}", flush=True)

    save_json(out_root / f"manifest-{args.shard_index:02d}.json", {
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "documents": len(shard_docs),
        "ok": ok,
        "stub": stub,
    })
    print(f"Shard tamamlandı: {len(shard_docs)} belge; OK={ok}, STUB={stub}")
    return 0


def mode_reindex(args: argparse.Namespace) -> int:
    catalog = load_json(Path(args.catalog_file), {})
    state = catalog.get("state")
    if not state:
        docs = catalog.get("documents") or []
        state = catalog_state(docs)
    save_json(STATE_PATH, state)
    save_json(INDEX_PATH, rebuild_index(LAWS_DIR))
    print(f"İndeks: {load_json(INDEX_PATH, {}).get('documents_total', 0)} belge")
    return 0


def mode_daily(args: argparse.Namespace) -> int:
    docs = list_documents(types_arg(args.types))
    if len(docs) < args.min_documents:
        raise SystemExit(
            f"Güvenlik kontrolü: resmî katalog {len(docs)} belge döndürdü; "
            f"en az {args.min_documents} bekleniyordu. Repo değiştirilmedi."
        )

    current_state = catalog_state(docs)
    previous_state = load_json(STATE_PATH, {})
    previous_map = {
        str(d.get("mevzuatId") or ""): d
        for d in (previous_state.get("documents") or [])
        if d.get("mevzuatId")
    }
    current_map = {str(d["mevzuatId"]): d for d in docs}
    current_projected = {sid: catalog_projection(d) for sid, d in current_map.items()}

    changed: set[str] = set()
    if previous_map:
        for sid, projected in current_projected.items():
            old = previous_map.get(sid)
            if old is None or fingerprint(projected) != fingerprint(old):
                changed.add(sid)

    existing = existing_by_id()
    missing = [sid for sid in current_map if sid not in existing]
    backfill = set(sorted(missing)[: args.max_backfill])

    day_bucket = date.today().toordinal() % args.rotation_buckets
    rotation = {
        sid for sid, item in current_map.items()
        if str(item.get("_source_type") or "") == "KANUN"
        and int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16) % args.rotation_buckets == day_bucket
    }

    selected = changed | backfill | rotation
    print(
        f"Günlük seçim: katalog-değişen={len(changed)}, "
        f"eksik-backfill={len(backfill)}/{len(missing)}, rotasyon={len(rotation)}, "
        f"toplam={len(selected)}",
        flush=True,
    )

    LAWS_DIR.mkdir(parents=True, exist_ok=True)
    for i, sid in enumerate(sorted(selected), 1):
        write_document(current_map[sid], LAWS_DIR, preserve_good_on_error=True)
        print(f"Günlük içerik: {i}/{len(selected)}", flush=True)

    removed_ids = set(previous_map) - set(current_map)
    by_id = existing_by_id()
    for sid in sorted(removed_ids):
        directory = by_id.get(sid)
        if directory and directory.exists():
            shutil.rmtree(directory)
            print(f"Katalogdan kaldırıldı: {sid} ({directory.name})")

    save_json(STATE_PATH, current_state)
    save_json(INDEX_PATH, rebuild_index(LAWS_DIR))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("daily", "catalog", "shard", "reindex"), default="daily")
    p.add_argument("--types", default="KANUN,MULGA")
    p.add_argument("--delay", type=float, default=0.35)
    p.add_argument("--min-documents", type=int, default=1000)
    p.add_argument("--catalog-out", default="/tmp/mevzuat-catalog.json")
    p.add_argument("--catalog-file", default="/tmp/mevzuat-catalog.json")
    p.add_argument("--output-root", default="/tmp/mevzuat-shard")
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=32)
    p.add_argument("--rotation-buckets", type=int, default=28)
    p.add_argument("--max-backfill", type=int, default=20)
    return p


def main() -> int:
    args = build_parser().parse_args()
    global REQUEST_DELAY_SECONDS
    REQUEST_DELAY_SECONDS = max(0.15, args.delay)
    if args.shard_count <= 0 or not (0 <= args.shard_index < args.shard_count):
        raise SystemExit("Geçersiz shard index/count")
    if args.rotation_buckets <= 0:
        raise SystemExit("rotation-buckets pozitif olmalı")

    if args.mode == "catalog":
        return mode_catalog(args)
    if args.mode == "shard":
        return mode_shard(args)
    if args.mode == "reindex":
        return mode_reindex(args)
    return mode_daily(args)


if __name__ == "__main__":
    raise SystemExit(main())
