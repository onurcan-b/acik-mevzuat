#!/usr/bin/env python3
import json
from pathlib import Path

try:
    import jsonschema
except ImportError:
    raise SystemExit(
        "jsonschema paketi kurulu değil. Kurulum: pip install jsonschema"
    )

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "semalar" / "kanun.schema.json"
LAWS_DIR = ROOT / "kanunlar"


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    errors = []
    for metadata_path in sorted(LAWS_DIR.glob("*/ustveri.json")):
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        file_errors = list(validator.iter_errors(data))
        if file_errors:
            for err in file_errors:
                errors.append(f"{metadata_path}: {err.message}")

    if errors:
        print("Doğrulama hataları bulundu:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Tüm metadata dosyaları doğrulandı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
