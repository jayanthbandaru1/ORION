"""
ORION's coding-tools MCP server.

Sandboxed to ./workspace, the same scoping pattern Phase 0's
filesystem_server.py established — no unrestricted machine access.
run_command is SENSITIVE by default; core/permissions.py grants it SAFE
only when the command's first token is on the allowlist in
config/permissions.yaml (pytest/python/git to start).
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from fastmcp import FastMCP

WORKSPACE_ROOT = (Path(__file__).parent.parent.parent / "workspace").resolve()
WORKSPACE_ROOT.mkdir(exist_ok=True)

# `python` on this machine's PATH resolves to the (non-functional)
# Microsoft Store stub, not the project venv — see SETUP.md. Put the
# venv's own Scripts dir first so run_command/run_tests actually find
# the real python/pytest instead of failing mysteriously.
_VENV_SCRIPTS = Path(sys.executable).parent
_SUBPROCESS_ENV = {**os.environ, "PATH": f"{_VENV_SCRIPTS}{os.pathsep}{os.environ.get('PATH', '')}"}

mcp = FastMCP(
    name="orion-coding",
    instructions="Read, search, and edit code inside the sandboxed workspace directory, and run commands/tests there. Nothing outside the workspace is reachable.",
)


def _resolve(relative_path: str) -> Path:
    """Resolve a path and refuse anything that escapes the workspace."""
    target = (WORKSPACE_ROOT / relative_path).resolve()
    if WORKSPACE_ROOT not in target.parents and target != WORKSPACE_ROOT:
        raise ValueError(f"'{relative_path}' resolves outside the workspace directory")
    return target


def _run(args: list[str], timeout: int = 60) -> dict:
    if args:
        # subprocess.run's executable search on Windows uses this
        # process's own PATH, not the env= dict handed to the child —
        # so a venv-only tool like pytest never resolves via env alone.
        # Resolve it ourselves against the PATH we actually want.
        resolved = shutil.which(args[0], path=_SUBPROCESS_ENV["PATH"])
        if resolved:
            args = [resolved, *args[1:]]

    try:
        proc = subprocess.run(
            args,
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_SUBPROCESS_ENV,
            # Without this, the child inherits this server's own stdin —
            # the MCP stdio pipe to the orchestrator — and can hang
            # waiting on a pipe that will never see EOF or new input.
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
    except FileNotFoundError as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}
    return {"returncode": proc.returncode, "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-4000:]}


@mcp.tool()
def code_list_files(subdirectory: str = ".") -> list[str]:
    """List file and folder names inside the coding workspace (or a subdirectory of it).
    Named distinctly from the Phase 0 filesystem server's list_files — Ollama's tool
    namespace is flat across every connected MCP server, so identical names would collide."""
    target = _resolve(subdirectory)
    if not target.is_dir():
        raise ValueError(f"'{subdirectory}' is not a directory")
    return sorted(p.name for p in target.iterdir() if p.name != ".git")


@mcp.tool()
def code_read_file(path: str) -> str:
    """Read and return the text contents of a file in the coding workspace."""
    target = _resolve(path)
    if not target.is_file():
        raise ValueError(f"'{path}' is not a file")
    return target.read_text(encoding="utf-8")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file in the workspace with the given content. SENSITIVE."""
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}"


@mcp.tool()
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Replace old_string with new_string in a file. old_string must appear
    exactly once — this mirrors a precise find-and-replace, not a bulk edit. SENSITIVE."""
    target = _resolve(path)
    if not target.is_file():
        raise ValueError(f"'{path}' is not a file")

    text = target.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        raise ValueError("old_string not found in file")
    if count > 1:
        raise ValueError(f"old_string is not unique — found {count} occurrences, need exactly 1")

    target.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
    return f"Edited {path}"


@mcp.tool()
def search_code(pattern: str, subdirectory: str = ".") -> list[dict]:
    """Regex-search text files under the workspace (or a subdirectory) for a pattern.
    Returns up to 200 matches as {file, line, text}."""
    target = _resolve(subdirectory)
    regex = re.compile(pattern)
    matches = []

    for path in target.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, start=1):
            if regex.search(line):
                matches.append({"file": str(path.relative_to(WORKSPACE_ROOT)), "line": i, "text": line.strip()})
                if len(matches) >= 200:
                    return matches
    return matches


def _shell_split(command: str) -> list[str]:
    import shlex

    # posix=False keeps this sane for Windows-style paths/flags.
    return shlex.split(command, posix=(sys.platform != "win32"))


@mcp.tool()
def run_command(command: str) -> dict:
    """Run a shell command inside the workspace directory. SENSITIVE unless the
    command's first word is allowlisted (pytest/python/git), per config/permissions.yaml."""
    return _run(_shell_split(command))


@mcp.tool()
def run_tests() -> dict:
    """Run pytest across the workspace. SAFE — read-only from the outside world's perspective."""
    return _run(["pytest", "-q"])


@mcp.tool()
def git_status() -> dict:
    """git status in the workspace."""
    return _run(["git", "status"])


@mcp.tool()
def git_diff(path: str | None = None) -> dict:
    """git diff in the workspace, optionally scoped to one path."""
    args = ["git", "diff"]
    if path:
        args.append(path)
    return _run(args)


@mcp.tool()
def git_log(max_count: int = 10) -> dict:
    """git log in the workspace, most recent first."""
    return _run(["git", "log", f"-{max_count}", "--oneline"])


if __name__ == "__main__":
    mcp.run()
