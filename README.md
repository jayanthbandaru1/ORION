# ORION

**Omni-Responsive Intelligence & Operations Nexus**

ORION is a local-first personal AI assistant designed to function as an intelligent operating layer across a user's computer, files, services, and devices.

Instead of acting like a traditional chatbot that only responds to prompts, ORION is built around the idea of an AI system that can understand context, decide when tools are needed, interact with the local machine, access connected services, and assist with real workflows while keeping the user in control.

The project combines a local language model, modular MCP tool servers, desktop and web interfaces, voice interaction, computer control, calendar and Gmail integrations, vision, system monitoring, location awareness, weather tools, proactive features, and a tiered permission system.

---

## Overview

ORION began as an experiment in building a personal AI assistant that feels closer to an operating system layer than a traditional chatbot.

The central idea behind the project is:

> **Give an AI assistant useful capabilities without giving it unrestricted authority.**

ORION is designed to run primarily on the user's own hardware. The language model itself does not receive unrestricted access to the operating system, filesystem, internet, or connected accounts.

Instead, ORION interacts with external systems through a controlled tool layer.

This architecture separates:

- AI reasoning
- Tool execution
- Permission enforcement
- System access
- User confirmation

The goal is to make ORION powerful enough to be genuinely useful while keeping sensitive or destructive actions under explicit user control.

---

## Core Architecture

ORION is organized around several primary layers.

### 1. Local AI Layer

ORION currently uses a locally hosted language model through Ollama.

The model is responsible for:

- Understanding natural-language requests
- Maintaining conversational context
- Deciding when tools are required
- Selecting tools
- Interpreting tool outputs
- Coordinating multi-step actions
- Generating responses
- Adapting behavior based on context

Because the model runs locally, ORION can perform inference without requiring every conversation to be sent to an external AI service.

---

### 2. Orchestration Layer

The orchestration layer acts as the central controller of ORION.

It manages:

- Conversation state
- Model requests
- Tool schemas
- MCP connections
- Tool execution
- Tool results
- Permission checks
- Error handling
- Multi-step workflows
- Realtime interactions

The orchestrator acts as the bridge between the language model and the rest of the system.

---

### 3. MCP Tool Layer

ORION uses a modular MCP-based architecture to expose capabilities to the assistant.

Each server focuses on a specific domain.

Current ORION tool categories include:

- Filesystem
- Web
- Calendar
- iCloud Calendar
- Gmail
- Tasks
- Coding
- Computer control
- Vision
- Location
- Weather

In the current build, ORION connects to **12 MCP servers** and exposes **56 tools** to the orchestration layer.

This modular architecture makes it easier to:

- Add new capabilities
- Test services independently
- Isolate failures
- Restrict access by tool
- Replace integrations
- Expand the system over time

---

## Key Features

### Local-First AI

ORION is built around local inference using Ollama.

Benefits include:

- Greater privacy
- Local processing
- Reduced dependence on cloud services
- More control over model behavior
- Easier integration with local system tools

The model layer is replaceable, allowing ORION to evolve as better local models become available.

---

### Tool-Based Execution

ORION does not directly execute arbitrary actions from model output.

Instead, capabilities are exposed through structured tools.

Examples include:

- Listing directories
- Reading files
- Checking weather
- Accessing calendar information
- Interacting with Gmail
- Controlling desktop functions
- Inspecting system state
- Working with code
- Processing location data
- Using vision features

This creates a controlled interface between the AI and the operating system.

---

## Permission System

One of ORION's most important components is its permission architecture.

Tools are assigned different permission levels based on risk.

| Tier | Purpose | Example |
|---|---|---|
| `READ` | Non-destructive information access | Read files, inspect system state |
| `SAFE` | Low-risk actions | Search local data |
| `REVERSIBLE` | Actions that can easily be undone | Modify temporary state |
| `SENSITIVE` | Actions involving private or important information | Send email, modify important data |
| `DESTRUCTIVE` | High-risk or irreversible actions | Delete files or perform destructive system actions |

Sensitive and destructive operations require explicit user confirmation.

This separates the model's ability to reason about an action from its authority to execute it.

---

## Filesystem Security

ORION does not have unrestricted filesystem access.

Filesystem tools are limited to explicitly authorized directories configured by the user.

Examples may include:

```text
Desktop
Documents
Downloads
Selected project folders
```

If ORION attempts to access a path outside the authorized locations, the filesystem server rejects the request.

Machine-specific path configuration is stored locally and excluded from the public repository.

---

## Desktop Application

ORION includes a desktop application built with Electron.

Current desktop functionality includes:

- Native application window
- Local backend communication
- Desktop integration
- Location access
- Persistent app behavior
- Local ORION connectivity
- System-level interaction support

The desktop client allows ORION to function more like a native assistant than a browser-only chatbot.

---

## Web and Mobile Interfaces

ORION includes responsive browser-based interfaces for both desktop and mobile devices.

Current functionality includes:

- Chat interaction
- Responsive layouts
- Progressive Web App support
- Web manifests
- Service workers
- Local-network access
- Mobile-specific UI

The long-term goal is for ORION to remain accessible across multiple devices while the primary AI system continues running on the host machine.

---

## Voice and Realtime Interaction

ORION includes voice and realtime components designed to make interactions feel more natural.

Current functionality includes:

- Speech synthesis
- Voice responses
- Realtime communication
- Audio-reactive speaking states
- Context-aware behavior
- Personality-driven pacing

Future versions are intended to support lower-latency and more continuous voice interaction.

---

## Vision

ORION includes a dedicated vision subsystem.

Current components include:

- Vision MCP server
- Vision API functionality
- Visual input processing
- Vision tracking
- Dedicated automated tests

The long-term goal is for ORION to understand:

- Screenshots
- Application state
- UI elements
- Camera input
- Visual context

This would allow ORION to reason about what the user is seeing rather than depending entirely on text input.

---

## Computer Control

ORION includes a computer-control tool layer.

Rather than granting the model unrestricted desktop control, computer interaction is exposed through structured tools and governed by the permission system.

This preserves a security boundary between AI reasoning and actual system authority.

---

## Location and Weather

ORION includes dedicated location and weather services.

These allow the assistant to retrieve contextual information when needed without giving the model permanent unrestricted access to location data.

Potential uses include:

- Local weather
- Location-aware requests
- Contextual recommendations
- Daily planning

---

## Calendar Integration

ORION includes calendar functionality through dedicated MCP servers.

Current integrations include general calendar functionality and iCloud Calendar support.

Calendar tools can be used for:

- Reading events
- Searching schedules
- Retrieving upcoming events
- Working with connected calendar services

Sensitive account credentials remain local and are not included in the public repository.

---

## Gmail Integration

ORION includes Gmail functionality through a dedicated MCP server.

The system is designed to support workflows such as:

- Reading messages
- Searching email
- Inspecting threads
- Preparing responses
- Performing user-approved actions

Sensitive email actions are protected by ORION's permission system.

---

## Coding Tools

ORION includes coding-focused capabilities for local software development.

These tools can support tasks such as:

- Reading source files
- Searching code
- Editing files
- Running commands
- Running tests
- Inspecting Git state

This allows ORION to function as a local development assistant while still applying permission boundaries.

---

## Proactive Systems

ORION includes proactive functionality designed to move beyond purely reactive chatbot behavior.

The proactive subsystem is intended to allow ORION to:

- Monitor relevant system state
- Detect useful events
- Surface contextual information
- Respond to changing conditions
- Assist without requiring every interaction to begin with a manual prompt

---

## System Monitoring

ORION includes system-monitoring functionality for observing the state of the host computer.

This provides contextual information that can help the assistant reason about the user's environment.

The monitoring layer remains isolated from the model and is exposed through controlled interfaces.

---

## Testing

ORION includes a comprehensive automated test suite covering the core system and individual MCP servers.

The current test suite contains **192 tests**.

Latest result:

```text
192 passed
0 failed
```

Test coverage includes:

- Calendar server
- Coding server
- Computer API
- Computer MCP server
- End-to-end tool calling
- Filesystem server
- Gmail server
- iCloud Calendar server
- Location API
- Location server
- Orchestrator
- Permission tiers
- Proactive systems
- Realtime systems
- Tasks
- Vision API
- Vision server
- Vision tracking
- Voice synthesis
- Weather API
- Weather server

The end-to-end smoke test verifies that ORION can:

1. Start the orchestrator
2. Connect to MCP servers
3. Receive a natural-language request
4. Select the appropriate tool
5. Execute that tool
6. Return a valid response

---

## Tech Stack

### Backend

- Python
- FastAPI
- AsyncIO
- Ollama
- FastMCP / MCP
- Pytest

### Desktop

- Electron
- JavaScript
- Node.js

### Frontend

- HTML
- CSS
- JavaScript
- Progressive Web App technologies

### AI

- Local LLM inference
- Tool calling
- Modular MCP architecture
- Context-aware orchestration

---

## Project Structure

```text
ORION/
├── api.py
├── requirements.txt
├── SETUP.md
│
├── config/
│   ├── mcp_servers.yaml
│   ├── permissions.yaml
│   └── authorized_paths.yaml
│
├── core/
│   ├── orchestrator.py
│   ├── permissions.py
│   ├── proactive.py
│   ├── realtime.py
│   ├── system_monitor.py
│   ├── vision_tracking.py
│   ├── icloud_auth.py
│   └── icloud_errors.py
│
├── desktop/
│   ├── main.js
│   ├── preload.js
│   ├── package.json
│   ├── package-lock.json
│   ├── app-icon.png
│   ├── icon.ico
│   └── get_location.ps1
│
├── interfaces/
│   └── web/
│       ├── index.html
│       ├── mobile.html
│       ├── manifest.json
│       ├── mobile-manifest.json
│       ├── sw.js
│       └── vendor/
│
├── mcp_servers/
│   ├── computer/
│   ├── files/
│   ├── icloud_calendar/
│   ├── location/
│   ├── vision/
│   └── weather/
│
└── tests/
```

---

## Setup

### Requirements

Install:

- Python 3.13+
- Node.js
- Ollama
- Git

Clone the repository:

```bash
git clone https://github.com/Slasher4t/ORION.git
cd ORION
```

Create a Python virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Verify Ollama:

```bash
ollama --version
```

Start Ollama:

```bash
ollama serve
```

Install the configured model if necessary:

```bash
ollama pull qwen3:8b
```

---

## Desktop Setup

Enter the desktop directory:

```bash
cd desktop
```

Install dependencies:

```bash
npm install
```

Run the desktop application:

```bash
npm start
```

---

## Running Tests

Activate the virtual environment and run:

```bash
python -m pytest
```

Current expected result:

```text
192 passed
```

---

## Environment Configuration

ORION uses local environment variables and configuration files for information that should not be publicly committed.

Do not commit:

- API keys
- Passwords
- OAuth tokens
- Email credentials
- Personal filesystem paths
- Authentication tokens
- Machine-specific configuration

Use `.env.example` as a reference for configuring local environment variables.

---

## Security Philosophy

Security is a core part of ORION's architecture.

The system is designed around several boundaries:

### Local Model Isolation

The model does not receive unrestricted direct access to the operating system.

### Tool Isolation

Capabilities are exposed through structured tools.

### Permission Tiers

Actions are categorized based on risk.

### Explicit Confirmation

Sensitive and destructive actions require user approval.

### Authorized Filesystem Paths

Filesystem operations are restricted to configured directories.

### Local Configuration

Private and machine-specific configuration is excluded from the public repository.

The goal is to provide meaningful AI capabilities without treating the language model itself as a fully trusted system process.

---

## Current Status

ORION is an actively developed personal project.

Currently implemented areas include:

- Local LLM integration
- Tool calling
- MCP architecture
- Permission tiers
- Filesystem security
- Desktop client
- Web interface
- Mobile interface
- Computer interaction
- Vision
- Location
- Weather
- Calendar tools
- iCloud Calendar integration
- Gmail integration
- Task tools
- Coding tools
- Voice synthesis
- Realtime systems
- System monitoring
- Proactive functionality
- Automated testing
- End-to-end tool-call testing

Current automated test status:

**192 / 192 tests passing**

---

## Future Roadmap

### Voice

- Wake-word activation
- Continuous conversation
- Improved speech recognition
- Lower-latency responses
- More natural realtime interaction

### Vision

- Screenshot understanding
- Active-window awareness
- Camera input
- UI understanding
- Visual context tracking

### Computer Control

- More advanced desktop automation
- Cross-application workflows
- Better system-state awareness
- Safer reversible actions

### Memory

- Long-term personal context
- Structured memory
- Preference learning
- Context retrieval
- User-controlled memory management

### Mobile

- Improved remote access
- Notifications
- Device synchronization
- Better mobile controls

### Smart Home

- Smart-home integrations
- Connected-device control
- Context-aware automations

### Proactivity

- Event-driven assistance
- Intelligent reminders
- Context-aware notifications
- Background monitoring
- User-defined proactive behaviors

---

## Design Philosophy

ORION is built around several principles:

1. **Local first**
2. **User controlled**
3. **Modular**
4. **Permission aware**
5. **Replaceable AI models**
6. **Tool-based system access**
7. **Extensible architecture**
8. **Privacy-conscious by design**

ORION is not intended to simply be another chatbot.

The goal is to explore what a personal AI system could look like when it becomes a real interface between the user and their digital environment.

---

## Author

**Jayanth Bandaru**
