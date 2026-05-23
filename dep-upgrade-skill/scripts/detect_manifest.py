#!/usr/bin/env python3
"""Detect package manifests in a repo and report ecosystems + dependency versions.

Walks the given path (default cwd, non-recursive — manifests are root-level by
convention) and reports each manifest's ecosystem + the locked-or-declared
version for each dependency.

Stdlib only. tomllib is 3.11+; falls back to a tiny scan for 3.10.

Output JSON:
{
  "manifests": [
    {
      "path": "package.json",
      "ecosystem": "npm",
      "dependencies": {"react": "18.2.0", "express": "^4.18.0", ...}
    }, ...
  ]
}

Usage:
    python detect_manifest.py              # scan cwd
    python detect_manifest.py /path/to/repo
    python detect_manifest.py --package react   # filter to one dep
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
    tomllib = None  # type: ignore[assignment]


def _read_npm(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = data.get(key) or {}
        if isinstance(block, dict):
            for name, ver in block.items():
                if isinstance(name, str) and isinstance(ver, str):
                    deps[name] = ver
    return {"path": path.name, "ecosystem": "npm", "dependencies": deps}


def _read_pyproject(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return None
    else:
        return _read_pyproject_fallback(text)
    deps: dict[str, str] = {}
    project = data.get("project") or {}
    for spec in project.get("dependencies") or []:
        name, ver = _split_pep508(spec)
        if name:
            deps[name] = ver
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, dict):
        for group in optional.values():
            for spec in group or []:
                name, ver = _split_pep508(spec)
                if name:
                    deps[name] = ver
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for name, ver in (poetry.get("dependencies") or {}).items():
        if name == "python":
            continue
        if isinstance(ver, str):
            deps[name] = ver
        elif isinstance(ver, dict) and "version" in ver:
            deps[name] = str(ver["version"])
    return {"path": path.name, "ecosystem": "pypi", "dependencies": deps}


def _read_pyproject_fallback(text: str) -> dict | None:
    deps: dict[str, str] = {}
    for m in re.finditer(r"^\s*\"([A-Za-z0-9_.-]+)\s*([^\"]*)\"", text, re.M):
        name, ver = m.group(1), m.group(2).strip()
        deps[name] = ver
    return {"path": "pyproject.toml", "ecosystem": "pypi", "dependencies": deps}


def _split_pep508(spec: str) -> tuple[str, str]:
    """Split 'requests>=2.31,<3' into ('requests', '>=2.31,<3'). Stdlib-friendly."""
    m = re.match(r"^\s*([A-Za-z0-9_.\-]+)(\s*\[[^\]]*\])?\s*(.*)$", spec)
    if not m:
        return ("", "")
    return (m.group(1), m.group(3).strip().rstrip(";").strip())


def _read_cargo(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if tomllib is None:
        # 3.10 fallback: regex scan inside [dependencies] tables.
        deps: dict[str, str] = {}
        for table_match in re.finditer(
            r"^\[(?:dependencies|dev-dependencies|build-dependencies)\]\s*\n((?:.|\n)*?)(?=^\[|\Z)",
            text,
            re.M,
        ):
            for line in table_match.group(1).splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=\s*\"([^\"]+)\"", line)
                if m:
                    deps[m.group(1)] = m.group(2)
        return {"path": path.name, "ecosystem": "cargo", "dependencies": deps}
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    deps = {}
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        block = data.get(key) or {}
        for name, ver in block.items():
            if isinstance(ver, str):
                deps[name] = ver
            elif isinstance(ver, dict) and "version" in ver:
                deps[name] = str(ver["version"])
    return {"path": path.name, "ecosystem": "cargo", "dependencies": deps}


def _read_package_lock(path: Path) -> dict | None:
    """Parse an npm `package-lock.json` (v2/v3 schema).

    Yields exact installed versions from the `packages` map (not the
    semver ranges in `dependencies` / `devDependencies` of package.json).
    Use this when you need to know what's actually in `node_modules`,
    which is what upgrade-impact analysis really wants.

    Keys in the `packages` dict are like `node_modules/react` for top-
    level deps and `node_modules/<a>/node_modules/<b>` for nested ones.
    The last `node_modules/` segment names the package; if the same
    package appears at multiple depths with different versions, the
    last one wins (matching how Node resolves at runtime).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    packages = data.get("packages") or {}
    if not isinstance(packages, dict):
        return {"path": path.name, "ecosystem": "npm-lock", "dependencies": {}}
    deps: dict[str, str] = {}
    for key, entry in packages.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if "node_modules/" not in key:
            continue
        name = key.rsplit("node_modules/", 1)[-1]
        if not name:
            continue
        version = entry.get("version")
        if isinstance(version, str) and version:
            deps[name] = version
    return {"path": path.name, "ecosystem": "npm-lock", "dependencies": deps}


def _read_gomod(path: Path) -> dict | None:
    """Parse a Go `go.mod` file.

    Pulls dependencies from `require` blocks (both the parenthesized
    block form and single-line `require X v0.0.0` form). Lines marked
    `// indirect` are excluded — those aren't direct dependencies and
    bumping them via upgrade-impact would be misleading.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    deps: dict[str, str] = {}

    def _absorb(line: str) -> None:
        # Strip comments after `//`.
        if "//" in line and "indirect" in line.split("//", 1)[1]:
            return
        body = line.split("//", 1)[0].strip()
        if not body:
            return
        parts = body.split()
        if len(parts) < 2:
            return
        module, version = parts[0], parts[1]
        deps[module] = version

    # Multi-line `require (` block.
    for block_match in re.finditer(r"^require\s*\(\s*\n((?:.|\n)*?)^\)", text, re.M):
        for raw_line in block_match.group(1).splitlines():
            _absorb(raw_line)

    # Single-line `require <module> <version>`.
    for line in text.splitlines():
        m = re.match(r"^\s*require\s+(\S+)\s+(\S+)(?:\s*//.*)?$", line)
        if m:
            mod = m.group(1)
            # Skip when it's the block opener.
            if mod == "(":
                continue
            ver = m.group(2)
            if "//" in line and "indirect" in line.split("//", 1)[1]:
                continue
            deps[mod] = ver

    return {"path": path.name, "ecosystem": "gomod", "dependencies": deps}


def _read_composer(path: Path) -> dict | None:
    """Parse a PHP `composer.json`.

    Pulls from both `require` and `require-dev`. The `php` runtime
    constraint itself is dropped — composer treats it as a dep but
    upgrade-impact analysis would only do dumb things with it.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    deps: dict[str, str] = {}
    for key in ("require", "require-dev"):
        block = data.get(key) or {}
        if not isinstance(block, dict):
            continue
        for name, ver in block.items():
            if not isinstance(name, str) or not isinstance(ver, str):
                continue
            # Skip the PHP runtime constraint and platform-style "ext-*" entries.
            if name == "php" or name.startswith("ext-") or name.startswith("lib-"):
                continue
            deps[name] = ver
    return {"path": path.name, "ecosystem": "composer", "dependencies": deps}


READERS = {
    "package.json": _read_npm,
    "package-lock.json": _read_package_lock,
    "pyproject.toml": _read_pyproject,
    "Cargo.toml": _read_cargo,
    "composer.json": _read_composer,
    "go.mod": _read_gomod,
}


def detect(root: Path) -> list[dict]:
    out: list[dict] = []
    for name, reader in READERS.items():
        path = root / name
        if not path.is_file():
            continue
        manifest = reader(path)
        if manifest is not None:
            out.append(manifest)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Detect package manifests + dependency versions.")
    p.add_argument("path", nargs="?", default=".", help="repo root (default: cwd)")
    p.add_argument("--package", help="filter output to one dependency by name")
    args = p.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        return 2

    manifests = detect(root)
    if args.package:
        for m in manifests:
            m["dependencies"] = {k: v for k, v in m["dependencies"].items() if k == args.package}
        manifests = [m for m in manifests if m["dependencies"]]

    json.dump({"manifests": manifests}, sys.stdout, indent=2)
    print()
    return 0 if manifests else 1


if __name__ == "__main__":
    sys.exit(main())
