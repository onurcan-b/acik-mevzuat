#!/usr/bin/env python3
"""Resmi PDF kaynaklarından kanun metinlerini indirip `metin.md` dosyalarını günceller.

Gereksinimler:
- curl
- pdftotext (poppler)

Kullanım:
    python betikler/kanun_metinlerini_indir.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KANUNLAR = ROOT / "kanunlar"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def run(cmd: list[str]) -> None:
    sonuc = subprocess.run(cmd, capture_output=True, text=True)
    if sonuc.returncode != 0:
        raise RuntimeError(f"Komut başarısız: {' '.join(cmd)}\n{sonuc.stderr}")


def indir_pdf(url: str, hedef: Path) -> None:
    run(
        [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "-A",
            USER_AGENT,
            "-H",
            "Accept: application/pdf,*/*;q=0.8",
            "-H",
            "Accept-Language: tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "-e",
            "https://www.mevzuat.gov.tr/",
            "-o",
            str(hedef),
            url,
        ]
    )


def pdf_metnini_cikar(pdf: Path, txt: Path) -> str:
    if shutil.which("pdftotext"):
        run(["pdftotext", "-layout", str(pdf), str(txt)])
        return txt.read_text(encoding="utf-8", errors="ignore")

    try:
        from pypdf import PdfReader
    except ImportError as hata:
        raise RuntimeError(
            "PDF metni çıkarılamadı: `pdftotext` bulunamadı ve Python `pypdf` "
            "paketi kurulu değil. Çözüm: `python -m pip install pypdf`"
        ) from hata

    okuyucu = PdfReader(str(pdf))
    sayfalar = [(sayfa.extract_text() or "").strip() for sayfa in okuyucu.pages]
    ham = "\n\n".join(sayfa for sayfa in sayfalar if sayfa)
    if not ham.strip():
        raise RuntimeError(f"PDF metni boş çıkarıldı: {pdf}")
    return ham


def main() -> int:
    for ustveri in sorted(KANUNLAR.glob("*/ustveri.json")):
        klasor = ustveri.parent
        veri = json.loads(ustveri.read_text(encoding="utf-8"))
        url = veri["source_url"]

        pdf = klasor / "kaynak.pdf"
        txt = klasor / "metin_raw.txt"
        metin = klasor / "metin.md"

        print(f"İndiriliyor: {klasor.name}")
        indir_pdf(url, pdf)

        ham = pdf_metnini_cikar(pdf, txt)
        metin.write_text(
            (
                f"# {veri['title']} (No. {veri['law_number']})\n\n"
                f"> Kaynak: {url}\n"
                "> Not: Bu metin resmi PDF kaynağından otomatik çıkarılmış ham metindir.\n\n"
                "```text\n"
                f"{ham}\n"
                "```\n"
            ),
            encoding="utf-8",
        )

        pdf.unlink(missing_ok=True)
        txt.unlink(missing_ok=True)

    print("Tüm metinler güncellendi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
