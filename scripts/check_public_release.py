#!/usr/bin/env python3
"""Check that FlowLens is safe and coherent enough for a public repository."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "reports" / "gate5" / "public_release_check.json"
TEXT_SUFFIXES = {".md", ".py", ".json", ".csv", ".txt", ".html", ".ipynb"}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".deps",
    "__pycache__",
    ".ipynb_checkpoints",
}
EXCLUDED_PREFIXES = (
    Path("data/raw"),
    Path("data/extracted"),
    Path("data/processed"),
    Path("runs"),
    Path("reports/gate5"),
)
EXCLUDED_FILES = {
    Path("00-PRD-v1.md"),
    Path("01-JD覆盖与验收矩阵.md"),
    Path("03-GitHub案例取舍.md"),
    Path("05-公开发布检查清单.md"),
    Path("portfolio/FlowLens-推荐策略产品作品集.html"),
    Path("output/pdf/FlowLens-推荐策略产品作品集.pdf"),
    Path("reports/gate3/standard_test_candidate_scores.csv"),
    Path("reports/gate3/random_sensitivity_candidate_scores.csv"),
    Path("reports/gate3/validation_candidate_scores.csv"),
    Path("reports/gate3/user_ranking_metrics.csv"),
    Path("reports/gate4/user_strategy_metrics.csv"),
}


def is_public_candidate(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative in EXCLUDED_FILES:
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
    warnings: list[dict[str, str]] = []
    checked_files: list[Path] = []

    sensitive_patterns = {
        "absolute_macos_home": re.compile("/" + "Users" + r"/[^/\s]+/"),
        "absolute_windows_home": re.compile(r"[A-Za-z]:\\" + "Users" + r"\\[^\\\s]+\\"),
        "openai_style_token": re.compile("sk" + r"-[A-Za-z0-9_-]{20,}"),
        "private_key": re.compile("BEGIN " + r"(?:RSA |OPENSSH |EC )?PRIVATE KEY"),
    }

    for path in PROJECT_ROOT.rglob("*"):
        if not is_public_candidate(path):
            continue
        checked_files.append(path)
        relative = path.relative_to(PROJECT_ROOT)
        if path.stat().st_size > 10 * 1024 * 1024:
            failures.append(
                {"check": "public_file_size", "file": str(relative), "detail": ">10 MiB"}
            )
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in sensitive_patterns.items():
            if pattern.search(text):
                failures.append(
                    {"check": name, "file": str(relative), "detail": "pattern matched"}
                )

    readme = PROJECT_ROOT / "README.md"
    for target in local_markdown_links(readme):
        if not target.exists():
            failures.append(
                {
                    "check": "readme_local_link",
                    "file": str(target),
                    "detail": "target missing",
                }
            )

    gate3 = json.loads((PROJECT_ROOT / "reports/gate3/run_manifest.json").read_text())
    gate4 = json.loads((PROJECT_ROOT / "reports/gate4/run_manifest.json").read_text())
    gate4_config = json.loads((PROJECT_ROOT / "config/gate4_strategies.json").read_text())
    if gate4["upstream_gate3_run_id"] != gate3["run_id"]:
        failures.append(
            {
                "check": "gate_lineage",
                "file": "reports/gate4/run_manifest.json",
                "detail": "Gate 4 manifest does not reference current Gate 3 run",
            }
        )
    if gate4_config["upstream_gate3_run_id"] != gate3["run_id"]:
        failures.append(
            {
                "check": "gate4_config_lineage",
                "file": "config/gate4_strategies.json",
                "detail": "Gate 4 config does not reference current Gate 3 run",
            }
        )

    license_path = PROJECT_ROOT / "LICENSE"
    if not license_path.exists():
        warnings.append(
            {
                "check": "code_license",
                "file": "LICENSE",
                "detail": "Code license requires user selection before publication",
            }
        )
    else:
        license_text = license_path.read_text(encoding="utf-8")
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            failures.append(
                {
                    "check": "code_license",
                    "file": "LICENSE",
                    "detail": "Expected the selected Apache License 2.0 text",
                }
            )
    if not (PROJECT_ROOT / ".git").exists():
        warnings.append(
            {
                "check": "independent_git_repository",
                "file": ".git",
                "detail": "Initialize FlowLens as an independent repository before publication",
            }
        )

    if failures:
        status = "FAIL"
    elif warnings:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"
    payload = {
        "status": status,
        "checked_public_candidate_files": len(checked_files),
        "failures": failures,
        "warnings": warnings,
        "gate3_run_id": gate3["run_id"],
        "gate4_run_id": gate4["run_id"],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Public release check: {status}")
    print(f"Checked files: {len(checked_files)}; failures: {len(failures)}; warnings: {len(warnings)}")
    print(f"Report: {REPORT_PATH}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
