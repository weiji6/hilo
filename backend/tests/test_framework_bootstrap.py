"""Ensure initial setup is repeatable and publication excludes private data."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initialization_preserves_user_configuration_and_generates_unique_auth_secret(tmp_path):
    init = script("init_config")
    first, second = tmp_path / "first", tmp_path / "second"
    init.initialize(first, "technical-docs")
    assert "profile: examples/technical-docs/domain.yaml" in (first / "config.yaml").read_text()
    assert (first / "knowledge/docs/retry-policy.md").exists()
    secret = (first / "frontend/.env").read_text()
    assert "replace-with-a-random-secret" not in secret
    (first / "backend/.env").write_text("my private settings")
    assert init.initialize(first, "technical-docs") == []
    assert (first / "backend/.env").read_text() == "my private settings"
    init.initialize(second)
    assert (second / "frontend/.env").read_text() != secret


def test_export_excludes_private_history_credentials_and_user_material(tmp_path):
    release = script("export_open_source")
    source = tmp_path / "source"
    for name in [
        "README.md",
        "LICENSE",
        "backend/src/app.py",
        "frontend/src/core/knowledge/api.ts",
        "backend/.production.env",
        "backend/scripts/sync_to_server.py",
        "frontend/.env",
        "config.yaml",
        "knowledge/docs/private.md",
        "frontend/public/demo/threads/private.json",
        ".git/config",
        ".github/workflows/deploy-prod.yml",
    ]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("example")
    names = {path.relative_to(source).as_posix() for path in release.source_files(source)}
    assert names == {"README.md", "LICENSE", "backend/src/app.py", "frontend/src/core/knowledge/api.ts"}
    output = tmp_path / "public"
    assert release.export(output, source) == 4
    assert not (output / ".git").exists()
    assert (output / "knowledge/docs/.gitkeep").exists()


def test_publication_guard_rejects_secret_without_printing_it(tmp_path):
    release = script("export_open_source")
    root = tmp_path / "source"
    root.mkdir()
    path = root / "README.md"
    value = "ghp_" + "A" * 36
    path.write_text(value)
    findings = release.inspect([path], root)
    assert len(findings) == 1 and "GitHub token" in findings[0]
    assert value not in findings[0]
