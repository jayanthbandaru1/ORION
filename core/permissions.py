"""
ORION's permission-tier lookup.

Look up each tool's tier and log it before the call runs. Phase 4 adds
real interactive confirmation for SENSITIVE/DESTRUCTIVE tools on top of
this same lookup — through Phase 2/3 those tiers are logged but not
yet blocked (see the working agreement in CLAUDE.md for why real
side-effecting calls get a human check-in manually in the meantime).
"""

from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "permissions.yaml"

# Unknown tools default to the most cautious tier until someone
# classifies them in config/permissions.yaml.
DEFAULT_TIER = "DESTRUCTIVE"


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_CONFIG = _load_config()


def get_tier(tool_name: str) -> str:
    tier = _CONFIG.get(tool_name, DEFAULT_TIER)
    # run_command_allowlist is config, not a tool — never mistake it for one.
    return tier if isinstance(tier, str) else DEFAULT_TIER


def classify_tool_call(tool_name: str, args: dict) -> str:
    """Like get_tier, but with a per-argument override for run_command: SAFE
    when its first word is on the allowlist, SENSITIVE otherwise. Everything
    else is a plain per-tool-name lookup — see PHASE2.md for why run_command
    alone needs this nuance."""
    if tool_name == "run_command":
        command = str(args.get("command", "")).strip()
        first_word = command.split()[0] if command else ""
        allowlist = _CONFIG.get("run_command_allowlist") or []
        if first_word in allowlist:
            return "SAFE"
    return get_tier(tool_name)
