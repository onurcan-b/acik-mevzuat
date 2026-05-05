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
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KANUNLAR = ROOT / "kanunlar"


def run(cmd: list[str]) -> None:
    sonuc = subprocess.run(cmd, capture_output=True, text=True)
    if sonuc.returncode != 0:
        raise RuntimeError(f"Komut başarısız: {' '.join(cmd)}\n{sonuc.stderr}")


def main() -> int:
    for ustveri in sorted(KANUNLAR.glob("*/ustveri.json")):
        klasor = ustveri.parent
        veri = json.loads(ustveri.read_text(encoding="utf-8"))
        url = veri["source_url"]

        pdf = klasor / "kaynak.pdf"
        txt = klasor / "metin_raw.txt"
        metin = klasor / "metin.md"

        print(f"İndiriliyor: {klasor.name}")
        run(["curl", "-L", "--fail", "-o", str(pdf), url])
        run(["pdftotext", str(pdf), str(txt)])

        ham = txt.read_text(encoding="utf-8", errors="ignore")
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
