"""Keep requirements.txt in step with pyproject.toml.

The Docker build needs to install dependencies *before* copying the source, so the
dependency layer caches across code changes. That means a plain list of
requirements, separate from pyproject. Two files listing versions is a drift risk,
so this script regenerates one from the other and CI checks the result is current.

pyproject.toml stays the single source of truth. Edit it, run this, commit both.
"""

from __future__ import annotations

import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]

HEADER = """# Generated from pyproject.toml — the single source of truth for versions.
# This file exists only so the Docker build can install dependencies before the
# source is copied, which keeps the dependency layer cached across code changes.
# Regenerate with: python scripts/sync_requirements.py
"""


def render() -> tuple[str, str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    runtime = data["project"]["dependencies"]
    dev = data["project"]["optional-dependencies"]["dev"]
    return (
        HEADER + "\n".join(runtime) + "\n",
        HEADER + "-r requirements.txt\n" + "\n".join(dev) + "\n",
    )


def main() -> int:
    runtime, dev = render()
    check = "--check" in sys.argv
    drifted = []

    for name, content in (("requirements.txt", runtime), ("requirements-dev.txt", dev)):
        path = ROOT / name
        current = path.read_text() if path.exists() else ""
        if current == content:
            continue
        if check:
            drifted.append(name)
        else:
            path.write_text(content)
            print(f"wrote {name}")

    if check and drifted:
        print(f"out of date: {', '.join(drifted)}")
        print("run `python scripts/sync_requirements.py` and commit the result")
        return 1
    if check:
        print("requirements files match pyproject.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
