"""Release notes for a version, from CHANGELOG.md. Used by .github/workflows/release.yml.

    python scripts/release_notes.py 0.1.0 --out notes.md

Fails if the version doesn't match pyproject.toml and winauto/__init__.py, or
CHANGELOG.md has no section for it. Relative links are made absolute so they
work on the GitHub release page.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "AadityaX86/WinAuto"


class ReleaseError(Exception):
    pass


def project_versions() -> dict[str, str]:
    pyproject = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    package = re.search(r'^__version__\s*=\s*"([^"]+)"', (ROOT / "winauto" / "__init__.py").read_text(encoding="utf-8"), re.M)
    return {"pyproject.toml": pyproject.group(1) if pyproject else "", "winauto/__init__.py": package.group(1) if package else ""}


def changelog_section(version: str, changelog: str) -> str:
    m = re.search(rf"^## {re.escape(version)}\b[^\n]*\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    if not m or not m.group(1).strip():
        raise ReleaseError(f"CHANGELOG.md has no section for {version}. Add '## {version} (date)' with the changes.")
    return m.group(1).strip()


def absolute_links(text: str, repo: str, ref: str) -> str:
    """docs/x.md -> https://github.com/<repo>/blob/<ref>/docs/x.md (images use raw links)."""

    def fix(m: re.Match) -> str:
        bang, label, target = m.group(1), m.group(2), m.group(3)
        if re.match(r"[a-z]+:|#", target):
            return m.group(0)
        kind = "raw" if bang else "blob"
        return f"{bang}[{label}](https://github.com/{repo}/{kind}/{ref}/{target.lstrip('./')})"

    return re.sub(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)", fix, text)


def render(version: str, repo: str = DEFAULT_REPO) -> str:
    version = version.strip().removeprefix("v")
    mismatched = {f: v for f, v in project_versions().items() if v != version}
    if mismatched:
        found = ", ".join(f"{f} says {v or 'nothing'}" for f, v in mismatched.items())
        raise ReleaseError(f"Releasing {version}, but {found}. Bump the version first.")
    section = changelog_section(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    tag = f"v{version}"
    header = f"""## Download

| File | |
|---|---|
| **WinAuto-{version}-windows.zip** | Recommended. Unzip it somewhere permanent (e.g. `C:\\Apps\\WinAuto`) and run `WinAuto.exe`. |
| **WinAuto-{version}.exe** | The same app as a single file, nothing to unzip. Takes a few seconds longer to start. |

WinAuto's AI runs on your PC through [Ollama](https://ollama.com/download): install it and run `ollama pull qwen3:8b` first. \
Full steps: [Getting started](docs/getting-started.md).

Windows may say "Windows protected your PC" because the app isn't code-signed: click **More info → Run anyway**. \
`SHA256SUMS.txt` lists the files' checksums.

## What's new

"""
    return absolute_links(header + section, repo, tag) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="e.g. 0.1.0 or v0.1.0")
    parser.add_argument("--out", type=Path, help="write the notes here (default: print them)")
    args = parser.parse_args()
    try:
        notes = render(args.version, os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO))
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.out:
        args.out.write_text(notes, encoding="utf-8")
    else:
        print(notes)
    version = args.version.strip().removeprefix("v")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"version={version}\ntag=v{version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
