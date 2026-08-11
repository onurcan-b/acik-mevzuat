#!/usr/bin/env python3
"""OpenMevzuat'ın güncel canonical snapshot'ını Açık Mevzuat formatına dönüştürür.

Bu script OpenMevzuat kaynak kodunu çalıştırmaz veya kopyalamaz. GitHub Actions
önce upstream repoyu shallow-clone eder; script yalnızca güncel canonical hukuk
metinlerini ve kaynak metadata'sını okuyup bu reponun JSON/Markdown formatını
üretir. Nihai ve bağlayıcı kaynak her zaman resmi mevzuat kaynağıdır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "kanunlar"
INDEX_PATH = ROOT / "indeks.json"
UPSTREAM_STATE = ROOT / ".openmevzuat-upstream.json"

ARTICLE_LINK_RE = re.compile(r"\((articles/[^)]+\.md)\)")
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
NUMBER_RE = re.compile(r"\*\*Kanun No:\*\*\s*([^\s]+)")
SOURCE_URL_RE = re.compile(r':source/url\s+"([^"]+)"')


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upstream_commit(upstream_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def load_existing_metadata(directory: Path) -> dict[str, Any]:
    path = directory / "ustveri.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_source_url(metadata_path: Path) -> str:
    if metadata_path.exists():
        text = metadata_path.read_text(encoding="utf-8", errors="replace")
        match = SOURCE_URL_RE.search(text)
        if match:
            return match.group(1)
    return "https://www.mevzuat.gov.tr/"


def source_id_from_url(url: str) -> str:
    match = re.search(r"/([^/]+?)\.pdf(?:\?.*)?$", url)
    return match.group(1) if match else "openmevzuat-canonical"


def read_canonical_document(directory: Path) -> tuple[str, str, str]:
    readme_path = directory / "README.md"
    if not readme_path.exists():
        raise RuntimeError(f"README.md yok: {directory}")

    readme = readme_path.read_text(encoding="utf-8", errors="replace")
    title_match = TITLE_RE.search(readme)
    if not title_match:
        raise RuntimeError(f"Başlık bulunamadı: {readme_path}")
    title = title_match.group(1).strip()

    number_match = NUMBER_RE.search(readme)
    law_number = number_match.group(1).strip() if number_match else directory.name.split("-", 1)[0]

    linked_paths: list[Path] = []
    seen: set[Path] = set()
    for rel in ARTICLE_LINK_RE.findall(readme):
        p = directory / rel
        if p.exists() and p not in seen:
            linked_paths.append(p)
            seen.add(p)

    articles_dir = directory / "articles"
    if articles_dir.exists():
        for p in sorted(articles_dir.glob("*.md")):
            if p not in seen:
                linked_paths.append(p)
                seen.add(p)

    if not linked_paths:
        raise RuntimeError(f"Madde dosyası bulunamadı: {directory}")

    chunks = [p.read_text(encoding="utf-8", errors="replace").strip() for p in linked_paths]
    body = "\n\n".join(chunk for chunk in chunks if chunk).strip() + "\n"
    return law_number, title, body


def render_markdown(title: str, law_number: str, source_url: str, body: str, upstream_sha: str) -> str:
    return "\n".join(
        [
            f"# {title} (No. {law_number})",
            "",
            f"> Resmî kaynak: {source_url}",
            "> Taşıma/normalizasyon kaynağı: https://github.com/openmevzuat/openmevzuat",
            f"> Upstream snapshot: {upstream_sha}",
            "",
            "---",
            "",
            body.rstrip(),
            "",
        ]
    )


def write_if_changed(path: Path, content: str) -> bool:
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    if previous == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def collect_documents(upstream_root: Path) -> list[tuple[Path, Path, str]]:
    groups = [
        (
            upstream_root / "data" / "canonical" / "laws",
            upstream_root / "data" / "metadata" / "laws",
            "KANUN",
        ),
        (
            upstream_root / "data" / "canonical" / "constitution",
            upstream_root / "data" / "metadata" / "constitution",
            "ANAYASA",
        ),
    ]
    documents: list[tuple[Path, Path, str]] = []
    for canonical_root, metadata_root, source_type in groups:
        if not canonical_root.exists():
            continue
        for directory in sorted(p for p in canonical_root.iterdir() if p.is_dir()):
            documents.append((directory, metadata_root / f"{directory.name}.edn", source_type))
    return documents


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path, help="Shallow-clone edilmiş OpenMevzuat repo yolu")
    parser.add_argument("--min-documents", type=int, default=900)
    args = parser.parse_args()

    upstream_root = args.upstream.resolve()
    upstream_sha = upstream_commit(upstream_root)
    documents = collect_documents(upstream_root)
    if len(documents) < args.min_documents:
        raise SystemExit(
            f"Güvenlik kontrolü: upstream yalnızca {len(documents)} belge içeriyor; "
            f"en az {args.min_documents} bekleniyordu. Repo değiştirilmedi."
        )

    LAWS_DIR.mkdir(parents=True, exist_ok=True)
    desired_dirs: set[str] = set()
    index_entries: list[dict[str, Any]] = []
    changed = 0

    for canonical_dir, metadata_path, source_type in documents:
        slug = canonical_dir.name
        desired_dirs.add(slug)
        target = LAWS_DIR / slug
        previous = load_existing_metadata(target)

        law_number, title, body = read_canonical_document(canonical_dir)
        source_url = read_source_url(metadata_path)
        markdown = render_markdown(title, law_number, source_url, body, upstream_sha)
        body_hash = sha256(body)

        metadata = {
            "law_number": law_number,
            "title": title,
            "slug": slug,
            "accepted_date": previous.get("accepted_date"),
            "effective_status": "in_force",
            "official_gazette": previous.get("official_gazette")
            or {"date": None, "number": None},
            "source_url": source_url,
            "language": "tr",
            "tags": previous.get("tags") or [],
            "source_mevzuat_id": source_id_from_url(source_url),
            "source_type": source_type,
            "content_sha256": body_hash,
            "retrieval_api": "https://github.com/openmevzuat/openmevzuat",
        }

        metadata_text = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        if write_if_changed(target / "ustveri.json", metadata_text):
            changed += 1
        if write_if_changed(target / "metin.md", markdown):
            changed += 1

        index_entries.append(
            {
                "law_number": law_number,
                "title": title,
                "type": source_type,
                "path": target.relative_to(ROOT).as_posix(),
                "source_mevzuat_id": metadata["source_mevzuat_id"],
                "content_sha256": body_hash,
            }
        )

    # Canonical snapshot'ta artık bulunmayan yerel klasörleri kaldır. Böylece
    # katalogdan çıkan/repeal edilen kayıtlar da Git diff'inde görünür.
    for local_dir in sorted(p for p in LAWS_DIR.iterdir() if p.is_dir()):
        if local_dir.name not in desired_dirs:
            shutil.rmtree(local_dir)
            changed += 1

    index_entries.sort(key=lambda x: (x["type"], x["law_number"], x["title"]))
    index_text = json.dumps(
        {
            "source": "https://github.com/openmevzuat/openmevzuat",
            "upstream_commit": upstream_sha,
            "documents_total": len(index_entries),
            "documents": index_entries,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    if write_if_changed(INDEX_PATH, index_text):
        changed += 1

    state_text = json.dumps(
        {
            "repository": "openmevzuat/openmevzuat",
            "commit": upstream_sha,
            "documents_total": len(index_entries),
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    if write_if_changed(UPSTREAM_STATE, state_text):
        changed += 1

    print(f"Upstream commit: {upstream_sha}")
    print(f"Belge sayısı: {len(index_entries)}")
    print(f"Değişen dosya/klasör sayısı: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
