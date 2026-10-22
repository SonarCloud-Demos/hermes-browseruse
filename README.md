# hermes-browseruse

Local stack with two chat models in **OpenWebUI**:

| Model in dropdown | What it is |
|---|---|
| `hermes3:8b` | Nous Research **Hermes 3 8B**, running locally in **Ollama** |
| `BrowserUse-Opus` | A headless-Chromium **browser-use** agent driven by **Claude Opus** (Anthropic API directly or via Portkey), or optionally by the local Hermes model |

```
browser ──► OpenWebUI :3000 ──► ollama:11434        (hermes3:8b, local)
                         └────► browser-agent:8000  (FastAPI + browser-use + Chromium ──► Anthropic API | Portkey | Ollama)
```

## Services

| Service | Image / build | Purpose |
|---|---|---|
| `openwebui` | `ghcr.io/open-webui/open-webui:main` | Chat UI on http://localhost:3000. Auto-discovers Ollama models; auto-registers the BrowserUse-Opus pipe on every start. |
| `ollama` | `ollama/ollama` | Model server on http://localhost:11434 |
| `ollama-pull` | `ollama/ollama` | One-off: `ollama pull hermes3:8b` once Ollama is healthy, then exits |
| `browser-agent` | `./browser-agent` | `GET /health`, `POST /run_task` – internal only (no host port) |

## Setup

1. **Configure the browser agent's LLM** – the only manual step. `hermes3:8b` needs no key;
   only BrowserUse-Opus does. Pick one backend in `.env` (see [LLM backends](#llm-backends)):

   ```bash
   cp .env.example .env        # already done if .env exists
   # edit .env, e.g. direct Anthropic API:
   BROWSER_AGENT_LLM=anthropic
   ANTHROPIC_API_KEY=sk-ant-...
   # ...or Anthropic through Portkey:
   BROWSER_AGENT_LLM=portkey
   PORTKEY_API_KEY=...
   ```

   If you change `.env` while the stack is running, apply it with
   `docker compose up -d browser-agent`.

2. **Start everything:**

   ```bash
   docker compose up -d --build
   ```

   The first start downloads `hermes3:8b` (~4.7 GB). Follow progress with
   `docker compose logs -f ollama-pull`; the container exits with code 0 when done.

3. **Check:**

   ```bash
   curl -I http://localhost:3000            # HTTP 200
   curl http://localhost:11434/api/tags     # lists hermes3:8b once the pull is finished
   ```

4. Open **http://localhost:3000**. There is no sign-up/login (`WEBUI_AUTH=False`,
   single-user mode, you are admin). Both **`hermes3:8b`** and **`BrowserUse-Opus`**
   appear in the model dropdown – no manual import or configuration step is needed:
   - Ollama models are discovered via `OLLAMA_BASE_URL=http://ollama:11434`.
   - `browser-agent/owui_function.py` is mounted into the OpenWebUI container and
     registered + activated automatically as function `browseruse` at startup
     (internal model id `browseruse.browseruse-opus`, display name `BrowserUse-Opus`).

## Sample tasks

**hermes3:8b** (local, general knowledge):

> What is the difference between nuclear fission and nuclear fusion? Answer in three sentences.

**BrowserUse-Opus** (real headless browser + Claude Opus):

> Open https://example.com and summarize the page content in one sentence

Expected answer, roughly: *"The page states that this domain is reserved for use in
documentation examples and may be used without prior coordination or permission."*
A browser task takes ~20–60 s; a status line shows progress. Failures (missing/invalid
API key, step limit reached, agent errors) are shown as a visible `❌ BrowserUse-Opus task failed` reply.

## LLM backends

`BROWSER_AGENT_LLM` in `.env` selects which LLM drives the browser agent (default `anthropic`).
All variables are read by the `browser-agent` service via `env_file: .env`.

| `BROWSER_AGENT_LLM` | Variables | Notes |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` (required), `ANTHROPIC_MODEL` (default `claude-opus-4-8`) | Direct Anthropic API |
| `portkey` | `PORTKEY_API_KEY` (required), `ANTHROPIC_MODEL`, `PORTKEY_BASE_URL` (default `https://api.portkey.ai`), `PORTKEY_PROVIDER` (default `@claude-code`) | Anthropic Messages API through the Portkey gateway. The key goes into the `x-portkey-api-key` header; `PORTKEY_PROVIDER` into `x-portkey-provider` (the Portkey integration that holds the Anthropic credentials). Same setup as `ANTHROPIC_BASE_URL` / `ANTHROPIC_CUSTOM_HEADERS` for Claude Code. |
| `ollama` | `OLLAMA_MODEL` (default `hermes3:8b`), `OLLAMA_BASE_URL` (default `http://ollama:11434`), `OLLAMA_NUM_CTX` (default `16384`) | Fully local, no key. Screenshots are disabled (`use_vision=False`) because `hermes3` is text-only. Experimental: small models are unreliable at multi-step browser control and slow on CPU. In testing, `hermes3:8b` completed the example.com task technically (`success: true`) but answered with the placeholder text "summary of the page" – use `anthropic` or `portkey` for real work. |

The model name in the dropdown stays `BrowserUse-Opus` regardless of backend.

## browser-agent API

```bash
# from inside the compose network (the OpenWebUI container has curl)
docker compose exec openwebui curl -s http://browser-agent:8000/health
# {"status":"ok"}

docker compose exec openwebui curl -s http://browser-agent:8000/run_task \
  -H 'Content-Type: application/json' \
  -d '{"task": "Open https://example.com and summarize the page content in one sentence", "max_steps": 25}'
# {"result": "...", "steps": 2, "success": true}
```

The pipe's valves (`BROWSER_AGENT_URL`, default `http://browser-agent:8000`, `MAX_STEPS`,
`TIMEOUT_SECONDS`) can be changed in OpenWebUI under *Admin Panel → Functions → BrowserUse-Opus*.

## Behind a TLS-inspecting proxy (optional)

If your network re-signs HTTPS traffic (e.g. Cloudflare Zero Trust / corporate proxy),
the browser-agent build fails with `SELF_SIGNED_CERT_IN_CHAIN` (Playwright download) and
calls to `api.anthropic.com` fail at runtime. Put the proxy's root CA(s) as `*.crt` into a
local folder and add a `docker-compose.override.yml` (picked up automatically by compose):

```yaml
services:
  browser-agent:
    build:
      additional_contexts:
        extra-ca: ./.local-ca     # folder with your *.crt files
```

On macOS you can export the CA from the keychain, e.g.
`security find-certificate -a -c "Gateway CA - Cloudflare" -p /Library/Keychains/System.keychain > .local-ca/proxy.crt`.
The Dockerfile then trusts it for Python, Node (Playwright) and Chromium (NSS).

## Deviations from the original spec

Changes made on purpose to reach the acceptance criterion, and why:

| Spec said | Implemented | Why |
|---|---|---|
| `ANTHROPIC_MODEL` default `claude-opus-4-20250514` | `claude-opus-4-8` | Claude Opus 4 (`-20250514`) reached end-of-life on 2026-06-15 and no longer answers. `browser-use==0.1.40` calls Claude with forced `tool_choice`, which Claude Opus 5.5 rejects (400); Opus 4.8 is the newest Opus that accepts it. |
| (implicit) `temperature=0` | no `temperature` sent | The Messages API now rejects `temperature` / `top_p` / `top_k` with a 400. |
| requirements: browser-use, fastapi, uvicorn, playwright, anthropic, pydantic | + `google-api-core` | browser-use 0.1.40's step error handler imports `google.api_core`; without it every LLM error (bad key, rate limit, network) is silently swallowed and the task only reports "did not finish". |
| model `id="browseruse-opus"` | model id `browseruse.browseruse-opus`, name `BrowserUse-Opus` | OpenWebUI always prefixes models of a manifold pipe (one with `pipes()`) with the function id. |
| no manual import step | function auto-registered at startup (`python owui_function.py --register`, run by the openwebui container's entrypoint) | OpenWebUI has no env var to preload functions; the register code lives in `owui_function.py` itself, so no extra file. |
| no other manual configuration | `WEBUI_AUTH=False` (single-user, no login) | Otherwise the first visitor must create an admin account before any model is usable. |
| `BROWSER_AGENT_LLM` not in spec | `anthropic` \| `portkey` \| `ollama` switch | Added on request: Anthropic is only reachable through Portkey here; Ollama allows a key-less local run. |
| browser-agent Dockerfile: plain install | optional `extra-ca` build context for extra root CAs | Needed behind TLS-inspecting proxies (see below); no effect when not used. |

Machine-local only (not part of the deliverable, delete on other machines):
`docker-compose.override.yml` + `.local-ca/` – trust the Cloudflare Zero Trust CA, and give
`browser-agent` public DNS (`1.1.1.1`, `8.8.8.8`) because this host's `/etc/hosts` maps
`example.com` to `127.0.0.1`, which Docker Desktop passes into containers.

## Notes

- Data persists in the named volumes `openwebui-data` and `ollama-data`
  (`docker compose down -v` deletes them, including the downloaded model).
- `WEBUI_AUTH=False` is meant for a local, single-user machine. Don't expose port 3000 publicly.
- Hermes 3 8B runs on CPU inside Docker on macOS (no Metal GPU passthrough); expect a few tokens/s.
