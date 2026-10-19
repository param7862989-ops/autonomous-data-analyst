"""Write the OpenAPI schema to a file: ``python -m app.openapi_export <path>``.

The frontend generates its typed API client from this file; CI regenerates it and fails if the
committed copy is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.config import Settings
from app.main import create_app


def export(path: Path) -> None:
    settings = Settings(_env_file=None, enable_api_docs=True)
    schema = create_app(settings).openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.openapi_export <output-path>")
    export(Path(sys.argv[1]))
