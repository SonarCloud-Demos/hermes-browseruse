> **Original task prompt**, given verbatim to the AI coding agent (Claude Code) that built this repo.
> Where the implementation deviates from it and why: see [README → Deviations from the original spec](README.md#deviations-from-the-original-spec).

# Workshop Planning

Build a fully working local system on this machine: OpenWebUI, the Hermes 8B model from Nous Research running locally via Ollama, and a separate browser-automation agent ("BrowserUse-Opus") powered by Claude Opus. Both must end up selectable as chat models in OpenWebUI. Work autonomously until the system is complete and runnable. Do not ask clarifying questions — use the defaults stated in this spec.

## 1. Project structure (new folder hermes-browseruse/)

```
hermes-browseruse/
├── docker-compose.yml
├── .env.example
├── README.md
└── browser-agent/
    ├── Dockerfile
    ├── requirements.txt
    ├── server.py
    └── owui_function.py
```

## 2. Ollama + Nous Research Hermes 8B

Service ollama: official image ollama/ollama, port mapping 11434:11434, volume ollama-data:/root/.ollama
On first startup, automatically pull the model hermes3:8b (Nous Research "Hermes 3 8B", available on the Ollama library as hermes3) — do this via a one-off init service (ollama-pull) that runs ollama pull hermes3:8b against the ollama service and then exits, so the user does not have to run any command manually
OpenWebUI auto-discovers Ollama models once OLLAMA_BASE_URL points at the ollama service — no extra registration code needed for this model, it just appears as hermes3:8b in the model dropdown

## 3. "browser-agent" service (FastAPI + browser-use), powered by Claude Opus

Base image: python:3.12-slim
Pin in requirements.txt: browser-use==0.1.40, fastapi, uvicorn[standard], playwright, anthropic, pydantic
Dockerfile runs playwright install --with-deps chromium
server.py: FastAPI app with exactly two endpoints:
GET /health → {"status": "ok"}
POST /run_task with body {"task": "<string>", "max_steps": 25} → runs the task via browser_use.Agent (LLM backend: Anthropic, model from env var ANTHROPIC_MODEL, default claude-opus-4-20250514), returns {"result": "<summary>", "steps": <int>, "success": <bool>}
Chromium runs headless in the container; API key from env var ANTHROPIC_API_KEY, never hardcoded
Container listens internally on port 8000

## 4. OpenWebUI pipe for the browser agent

owui_function.py: an OpenWebUI "Pipe" function (class Pipe: with Valves, pipes(), pipe() per the OpenWebUI Functions API)
Valve BROWSER_AGENT_URL (default http://browser-agent:8000)
Registers exactly one model: id="browseruse-opus", name="BrowserUse-Opus"
Forwards incoming chat messages verbatim as task to POST /run_task; returns the response as the chat reply; on success:false, surface the error visibly, never fail silently

## 5. docker-compose.yml

Service openwebui: image ghcr.io/open-webui/open-webui:main, port mapping 3000:8080, volume openwebui-data:/app/backend/data, env var OLLAMA_BASE_URL=http://ollama:11434, healthcheck on its root endpoint
Service ollama: as in section 2
Service ollama-pull (one-off, restart: "no"): runs ollama pull hermes3:8b against ollama, depends_on: ollama with condition: service_healthy (or a retry loop if Ollama has no built-in healthcheck)
Service browser-agent: build from ./browser-agent, no host port mapping (internal hostname browser-agent), env_file: .env
Shared Docker network, named volumes openwebui-data and ollama-data
.env.example with ANTHROPIC_API_KEY= and ANTHROPIC_MODEL=claude-opus-4-20250514

## 6. After building, you must run and verify

Generate .env from .env.example (placeholder key; README tells the user to fill it in)
docker compose up -d --build
curl http://localhost:3000 → must return HTTP 200
curl http://localhost:11434/api/tags → must list hermes3:8b once the pull finishes
README must document: entering the API key, that hermes3:8b and BrowserUse-Opus both appear as selectable models with no manual import step, and one sample task for each: a general-knowledge question for Hermes 8B, and "Open https://example.com and summarize the page content in one sentence" for BrowserUse-Opus

## 7. Acceptance criterion (for the benchmark)

Success means: after docker compose up -d --build plus entering the API key in .env — with no other manual configuration step — a human opens OpenWebUI and can (a) select hermes3:8b and get a response from the locally running Nous Research Hermes model, and (b) select BrowserUse-Opus and get a correct result for the sample browser task. Fix all build/startup/pull errors yourself until this state is reached — do not stop early.

## 8. Scope limitation

Only the services/files listed above. No additional agents, no n8n, no systemd/autostart, no VNC/noVNC viewer.