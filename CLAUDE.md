# ORION — project context for Claude Code

This file is the living, current source of truth for the project. Where
it conflicts with an earlier phase doc, this file wins. It's written
long and detailed on purpose — the original planning document was
specific, and compressing it into short bullets across revisions kept
losing that specificity. This version restores it.

## What ORION is

ORION — Omni-Responsive Intelligence & Operations Nexus — is a
local-first personal AI operating system. Not a chatbot: an agentic
system that understands natural language, reasons about tasks, selects
appropriate tools, executes multi-step workflows, maintains long-term
memory, interacts with the digital environment, accesses current
internet information, assists with software development, and
proactively helps with personal life.

**Core principle: one central intelligence.** There is exactly one
ORION agent/brain. Voice, text, and vision are interfaces into that
same agent — not separate assistants. All interfaces share the same
memory, tools, permissions, and context. Do not build a "voice ORION"
and a "coding ORION" as if they were different things; they're the
same agent through different doors.

## LLM requirements

The primary LLM runs locally. It should not need unrestricted internet
access itself — internet access is mediated entirely through
controlled tools (the MCP servers), never raw model access to the web.
The model must be capable of reasoning, tool selection, coding,
summarization, planning, and multi-step tasks, and must be swappable —
never permanently tied to one model or vendor. This is why
`core/llm_provider.py` exists as an abstraction layer rather than
Ollama calls being scattered through the orchestrator directly.

Current pick: `qwen3:8b` via Ollama, `qwen3.5:9b` as a fallback to test
if tool-calling proves unreliable — chosen specifically for the
RTX 4060 Mobile's 8GB VRAM ceiling, not because it's the best model in
the abstract. When the MacBook Pro M5 comes online, its model choice
should be re-evaluated on its own hardware terms, not assumed to
inherit the Windows machine's pick.

## Interfaces

### Text
Full text interface: type messages, see responses, view conversation
history, see tool activity when appropriate, inspect results, approve
or reject actions, view code changes, interact with ongoing tasks,
upload relevant files/images. Talks to the same central agent as every
other interface — see `interfaces/web/index.html` and PHASE1.md.

### Voice
Not a replacement for text — both exist simultaneously, always.
Requirements: microphone input, speech recognition, natural
conversational interaction, spoken responses, interruption handling
where practical, configurable voice, wake-word support, voice/text
conversation continuity, low-latency interaction where practical.
Example from the original spec: "ORION, what's on my calendar
tomorrow?" — ORION retrieves calendar information and responds
verbally, and the same interaction appears in the text conversation
history. Implementation: faster-whisper (STT) + Kokoro-82M (TTS), push
to talk for the beta, wake-word deferred (see Foundations below). See
PHASE3.md when we get there.

### Vision
Image understanding, camera input, screenshot understanding, computer
screen understanding, UI interpretation, visual question answering.
Example: "ORION, what's wrong with this error?" — ORION inspects a
screenshot and explains it. Eventually ORION should understand the
current computer screen when authorized. **Not built in the beta** —
see Foundations below for what "foundation" means here specifically.

## Personal life integration

Priority integrations: Notion Calendar (via the Google Calendar
account it's connected to — see below), Gmail, tasks/reminders.

### Calendar — important technical note

Notion Calendar has no API of its own. It's a viewer/aggregator that
displays and lets you create events in whichever external calendar
account you've connected to it — Google, Outlook, or iCloud. This
project's account is Google, so ORION talks to the **Google Calendar
API** directly. Anything ORION creates or edits there appears in
Notion Calendar automatically, since Notion Calendar is just mirroring
that account. This is exactly the fallback the original spec asked
for: "if Notion Calendar relies on a connected calendar provider for
particular functionality, use the appropriate officially supported
integration rather than creating a duplicate calendar system."

Capabilities (from the original spec, all in scope for the beta):
read calendar events, search events, view upcoming events, identify
free time, identify conflicts, create events, modify events, delete
events, move/reschedule events, schedule tasks into available time,
summarize the schedule, combine calendar information with Gmail,
tasks, and reminders. Autonomous scheduling per learned preferences is
explicitly **post-beta**.

Conceptual tools (implemented as one MCP server, `mcp_servers/calendar/`):
```
calendar_get_events()
calendar_search()
calendar_find_free_time()
calendar_create_event()
calendar_update_event()
calendar_delete_event()
```

Example interactions the original spec gives, which are the actual
acceptance criteria for "does this work":
- "What's my schedule tomorrow?" → ORION checks Google Calendar and
  returns upcoming events.
- "Find me two free hours tomorrow afternoon to work on ORION." →
  ORION checks the calendar, finds available time, considers existing
  tasks/preferences, proposes a time, and creates the event if
  authorized.

The calendar integration is modular — not tightly coupled to the core
agent. It's a Google Calendar MCP server, full stop; if the connected
provider ever changes to Outlook or iCloud, only that server changes.

### Gmail

Gmail is a first-class ORION tool via the official Gmail API and OAuth
authentication. Capabilities: read emails, search emails, filter
emails, summarize emails, classify emails, identify important emails,
identify emails requiring responses, inspect email threads, create
drafts, edit drafts, reply to emails, send emails. Fully autonomous
email actions (auto-sending without review) are explicitly **not**
beta scope — every send stays behind the SENSITIVE permission tier.

Conceptual tools (`mcp_servers/gmail/`):
```
gmail_search()
gmail_get_message()
gmail_get_thread()
gmail_create_draft()
gmail_update_draft()
gmail_send_draft()
```

Example interactions:
- "Find emails I need to respond to." → ORION searches Gmail, analyzes
  relevant messages, presents them.
- "Draft a response to John saying I'll finish it tomorrow." → ORION
  identifies the relevant conversation and creates a Gmail draft.
- "Send it." → ORION sends the approved draft — this is a SENSITIVE
  action per the permission model below; never auto-confirmed.

Never hardcode Gmail credentials or OAuth secrets — they live in
`.env`, which is gitignored, never in any doc in this repo.

### Cross-application personal context

This is a distinct requirement, not just "have both integrations
installed": ORION should reason across Calendar, Gmail, tasks, and
reminders together, not expose them as isolated APIs the user has to
manually cross-reference themselves. Examples from the spec:
- "What do I have going on tomorrow?" → combines calendar events,
  Gmail messages, tasks, reminders, and upcoming deadlines into one
  answer.
- "Do I have time tomorrow to meet with Sarah?" → inspects the
  calendar, identifies free time, searches Gmail if relevant, suggests
  times, creates the event if authorized.
- "Find the emails I need to respond to before tomorrow's meetings." →
  inspects tomorrow's calendar, identifies relevant meetings, searches
  Gmail, identifies relevant messages, summarizes what needs attention.

This capability isn't a separate tool — it's the model's own reasoning
across the results of multiple tool calls in one turn. The system
prompt and the model's general competence at multi-step tool use (the
thing Phase 0 specifically validated) are what make this work, not
additional plumbing.

### Tasks and reminders

Capabilities: create task, update task, complete task, delete task,
set due dates, priorities, reminders, notifications, recurring tasks.
Tasks should interact with the calendar where appropriate — example
from the spec: "I need to study for three hours this weekend" should
result in ORION identifying available time in the calendar and
proposing or scheduling study blocks, not just creating a bare task
row.

## Coding agent

Must be capable of interacting with actual repositories, not just
generating snippets. Required tools:
```
list_files()
read_file()
write_file()
edit_file()
search_code()
run_command()
run_tests()
git_status()
git_diff()
git_log()
```
Potential future tools (post-beta): `create_branch()`, `commit()`,
`open_pull_request()`, `inspect_dependencies()`,
`search_documentation()`.

Workflow the tools should support: understand the request → inspect
the repository → find relevant code → reason about the problem →
modify code → run tests → inspect failures → modify again → run tests
again → verify the solution → show the user the changes. ORION should
eventually be able to work on its own source code — this project's own
repo is a valid future target for the coding agent, once it exists.

**Sandbox constraint**: no unrestricted machine access by default.
Restricted workspace, permission-controlled filesystem access, command
allowlists where appropriate, confirmation for potentially destructive
actions. This is the same sandboxing pattern already established in
Phase 0's `filesystem_server.py` — the coding tools extend it, they
don't introduce a new one.

## Foundations built during the beta

The original spec asks for architectural foundations — not full
builds — for several post-beta features. Specific, not hand-waved:

- **Autonomous workflows** — genuinely founded already. The permission
  tier system (READ → SAFE → REVERSIBLE → SENSITIVE → DESTRUCTIVE,
  config-driven per tool, see Permission model below) is exactly the
  safety layer multi-step autonomy needs. Nothing extra required.
- **Phone integration** — genuinely founded already, structurally. The
  FastAPI/WebSocket API is client-agnostic; a phone app is just
  another client hitting `/chat`. The original spec frames this
  correctly: "the phone should become another ORION interface rather
  than a separate assistant" — that's already true of the API design.
- **Vision, computer control, smart-home** — foundation is the MCP
  server pattern itself. Each slots in later as its own
  `mcp_servers/` entry through the same tool-call and permission-tier
  pipeline filesystem/calendar/gmail/tasks/coding already use.
- **Wake word** — Phase 3 ships push-to-talk; the audio-input
  abstraction should make an always-listening wake-word detector an
  addition later, not a rewrite. The detector itself isn't beta work.
- **Proactive behavior, notifications** — honestly, no foundation
  exists yet. Example from the spec of what this eventually looks
  like: "You have a meeting in 20 minutes and three failing tests in
  your ORION project. I recommend fixing the authentication test
  first." That requires a background scheduler/event loop — a
  different shape of problem than the request/response tool pattern
  everything else uses. Real post-beta design work.
- **Meta AI glasses** — the original spec explicitly allows this to be
  fully deferred with no foundation work if the timeline is tight, and
  explicitly requires using only official Meta APIs/SDKs if it's ever
  built — no reverse-engineering, no private interfaces. Taking the
  defer option for now.

## Permission model

Five tiers, exactly as specified: READ → SAFE ACTION → REVERSIBLE
ACTION → SENSITIVE ACTION → DESTRUCTIVE ACTION.

- **Safe** (no confirmation): read calendar, search web, read files,
  search Gmail.
- **Sensitive** (confirmation recommended): create calendar event,
  create email draft, modify a task.
- **Confirmation required**: send email, modify an important calendar
  event, execute a potentially destructive command.
- **Strong confirmation**: delete data, destructive filesystem
  operations, financial transactions, irreversible external actions.

Implementation: `config/permissions.yaml` maps each tool to a tier;
`core/permissions.py` enforces it before every tool call and logs the
tier; the JARVIS UI renders the tier on every tool-call log line so
this is visible, not buried in a terminal. Interactive confirmation
UI for SENSITIVE/DESTRUCTIVE actions is Phase 4 — until then those
tiers are logged but not blocked, which is why the working agreement
below requires a human check before exercising them for real, even
during Claude Code's own testing.

## Memory

Categories, per the original spec: conversation history, user
preferences, personal context, projects, tasks, previous actions,
important facts, semantic/vector memory. Memory should be selectively
stored, not blindly logging everything — the architecture should allow
the implementation to evolve. Current implementation: SQLite for
structured memory (Phase 1); Chroma for semantic/vector memory,
deferred to post-beta per that same "let it evolve" principle.

## Personality

ORION has a specific character, and it needs to reach actual
responses, not just live in this file:
- Highly intelligent, confident, analytical, calm
- Slightly intimidating / futuristic in tone — operating a level above
  the conversation, not chasing approval
- Occasional dry, understated humor — sparing, not constant
- Proactive: surfaces relevant information unprompted when it
  genuinely matters (a calendar conflict, a failing test)
- Not blindly agreeable — pushes back on bad ideas or risky actions
  instead of just executing them
- Useful first, character second — a witty wrong answer is still wrong

This must be sent as a system prompt on every Ollama call:

```python
ORION_SYSTEM_PROMPT = """You are ORION (Omni-Responsive Intelligence &
Operations Nexus) — a highly capable personal AI operating system.

Voice: confident, analytical, calm, precise. Occasional dry humor is
fine, but don't force it — restraint is part of the character. You are
not obsequious: if a request is a bad idea, say so plainly before doing
it. Be proactive about surfacing things that matter, but don't pad
responses with unnecessary commentary.

You have real tools and real consequences — when you call a tool, you
are actually doing the thing, not describing it."""
```

## UI direction

Should look and feel like JARVIS, not a generic chat app. Reference
implementation: `interfaces/web/index.html` — dark background, cyan
arc-reactor glow, a pulsing "core" that speeds up while processing,
HUD corner brackets, tier-colored tool-call log lines under each
response (this is what makes the permission model above actually
visible). Use it as-is; details in PHASE1.md.

## Architecture principles

Verbatim from the original spec, still binding:
1. Local-first
2. Modular
3. Tool-driven
4. Model-agnostic
5. Permission-aware
6. Extensible
7. Secure by default
8. Reusable components
9. Avoid unnecessary complexity
10. Build for the beta first, then expand
11. Hardware/device integrations should use abstractions
12. No single external platform should become a hard dependency of the
    core ORION system
13. Keep the core system independent from any single LLM provider
14. Design APIs so additional clients can connect later
15. Integrate with the services actually in use rather than forcing
    replacement services
16. Use official APIs and OAuth wherever available

## Development rules

From the original spec's "How I want you to work with me" and
"development rules" sections — these apply to Claude Code's actual
day-to-day work on this repo, not just planning:

- Start from square one; don't assume prior code exists beyond what's
  actually in this repo.
- Establish architecture before implementing major components.
- Don't over-engineer the first version; prioritize working
  functionality over premature optimization.
- Keep modules separated. Use environment variables for secrets, never
  hardcode API keys. Use OAuth for personal service integrations.
- Implement logging and error handling as you go, not as a later pass.
- Write tests for important functionality.
- Keep the system debuggable.
- When providing code: give complete files when practical, verify
  imports and dependencies actually exist, avoid unnecessary
  dependencies, don't invent APIs without verifying they exist.
- When working with external services: verify current official
  documentation, don't assume an API exists, never use
  undocumented/private APIs, account for quotas and rate limits,
  handle authentication failures gracefully.

## Hardware / constraints

- RTX 4060 Mobile laptop GPU, 8GB VRAM, Windows (primary dev machine
  now)
- MacBook Pro M5, 16GB/1TB incoming — will take over the iOS work later
- Local LLM: `qwen3:8b` via Ollama by default; `qwen3.5:9b` as a
  fallback to try if tool-calling is unreliable
- Calendar integration targets the Google Calendar API directly (see
  Personal life integration above for why)

## Stack decisions (don't relitigate these)

- Python/FastAPI backend
- Ollama for the local LLM, abstracted behind `core/llm_provider.py`
- MCP (via the `fastmcp` package) as the tool-calling layer — every
  integration is its own MCP server under `mcp_servers/`
- Web search/fetch: Tavily (official `tavily-python` SDK) — free tier,
  no card required
- SQLite for structured memory; Chroma for vector memory, post-beta
- STT: faster-whisper. TTS: Kokoro-82M
- Permission tiers per the Permission model section above

## Beta goal — minimum experience, verbatim from the spec

> Text + Voice + Local LLM + Web access + Memory + Gmail + Notion
> Calendar + Tasks/Reminders + Coding tools + Permissions

The beta is a convincing vertical slice, not every future feature. It
should also establish the foundations listed above — some genuinely
already exist as a side effect of the architecture, some honestly
don't yet, per that section's specifics.

## Phase roadmap (beta target: 2–3 weeks)

- **Phase 0 — walking skeleton. DONE.** Ollama + one MCP filesystem
  tool + FastAPI, proving the tool-call loop works at all.
- **Phase 1 — core loop, UI, and web access. DONE (assumed — confirm
  its checklist actually passed before treating Phase 2 work as safe
  to build on).** Conversation history, the system prompt, the JARVIS
  UI, permission tiers, Tavily web search/fetch. See PHASE1.md.
- **Phase 2 — integrations. In progress.** Google Calendar, Gmail,
  tasks/reminders, coding tools — four independent MCP servers, one at
  a time. See PHASE2.md.
- **Phase 3 — voice.** faster-whisper in, Kokoro-82M out. Push-to-talk
  now, wake word is the stretch cut. See PHASE3.md.
- **Phase 4 — polish.** Real interactive confirmation flow for
  SENSITIVE/DESTRUCTIVE actions, error handling pass, tests on the
  tool servers. See PHASE4.md.

## Working agreement

- Move through phases automatically, in order, without stopping to
  ask for a new go-ahead between them. A phase's done-checklist must
  still fully pass before starting the next one — that gate doesn't
  relax just because the process is more autonomous now.
- Only stop and ask when something genuinely requires input:
  - Credentials/API keys that aren't already in `.env`
  - A real design decision that this file and the phase docs don't
    already resolve — not "which incremental step to do first," an
    actual fork with no stated preference
  - **Before exercising any SENSITIVE or DESTRUCTIVE-tier tool for
    real** (sending an actual email, creating/deleting a real
    calendar event, running a command with real side effects) — even
    during testing. Use safe substitutes instead where possible:
    drafts instead of sends, a scratch calendar instead of the real
    one, dry-run flags. Confirm before anything that would genuinely
    touch the real Gmail or Calendar.
  - If a requirement is genuinely unrealistic for this hardware or the
    timeframe — say so and propose a scaled-down version rather than
    quietly under- or over-delivering
- When something breaks, debug and fix it directly rather than
  reporting the error back and waiting.
