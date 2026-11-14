#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def normalize_structured_file(path: Path) -> tuple[int, bool]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    paragraph_count = 0

    for page in payload.get("pages", []):
        page_no = page.get("page_no")
        if page_no is None:
            continue
        for index, paragraph in enumerate(page.get("paragraphs", []), start=1):
            expected_id = f"page-{page_no}-p{index}"
            paragraph_count += 1
            if paragraph.get("paragraph_id") != expected_id:
                paragraph["paragraph_id"] = expected_id
                changed = True
            if paragraph.get("paragraph_no") != index:
                paragraph["paragraph_no"] = index
                changed = True

    if changed:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return paragraph_count, changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize paragraph ids in a structured knowledge-base document."
    )
    parser.add_argument("path", help="Path to the *.structured.json file")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        raise FileNotFoundError(path)

    paragraph_count, changed = normalize_structured_file(path)
    print(
        json.dumps(
            {
                "path": str(path),
                "paragraph_count": paragraph_count,
                "changed": changed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
