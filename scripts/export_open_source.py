"""Export a clean Hilo source snapshot without private history or runtime data.

Uses an explicit source allowlist, skips symlinks and local credentials, and
checks the selected text files before writing a new destination directory.
This is a release guard, not a substitute for reviewing the publication diff.
"""

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "README.md",
    "README.zh-CN.md",
    "README.en.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "AGENTS.md",
    "Makefile",
    ".gitignore",
    ".dockerignore",
    "config.example.yaml",
    "extensions_config.example.json",
    "CHANGELOG.md",
}
DOC_FILES = {
    "docs/architecture.md",
    "docs/domain-profiles.md",
    "docs/roadmap.md",
    "docs/functionality-audit.md",
}
DOCKER_FILES = {
    "docker/compose.hilo.yaml",
    "docker/nginx/hilo.conf",
    "docker/provisioner/app.py",
    "docker/provisioner/Dockerfile",
    "docker/provisioner/README.md",
}
WORKFLOW_FILES = {".github/workflows/ci.yml", ".github/pull_request_template.md"}
SCRIPT_FILES = {
    "scripts/init_config.py",
    "scripts/export_open_source.py",
    "scripts/docker.sh",
    "scripts/ingest_structured_docs_to_db.py",
    "scripts/normalize_structured_paragraph_ids.py",
    "scripts/prewarm_knowledge_indexes.py",
    "scripts/reindex_global_knowledge.py",
    "backend/scripts/local_ocr.py",
}
EXCLUDE_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".deer-flow",
    ".hilo",
    ".langgraph_api",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode",
    ".claude",
    "htmlcov",
    "build",
    "dist",
    "static",
}
OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(
        r"gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{40,}"
    ),
    "provider token": re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}\b"),
    "cloud access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private network address": re.compile(
        rf"(?<![\d.])(?:10\.{OCTET}\.{OCTET}\.{OCTET}|192\.168\.{OCTET}\.{OCTET})(?![\d.])"
    ),
}


def included(relative: Path) -> bool:
    name = relative.as_posix()
    if any(part in EXCLUDE_PARTS for part in relative.parts):
        return False
    if relative.name.startswith(".env") and relative.name != ".env.example":
        return False
    if relative.name.startswith(".production.env") or relative.suffix in {
        ".log",
        ".pyc",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".tsbuildinfo",
    }:
        return False
    if name in ROOT_FILES | DOC_FILES | DOCKER_FILES | WORKFLOW_FILES | SCRIPT_FILES:
        return True
    if name.startswith("examples/"):
        return relative.suffix in {".md", ".yaml", ".json"}
    if name.startswith("skills/public/"):
        return True
    if name.startswith("backend/"):
        if name.startswith("backend/scripts/") or name == "backend/CONTRIBUTING.md":
            return False
        if len(relative.parts) == 2 and relative.suffix == ".py":
            return False
        return not name.startswith("backend/docs/") and relative.name not in {
            "config.yaml",
            ".coverage",
            "agent_history.gif",
        }
    if name.startswith("frontend/"):
        if len(relative.parts) == 2 and (
            relative.suffix == ".py" or relative.name == "next-env.d.ts"
        ):
            return False
        return not name.startswith(
            (
                "frontend/public/demo/",
                "frontend/public/images/",
                "frontend/scripts/save-demo",
            )
        )
    return False


def source_files(root: Path = ROOT) -> list[Path]:
    # A pruned traversal avoids walking dependencies and existing release output.
    files: list[Path] = []
    import os

    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in EXCLUDE_PARTS | {"release", ".hilo-release"}
            and not (Path(directory) == root and d in {"knowledge", "logs"})
            and not (Path(directory) / d).is_symlink()
        )
        for name in sorted(names):
            path = Path(directory) / name
            if not path.is_symlink() and included(path.relative_to(root)):
                files.append(path)
    return files


def inspect(files: list[Path], root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(root)}:{line}: {label}")
    return findings


def export(output: Path, root: Path = ROOT) -> int:
    output = output.resolve()
    if output.exists():
        raise ValueError(f"Destination already exists; refusing to overwrite: {output}")
    if output == root.resolve() or output in root.resolve().parents:
        raise ValueError("Destination must not be the source or one of its parents")
    files = source_files(root)
    findings = inspect(files, root)
    if findings:
        raise ValueError(
            "Publication inspection failed (values redacted):\n" + "\n".join(findings)
        )
    output.mkdir(parents=True)
    for path in files:
        target = output / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (output / "knowledge/docs").mkdir(parents=True, exist_ok=True)
    (output / "knowledge/docs/.gitkeep").touch()
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        files = source_files()
        findings = inspect(files)
        if findings:
            print("\n".join(findings))
            raise SystemExit(1)
        print(
            f"Publication inspection passed: {len(files)} selected files; sensitive values are never printed."
        )
    elif args.output:
        count = export(args.output)
        print(
            f"Exported {count} source files to {args.output.resolve()} without Git history or private runtime data."
        )
    else:
        parser.error("Provide --check or --output")


if __name__ == "__main__":
    main()
