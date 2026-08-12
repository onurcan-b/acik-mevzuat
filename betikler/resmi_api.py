#!/usr/bin/env python3
"""senkronize.py'yi Bedesten için kısa ömürlü HTTP bağlantılarıyla çalıştırır.

GitHub-hosted runner'larda uzun ömürlü keep-alive bağlantıları Bedesten tarafında
zaman zaman askıda kalabiliyor. Resmî API mantığı değişmez; yalnızca her istekten
sonra bağlantının kapatılması istenir.
"""
from __future__ import annotations

import senkronize as sync

sync.HEADERS["Connection"] = "close"
sync.SESSION.headers.update({"Connection": "close"})

if __name__ == "__main__":
    raise SystemExit(sync.main())
