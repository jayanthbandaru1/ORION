"""
ORION's broader personal-file search server — separate from
mcp_servers/coding/, which stays scoped to ./workspace on purpose (the
coding agent's own sandbox, unrelated to the user's actual documents).
This is for natural-language personal-file requests: "find my resume",
"open the ORION architecture document", "what PDFs do I have in
Downloads".

"Authorized locations" is an explicit small allowlist
(config/authorized_paths.yaml), verified to actually exist on this
machine before being listed there — never silent full-drive access.
Every tool resolves the given path and checks it's actually inside one
of those directories before doing anything with it.

Deliberately does NOT expose file *contents* — only names, metadata,
and the ability to open a file in its default application. Reading
arbitrary file bytes is what the already-sandboxed `read_file`/
`code_read_file` tools are for, each scoped to its own narrower root;
this server stays "content-blind" on purpose, which is what makes a
broader personal-directory allowlist reasonable here in the first
place.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "authorized_paths.yaml"
MAX_SEARCH_RESULTS = 50


def _load_authorized_paths() -> list[Path]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return [Path(p).expanduser().resolve() for p in config.get("authorized_paths", [])]


AUTHORIZED_PATHS = _load_authorized_paths()

mcp = FastMCP(
    name="orion-files",
    instructions=(
        "Search, find, and open real personal files by name (Desktop/Documents/Downloads — "
        "see config/authorized_paths.yaml for the exact list) using natural language. "
        "Separate from the coding tools, which stay scoped to the ./workspace sandbox. "
        "This server never returns file contents, only names/metadata, and can open a file "
        "in its default application."
    ),
)


def _require_authorized(path_str: str) -> Path:
    resolved = Path(path_str).expanduser().resolve()
    if not any(resolved == base or base in resolved.parents for base in AUTHORIZED_PATHS):
        allowed = ", ".join(str(p) for p in AUTHORIZED_PATHS)
        raise ValueError(f"'{path_str}' is outside ORION's authorized locations ({allowed}).")
    return resolved


def _entry_info(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
    }


@mcp.tool()
def list_directory(path: str | None = None) -> list[dict]:
    """List files/folders directly inside `path` (defaults to the first authorized
    directory if omitted). Not recursive. READ."""
    target = _require_authorized(path) if path else AUTHORIZED_PATHS[0]
    if not target.is_dir():
        raise ValueError(f"'{target}' is not a directory.")
    return [_entry_info(entry) for entry in sorted(target.iterdir())]


@mcp.tool()
def search_files(query: str, directory: str | None = None) -> list[dict]:
    """Search filenames (case-insensitive substring match) recursively under
    `directory` (defaults to every authorized location if omitted). Capped at
    50 results. READ."""
    query_lower = query.lower()
    roots = [_require_authorized(directory)] if directory else AUTHORIZED_PATHS
    matches: list[dict] = []
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if query_lower in candidate.name.lower():
                matches.append(_entry_info(candidate))
                if len(matches) >= MAX_SEARCH_RESULTS:
                    return matches
    return matches


@mcp.tool()
def find_file(filename: str) -> list[dict]:
    """Find file(s) whose name matches `filename` exactly (case-insensitive),
    anywhere under the authorized locations. READ."""
    filename_lower = filename.lower()
    matches: list[dict] = []
    for root in AUTHORIZED_PATHS:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if candidate.is_file() and candidate.name.lower() == filename_lower:
                matches.append(_entry_info(candidate))
    return matches


@mcp.tool()
def get_file_metadata(path: str) -> dict:
    """Real metadata (size, last-modified time, file vs. directory) for a path.
    Never the file's contents. READ."""
    target = _require_authorized(path)
    if not target.exists():
        raise ValueError(f"'{target}' does not exist.")
    stat = target.stat()
    return {
        "path": str(target),
        "is_dir": target.is_dir(),
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


@mcp.tool()
def open_file(path: str) -> str:
    """Open a file with the user's default application for it (e.g. a PDF opens
    in the default PDF viewer). SENSITIVE — this launches a real external
    program; confirm with the user before calling this for real."""
    target = _require_authorized(path)
    if not target.exists():
        raise ValueError(f"'{target}' does not exist.")
    if sys.platform == "win32":
        os.startfile(str(target))  # noqa: S606 — this tool's entire purpose is launching the default app
    elif sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=True)
    else:
        subprocess.run(["xdg-open", str(target)], check=True)
    return f"Opened {target}"


if __name__ == "__main__":
    mcp.run()
