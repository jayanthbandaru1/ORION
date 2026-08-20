"""
ORION's first MCP server: read-only filesystem access, scoped to
./sandbox so there's no way for the model to reach anything else
on the machine during Phase 0.

Run standalone for debugging:
    python mcp_servers/filesystem_server.py

Normally it's launched as a subprocess by core/orchestrator.py.
"""

from pathlib import Path

from fastmcp import FastMCP

SANDBOX_ROOT = (Path(__file__).parent.parent / "sandbox").resolve()
SANDBOX_ROOT.mkdir(exist_ok=True)

mcp = FastMCP(
    name="orion-filesystem",
    instructions="Read-only access to files inside ORION's sandbox directory.",
)


def _resolve(relative_path: str) -> Path:
    """Resolve a path and refuse anything that escapes the sandbox."""
    target = (SANDBOX_ROOT / relative_path).resolve()
    if SANDBOX_ROOT not in target.parents and target != SANDBOX_ROOT:
        raise ValueError(f"'{relative_path}' resolves outside the sandbox directory")
    return target


@mcp.tool()
def list_files(subdirectory: str = ".") -> list[str]:
    """List file and folder names inside the sandbox directory (or a subdirectory of it)."""
    target = _resolve(subdirectory)
    if not target.is_dir():
        raise ValueError(f"'{subdirectory}' is not a directory")
    return sorted(p.name for p in target.iterdir())


@mcp.tool()
def read_file(path: str) -> str:
    """Read and return the text contents of a file inside the sandbox directory."""
    target = _resolve(path)
    if not target.is_file():
        raise ValueError(f"'{path}' is not a file")
    return target.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport
