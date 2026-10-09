#!/usr/bin/env python3
"""Check the small public release surface for safety and broken links."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".json", ".csv", ".txt", ".html", ".js", ".yml", ".yaml"}
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".ipynb_checkpoints"}
EXCLUDED_PREFIXES = (
    Path("data/raw"),
    Path("data/extracted"),
    Path("data/processed"),
    Path("runs"),
)
REQUIRED_FILES = (
    Path("README.md"),
    Path("LICENSE"),
    Path("Makefile"),
    Path("apps/livelab/index.html"),
    Path("apps/livelab/app.js"),
    Path("config/integration/metarank_event_contract.json"),
    Path("docs/integration/01-system-architecture.md"),
    Path("docs/integration/03-evidence-boundary.md"),
    Path("reports/integration/GateC-统一离线评估.md"),
    Path("services/metarank/compose.yml"),
    Path("tests/test_metarank_integration.py"),
)
REMOVED_LEGACY_PATHS = (
    Path("notebooks"),
    Path("output"),
    Path("portfolio"),
    Path("reports/data-quality"),
    Path("reports/gate4"),
)


def is_public_candidate(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if any(relative == prefix or prefix in relative.parents for prefix in EXCLUDED_PREFIXES):
        return False
    return path.is_file()


def local_markdown_links(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8")
    links = re.findall(r"\]\((\./[^)#]+)(?:#[^)]+)?\)", text)
    return [(path.parent / unquote(link)).resolve() for link in links]


def main() -> None:
    failures: list[dict[str, str]] = []
    checked_files: list[Path] = []
    sensitive_patterns = {
        "absolute_macos_home": re.compile("/" + "Users" + r"/[^/\s]+/"),
        "absolute_windows_home": re.compile(r"[A-Za-z]:\\" + "Users" + r"\\[^\\\s]+\\"),
        "openai_style_token": re.compile("sk" + r"-[A-Za-z0-9_-]{20,}"),
        "private_key": re.compile("BEGIN " + r"(?:RSA |OPENSSH |EC )?PRIVATE KEY"),
    }

    for relative in REQUIRED_FILES:
        if not (PROJECT_ROOT / relative).is_file():
            failures.append({"check": "required_file", "file": str(relative), "detail": "missing"})

    for relative in REMOVED_LEGACY_PATHS:
        if (PROJECT_ROOT / relative).exists():
            failures.append(
                {"check": "legacy_clutter", "file": str(relative), "detail": "should stay removed"}
            )

    for path in PROJECT_ROOT.rglob("*"):
        if not is_public_candidate(path):
            continue
        checked_files.append(path)
        relative = path.relative_to(PROJECT_ROOT)
        if path.stat().st_size > 10 * 1024 * 1024:
            failures.append({"check": "public_file_size", "file": str(relative), "detail": ">10 MiB"})
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in sensitive_patterns.items():
            if pattern.search(text):
                failures.append({"check": name, "file": str(relative), "detail": "pattern matched"})

    for markdown in PROJECT_ROOT.rglob("*.md"):
        if not is_public_candidate(markdown):
            continue
        for target in local_markdown_links(markdown):
            if not target.exists():
                failures.append(
                    {"check": "local_markdown_link", "file": str(markdown.relative_to(PROJECT_ROOT)), "detail": str(target)}
                )

    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        failures.append({"check": "code_license", "file": "LICENSE", "detail": "expected Apache-2.0"})

    payload = {
        "status": "PASS" if not failures else "FAIL",
        "checked_public_candidate_files": len(checked_files),
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
