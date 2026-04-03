# openfang-ollama-telegram

Deploy a local GPU-powered OpenFang agent with Ollama and Telegram using Docker Compose.

This repo packages OpenFang, Ollama, and Telegram into a single self-hosted stack. The default path favors OpenFang's native Telegram channel and bundled hands, while still keeping an optional deterministic `telegram-bridge` profile in the repo for reminder experiments and fallback workflows.

## What this repo includes

- OpenFang pinned to `v0.5.3`
- Ollama pinned to `v0.17.7`
- Default local model set to `qwen3.5:2b`
- Embedding model set to `nomic-embed-text:latest`
- Native OpenFang Telegram channel enabled by default
- Lightweight `telegram-chat` front-door agent enabled by default
- Built-in OpenFang hands available out of the box
- Optional custom hands for reminder and daily-report workflows
- Optional repo-dev workflow for small code changes and draft PR submission
- Optional `telegram-bridge` profile for deterministic reminder handling
- Automatic first-run model pull through the Ollama API
- Helper scripts for hand activation, cron inspection, Claude Code wiring, and repo-dev GitHub flows

## What We've Covered So Far

- Reminders
  - Telegram users can ask for reminders in natural language
  - The repo includes both a native OpenFang path and an optional deterministic bridge path
  - Reminder behavior has been tested against local Ollama models

- Cron jobs
  - OpenFang cron APIs are the intended scheduler path for delayed and recurring work
  - The repo includes helper scripts to inspect scheduled jobs
  - Cron-based reminders and recurring workflows are part of the target design

- Research hand
  - OpenFang bundled hands can be used for deeper research workflows
  - The built-in `researcher` hand is the main example for web-backed research tasks
  - This is the recommended starting point for report-style and investigation-style demos

## Architecture

```text
Telegram user
  -> Telegram Bot API
  -> OpenFang
     -> native Telegram channel
     -> telegram-chat front-door agent
     -> built-in hands
     -> optional custom hands
     -> dashboard + API
  -> Ollama
  -> NVIDIA GPU
```

OpenFang handles Telegram polling directly by default. The running API exposes built-in hands such as `researcher`, `collector`, `browser`, `lead`, and `predictor`, so the intended workflow is to start with those bundled capabilities before adding custom logic.

The default Telegram front door is a lightweight custom agent named `telegram-chat`. It is intentionally narrower than the built-in `assistant`, so everyday Telegram messages do not hit the full tool surface by default. It is also constrained to plain-text-style replies so Telegram delivery is less likely to fail on malformed rich-text entities.

The repo also includes an optional gateway-style bridge profile that moves the project toward an OpenClaw-inspired architecture without changing OpenFang itself:

```text
Telegram
  -> Channel Adapter
  -> Gateway Server
     -> session router
     -> lane-based execution
     -> persisted session events
  -> Agent runner
  -> Response path back to Telegram
```

That bridge path is implemented in [telegram_bridge.py](./bridge/telegram_bridge.py) and documented in [docs/openclaw-style-architecture.md](./docs/openclaw-style-architecture.md).

It is important to treat that bridge as an architectural enhancement around OpenFang, not as a rewrite of OpenFang's internal runtime. The goal is to keep OpenFang as the partner service while improving message flow, session routing, lane-based execution, response persistence, and responsible agent behavior.

If you want to run the gateway-style bridge against your Telegram bot, disable OpenFang's native Telegram polling first so both services do not compete for the same bot token:

```env
OPENFANG_TELEGRAM_ENABLED=false
```

Then start the bridge profile:

```bash
docker compose --profile bridge up -d --build telegram-bridge
```

## Quick Start

```bash
git clone https://github.com/Rishiatweb/openfang-ollama-telegram.git
cd openfang-ollama-telegram
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
TELEGRAM_BOT_TOKEN=1234567890:replace-me
OPENFANG_API_KEY=replace-me
```

Then start the stack:

```bash
docker compose up -d --build
```

The first run can take a while because Ollama needs to download both the selected chat model and the embedding model. For the full step-by-step walkthrough, see [QUICKSTART.md](./QUICKSTART.md).

## Setup Wizards

This repo now includes both a GUI setup path and a terminal setup path. Both generate the same local [`.env.example`](./.env.example)-based configuration and let users supply:

- Telegram bot token
- OpenFang API key
- their own Ollama URL if they already run Ollama elsewhere
- their preferred chat model and embedding model
- optional Tavily or Brave search keys
- optional GitHub repo-dev target repo and token
- the model Claude Code should use against the same Ollama-compatible endpoint

### GUI setup wizard

Launch the local browser-based setup wizard:

```powershell
.\scripts\setup-gui.ps1
```

Or:

```bash
python ./scripts/setup_gui.py
```

By default it starts on `http://127.0.0.1:8765` and writes `.env` in the repo root after you save the form.

Secret fields are never prefilled back into the form. If a secret is already set, leaving that field blank keeps the existing value.

### Terminal setup wizard

Launch the interactive terminal wizard:

```powershell
.\scripts\setup-terminal.ps1
```

Or:

```bash
python ./scripts/setup_terminal.py
```

This is useful for remote Linux boxes, SSH sessions, or headless servers where a browser is not convenient.

Secret prompts are hidden in the terminal wizard, and pressing Enter on a secret field keeps the current value if one already exists.

## Linux Setup

These steps assume a fresh Linux machine with:

- Docker Engine 24+ installed
- Docker Compose plugin available
- NVIDIA drivers installed on the host if GPU inference is required
- NVIDIA Container Toolkit installed and Docker configured to use it
- A Telegram bot token from `@BotFather`

### 1. Clone the repository

```bash
git clone https://github.com/Rishiatweb/openfang-ollama-telegram.git
cd openfang-ollama-telegram
```

### 2. Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and set:

```env
TELEGRAM_BOT_TOKEN=your-real-bot-token
OPENFANG_API_KEY=your-secret-api-key
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen3.5:2b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text:latest
OPENFANG_TELEGRAM_DEFAULT_AGENT=telegram-chat
```

### 3. Start the stack

```bash
docker compose up -d --build
```

### 4. Verify services

```bash
docker compose ps
docker compose logs -f ollama
docker compose logs -f openfang
```

Expected milestones:

- `ollama` becomes `healthy`
- `ollama-model` exits with code `0`
- `openfang` stays `running`

### 5. Test in Telegram

Send your bot:

```text
Hello from Telegram. Reply with exactly: OpenFang is live.
```

### 6. Open the dashboard

The OpenFang dashboard is exposed on:

```text
http://localhost:4200
```

Use the API key from `.env` if OpenFang prompts for it.

## Setup Options

### Terminal-first setup

Use the terminal for:

- cloning the repo
- running the terminal setup wizard
- starting Docker Compose
- checking logs
- activating hands
- inspecting cron jobs

Main commands:

```bash
python ./scripts/setup_terminal.py
docker compose up -d --build
docker compose ps
docker compose logs -f openfang
```

### GUI-assisted setup

You can also use:

- the local setup GUI to generate `.env`
- Docker Desktop, Portainer, or another container UI to inspect services
- a browser to open the OpenFang dashboard
- Telegram desktop/mobile to test the bot

Useful GUI endpoints:

- Setup wizard: `http://127.0.0.1:8765`
- OpenFang dashboard: `http://localhost:4200`
- Telegram bot chat: the bot URL created through BotFather

## Using Your Own Ollama or LLM Endpoint

If you already have an Ollama server on another machine, keep the repo structure the same and change only the endpoint and model configuration.

Example:

```env
OLLAMA_BASE_URL=http://10.0.0.25:11434
OLLAMA_MODEL=qwen3.5:2b
CLAUDE_CODE_MODEL=qwen3.5:2b
```

Important notes:

- `OLLAMA_MODEL` must match a model that already exists on your remote Ollama server
- `CLAUDE_CODE_MODEL` lets the helper script aim Claude Code at the same local or remote Ollama-backed model
- when OpenFang runs in Docker, do not use `localhost` for an external Ollama server; use `host.docker.internal` for host-local Ollama or a reachable LAN hostname/IP
- the Claude helper translates bundled Docker endpoints like `ollama` or `host.docker.internal` back to `localhost` when it runs on the host
- if you point to an external Ollama endpoint, the setup wizards will recommend starting only `openfang` instead of the full stack
- the wizards automatically derive `OPENFANG_OLLAMA_BASE_URL` from `OLLAMA_BASE_URL`

If you use a different OpenAI-compatible LLM endpoint instead of Ollama:

- confirm the endpoint is API-compatible with what OpenFang expects
- update the provider base URL and model name
- verify the selected model exists on that endpoint before starting the full stack

## Key Configuration

The defaults live in [`.env.example`](./.env.example).

| Variable | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token used by OpenFang's native Telegram channel |
| `OPENFANG_API_KEY` | Yes | API/dashboard key for OpenFang |
| `OLLAMA_BASE_URL` | No | Base Ollama endpoint for model pulling, bridge mode, and setup tooling |
| `OLLAMA_MODEL` | No | Primary local chat model; defaults to `qwen3.5:2b` |
| `OLLAMA_EMBEDDING_MODEL` | No | Embedding model pulled on first startup |
| `CLAUDE_CODE_MODEL` | No | Model used by `run-claude-with-ollama.ps1`; falls back to `OLLAMA_MODEL` |
| `OPENFANG_TELEGRAM_DEFAULT_AGENT` | No | Default Telegram agent; defaults to `telegram-chat` |
| `TELEGRAM_ALLOWED_USERS` | Recommended | Comma-separated numeric Telegram user IDs allowed to use the bot |
| `TAVILY_API_KEY` / `BRAVE_API_KEY` | Optional | Enables live web search for report workflows |
| `GITHUB_TOKEN` | Optional | Enables repo-dev push and draft PR creation |
| `GITHUB_REPO_OWNER` / `GITHUB_REPO_NAME` | Optional | Target GitHub repo for repo-dev; can differ from local `origin` |
| `GITHUB_BASE_BRANCH` | Optional | Base branch used by repo-dev PR creation |
| `REPO_DEV_WORKSPACE_PATH` | Optional | Mounted repo path inside the OpenFang container |

Notes:

- `qwen3.5:2b` is the default because it stays in the Qwen 3.5 line while fitting a 6 GB class laptop GPU more comfortably than larger variants
- `OLLAMA_CONTEXT_LENGTH=4096` is the default to reduce prompt pressure and keep the live Telegram path more responsive on smaller GPUs
- `OLLAMA_BASE_URL=http://ollama:11434` is the correct bundled-container value; for host Ollama from Docker use `http://host.docker.internal:11434`
- `OPENFANG_TELEGRAM_ENABLED=true` is the default because this stack now prefers OpenFang's native Telegram support
- `telegram-bridge` is still available as an optional Compose profile if you want to experiment with the older deterministic reminder path:

```bash
docker compose --profile bridge up -d telegram-bridge
```

## Built-In Hands First

Before installing custom hands, inspect the bundled OpenFang hands the running API already exposes:

```powershell
.\scripts\list-installed-hands.ps1
```

For deep research, activate the built-in `researcher` hand when you need it:

```powershell
.\scripts\activate-hand.ps1 researcher
```

Useful built-in hands you should expect to see from the running API include:

- `researcher`
- `collector`
- `browser`
- `lead`
- `predictor`

This repo still includes custom hands under [`hands/reminder`](./hands/reminder), [`hands/daily-report`](./hands/daily-report), and [`hands/repo-dev`](./hands/repo-dev), but they are optional extensions rather than the default starting point.

The repo-dev workflow is backed by [`scripts/github_repo_flow.py`](./scripts/github_repo_flow.py). The native `telegram-chat` path can describe repo actions, but the deterministic bot-driven repo command path lives in the optional `telegram-bridge` profile.

For genuine Telegram-driven `repo status`, `repo apply`, `repo diff`, and `repo approve` execution, run the bridge profile and disable native Telegram polling in OpenFang:

```env
OPENFANG_TELEGRAM_ENABLED=false
```

```bash
docker compose --profile bridge up -d --build telegram-bridge
```

When you want to stop routing through an activated hand later:

```powershell
.\scripts\deactivate-hand.ps1 researcher
docker compose restart openfang
```

## Demo Flow

For a short team demo, use this sequence:

1. Basic sanity check in Telegram:

```text
Say OpenFang is live
```

2. Show the active runtime in terminal:

```powershell
python .\scripts\openfang_api.py --path "/api/agents"
.\scripts\list-active-hands.ps1
```

3. Activate deep research:

```powershell
.\scripts\activate-hand.ps1 researcher
```

4. Try a research prompt:

```text
Use researcher hand to research the latest AI infrastructure trends.
```

5. Demonstrate a real action:

```text
remind me in 2 minutes to stretch
```

Then show:

```powershell
.\scripts\list-cron-jobs.ps1
```

## Services

| Service | Purpose |
| --- | --- |
| `ollama` | Local model server with GPU access and persistent model cache |
| `ollama-model` | One-shot init container that pulls the configured models on first run |
| `openfang` | OpenFang service with generated config, dashboard, API, native Telegram channel, and mounted custom hands |
| `openfang-hand-installer` | One-shot helper that installs local custom hands into the running OpenFang instance |
| `telegram-bridge` | Optional bridge profile for the earlier deterministic reminder path |

## Day-to-Day Operations

Start or rebuild everything:

```bash
docker compose up -d --build
```

If you are using an external `OLLAMA_BASE_URL`, start only OpenFang:

```bash
docker compose up -d --build openfang
```

Stop the stack:

```bash
docker compose down
```

Refresh the selected model after changing `.env`:

```bash
docker compose up -d ollama-model
docker compose up -d openfang
```

If you changed `OPENFANG_VERSION`, rebuild the OpenFang image too:

```bash
docker compose up -d --build openfang
```

Tail logs:

```bash
docker compose logs -f ollama
docker compose logs -f openfang
```

Inspect installed and active hands:

```powershell
.\scripts\list-installed-hands.ps1
.\scripts\list-active-hands.ps1
```

Inspect scheduled jobs:

```powershell
.\scripts\list-cron-jobs.ps1
```

Check repo-dev GitHub readiness:

```powershell
python .\scripts\github_repo_flow.py github-preflight --session-id telegram --pretty
```

Inspect gateway sessions when running the optional bridge profile:

```powershell
.\scripts\list-bridge-sessions.ps1
```

Run Claude Code against the same Ollama-backed endpoint and model family:

```powershell
.\scripts\run-claude-with-ollama.ps1
```

Preview the resolved Claude wiring without launching:

```powershell
.\scripts\run-claude-with-ollama.ps1 -PrintOnly
```

Override the Claude-only model:

```powershell
.\scripts\run-claude-with-ollama.ps1 -Model qwen3.5:2b
```

## Repository Layout

```text
.
|-- .env.example
|-- docker-compose.yml
|-- QUICKSTART.md
|-- README.md
|-- bridge/
|   `-- telegram_bridge.py
|-- docker/
|   |-- openfang/
|   |   |-- Dockerfile
|   |   |-- config.toml.template
|   |   |-- reminder-agent.toml.template
|   |   `-- telegram-chat-agent.toml.template
|   `-- telegram-bridge/
|       `-- Dockerfile
|-- docs/
|   |-- implementation-checklist.md
|   |-- repo-dev-hand.md
|   `-- reminders-and-daily-reports.md
|-- hands/
|   |-- daily-report/
|   |-- reminder/
|   `-- repo-dev/
|-- prompts/
|   `-- codex_end_to_end_openfang_implementation_prompt.md
`-- scripts/
    |-- activate-hand.ps1
    |-- deactivate-hand.ps1
    |-- install-custom-hands.ps1
    |-- install_custom_hands.py
    |-- list-active-hands.ps1
    |-- list-bridge-reminders.ps1
    |-- list-bridge-sessions.ps1
    |-- list-cron-jobs.ps1
    |-- list-installed-hands.ps1
    |-- openfang-common.ps1
    |-- openfang-entrypoint.sh
    |-- openfang_api.py
    |-- pull-model.sh
    |-- run-claude-with-ollama.ps1
    |-- github_repo_flow.py
    |-- setup-gui.ps1
    |-- setup-terminal.ps1
    |-- setup_gui.py
    |-- setup_shared.py
    `-- setup_terminal.py
```

## Troubleshooting

### Ollama cannot see the GPU

Check:

- `nvidia-smi` works on the host
- NVIDIA Container Toolkit is installed
- Docker was configured for the NVIDIA runtime
- Docker was restarted after toolkit setup

### The bot never answers

Check:

- `TELEGRAM_BOT_TOKEN` is correct
- `ollama-model` finished successfully
- OpenFang can reach Ollama at `http://ollama:11434`
- OpenFang native Telegram is enabled in `.env`

Useful commands:

```bash
docker compose logs -f ollama-model
docker compose logs -f openfang
```

### Telegram replies fail with `can't parse entities`

That means Telegram rejected a formatted reply because it contained malformed Markdown or HTML-like entities.

What to do:

- restart OpenFang so the current plain-text `telegram-chat` prompt is loaded
- if the bad formatting came from old conversation state, clear the `telegram-chat` session history and restart the container
- prefer plain-text prompts for Telegram demonstrations and validation runs
- avoid asking the bot for code blocks, tables, or heavily formatted reports in Telegram

### Built-in hands are not active

List the hands the running API exposes:

```powershell
.\scripts\list-installed-hands.ps1
```

Then activate the one you want, for example:

```powershell
.\scripts\activate-hand.ps1 researcher
```

### `No HAND.toml found` during install

That usually means `openfang` was started before the repo mounted `./hands` into the container. Rebuild and retry:

```powershell
docker compose up -d --build --force-recreate openfang
.\scripts\install-custom-hands.ps1
```

## Security Notes

- Keep `OPENFANG_API_KEY` set; do not expose OpenFang without authentication
- Use `TELEGRAM_ALLOWED_USERS` if the bot is meant for a private operator workflow
- This stack is intended for trusted self-hosted environments
- If you expose services beyond localhost, put a reverse proxy and TLS in front of them

## Additional Docs

- [QUICKSTART.md](./QUICKSTART.md)
- [docs/reminders-and-daily-reports.md](./docs/reminders-and-daily-reports.md)
- [docs/implementation-checklist.md](./docs/implementation-checklist.md)
- [docs/openclaw-style-architecture.md](./docs/openclaw-style-architecture.md)
- [docs/repo-dev-hand.md](./docs/repo-dev-hand.md)
- OpenFang hands docs: https://www.openfang.sh/docs/hands
- Ollama Qwen 3.5 model page: https://ollama.com/library/qwen3.5

repo-dev PR flow was validated

second repo-dev validation passed
