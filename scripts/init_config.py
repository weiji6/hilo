"""Create local Hilo configuration without overwriting user files (stdlib only)."""

import argparse
import secrets
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def initialize(root: Path, example: str | None = None) -> list[str]:
    root = root.resolve()
    created: list[str] = []

    def write_once(relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(content)
            created.append(relative)
        except FileExistsError:
            pass

    config = (SOURCE_ROOT / "config.example.yaml").read_text(encoding="utf-8")
    if example:
        config = config.replace(
            "domain:\n  name: general",
            f"domain:\n  profile: examples/{example}/domain.yaml",
        )
        example_root = SOURCE_ROOT / "examples" / example
        for path in sorted(example_root.rglob("*")):
            if path.is_file():
                write_once(
                    str(path.relative_to(SOURCE_ROOT)), path.read_text(encoding="utf-8")
                )
        for path in sorted((example_root / "documents").glob("*.md")):
            write_once(f"knowledge/docs/{path.name}", path.read_text(encoding="utf-8"))
    write_once("config.yaml", config)
    write_once(
        "backend/.env",
        (SOURCE_ROOT / "backend/.env.example").read_text(encoding="utf-8"),
    )
    frontend_env = (SOURCE_ROOT / "frontend/.env.example").read_text(encoding="utf-8")
    write_once(
        "frontend/.env",
        frontend_env.replace("replace-with-a-random-secret", secrets.token_urlsafe(48)),
    )
    write_once(
        "extensions_config.json",
        (SOURCE_ROOT / "extensions_config.example.json").read_text(encoding="utf-8"),
    )
    (root / "knowledge/docs").mkdir(parents=True, exist_ok=True)
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--example", choices=["technical-docs", "fiscal-history"])
    args = parser.parse_args()
    created = initialize(args.root, args.example)
    print(f"Hilo configuration ready: {args.root.resolve()}")
    print(f"Created {len(created)} files; existing files were preserved.")
    print("Set your model API key in backend/.env before starting Hilo.")
    print(
        "If config.yaml already existed, select the desired domain profile there manually."
    )


if __name__ == "__main__":
    main()
