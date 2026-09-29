# ORION — Phase 0 setup (walking skeleton)

Goal: prove that a local model can reliably call a tool through MCP,
end to end, before anything else gets built on top of it. All
commands below are PowerShell, for your Windows machine.

## 1. Install Ollama

1. Download from https://ollama.com/download and run the Windows installer.
2. It installs as a background service — you don't need to manually
   start a server. Confirm it's running:
   ```powershell
   ollama --version
   ```

## 2. Pull the model

```powershell
ollama pull qwen3:8b
```

This is ~5-6GB and should fit comfortably in your 8GB VRAM. If tool
calls turn out flaky in step 6, also pull the alternative and swap
`MODEL` in `core/orchestrator.py`:

```powershell
ollama pull qwen3.5:9b
```

Sanity-check the model loads and responds:
```powershell
ollama run qwen3:8b "say hello in five words"
```
(Type `/bye` to exit.)

## 3. Set up the Python project

From inside this `orion-beta` folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks the activation script with an execution-policy
error, run this once (as your normal user, not admin):
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 4. Sanity-check the MCP server on its own

Before wiring it to Ollama, confirm the filesystem server itself
runs without errors:
```powershell
python mcp_servers\filesystem_server.py
```
It should sit there waiting (stdio transport has no output when
idle) — that's correct. Press `Ctrl+C` to stop it. This step just
rules out an import/syntax problem before it's harder to debug
underneath the full loop.

## 5. Run ORION

```powershell
uvicorn api:app --host 0.0.0.0 --reload --reload-dir core --reload-dir mcp_servers --reload-dir config --reload-dir interfaces
```

`--host 0.0.0.0` (rather than the default 127.0.0.1-only) is what makes
ORION reachable from a phone on the same Wi-Fi/LAN — see the NETWORK tab
for the exact URL to open there once the server's running. The first
time you do this, Windows Firewall will prompt to allow Python through
on private networks — allow it, or the phone won't be able to connect.
The explicit `--reload-dir` list matters too: the coding tools write into
`./workspace` and SQLite writes into `./data` during normal operation —
without this allowlist, `--reload`'s file watcher (which defaults to the
whole project) treats every tool call as a source change and restarts
the whole server mid-request.

You should see a log line like:
```
[orion] connected to filesystem MCP server, 2 tool(s) available
```
That line is the first real milestone — it means the orchestrator
successfully spawned the MCP server and got its tool list back.

## 6. Test it

Open a second PowerShell window (keep the server running in the
first), activate the venv again, and run:
```powershell
.venv\Scripts\Activate.ps1
python test_chat.py
```

Expect: the model lists `welcome.txt` for the first question, and
correctly summarizes its contents for the second — meaning it chose
to call `list_files`, then `read_file`, on its own, and used the
results correctly.

You can also poke it manually at http://localhost:8000/docs — FastAPI's
built-in interactive test page.

## What "done" looks like for Phase 0

- [ ] Ollama installed, model pulled, responds to a plain prompt
- [ ] `filesystem_server.py` runs standalone with no errors
- [ ] `uvicorn api:app` starts and logs the tool count
- [ ] `test_chat.py` gets correct answers to both questions, and the
      terminal running uvicorn shows `[orion] tool call: ...` lines
      proving it actually used the tools rather than guessing

## If something breaks

Tool-calling message formats between Ollama and MCP shift slightly
across versions, and I can't run this on your exact machine to
pre-verify it — so the most likely failure point is the shape of
the message we send back to Ollama after a tool runs (in
`orchestrator.py`, the `messages.append({"role": "tool", ...})`
line). If you hit an error there, paste the traceback and we'll fix
the schema together — it's a small, contained fix, not a redesign.

## Once this works

Tell me, and we'll move to Phase 1: conversation memory (SQLite),
the minimal web chat UI, and permission tiers on top of this same
loop.
