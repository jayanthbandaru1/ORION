"""
Shared test setup.

Every MCP server module is literally named server.py (mcp_servers/
calendar/server.py, mcp_servers/gmail/server.py, ...) — importing two
of them the way they import themselves at runtime (sys.path insert +
`import server`) would collide in sys.modules under the same name
'server' once more than one test file does it in the same pytest
session. load_server_module() loads each one under its own unique
name instead.
"""

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_server_module(unique_name: str, relative_path: str):
    path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(unique_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module
