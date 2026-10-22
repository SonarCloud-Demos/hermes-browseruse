"""BrowserUse-Opus: FastAPI wrapper around browser_use.Agent (LLM: Anthropic, Portkey or Ollama)."""

import logging
import os

from browser_use import Agent, Browser, BrowserConfig
from fastapi import FastAPI
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

# claude-opus-4-20250514 (named in the original spec) reached end-of-life on
# 2026-06-15. browser-use 0.1.40 forces tool_choice via with_structured_output,
# which Claude Opus 5.5 rejects, so the default is the newest Opus that accepts it.
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_PORTKEY_BASE_URL = "https://api.portkey.ai"
DEFAULT_PORTKEY_PROVIDER = "@claude-code"
DEFAULT_OLLAMA_BASE_URL = "http://ollama:11434"
DEFAULT_OLLAMA_MODEL = "hermes3:8b"
RESTART_HINT = "Set it in .env and run `docker compose up -d browser-agent` to restart the service."

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("browser-agent")

app = FastAPI(title="BrowserUse-Opus")


class TaskRequest(BaseModel):
    task: str = Field(..., min_length=1)
    max_steps: int = Field(25, ge=1, le=100)


class TaskResponse(BaseModel):
    result: str
    steps: int
    success: bool


@app.get("/health")
def health():
    return {"status": "ok"}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def build_llm():
    """Return (llm, None) for the backend selected by BROWSER_AGENT_LLM, or (None, error)."""
    backend = env("BROWSER_AGENT_LLM", "anthropic").lower()

    if backend == "anthropic":
        api_key = env("ANTHROPIC_API_KEY")
        if not api_key:
            return None, f"ANTHROPIC_API_KEY is not set (BROWSER_AGENT_LLM=anthropic). {RESTART_HINT}"
        return ChatAnthropic(
            model_name=env("ANTHROPIC_MODEL", DEFAULT_MODEL),
            api_key=api_key,
            timeout=120,
            max_tokens=4096,
            stop=None,
        ), None

    if backend == "portkey":
        # Portkey's Anthropic-compatible gateway: same /v1/messages API, routed to
        # the provider named in x-portkey-provider using credentials stored in Portkey.
        portkey_key = env("PORTKEY_API_KEY")
        if not portkey_key:
            return None, f"PORTKEY_API_KEY is not set (BROWSER_AGENT_LLM=portkey). {RESTART_HINT}"
        return ChatAnthropic(
            model_name=env("ANTHROPIC_MODEL", DEFAULT_MODEL),
            api_key=portkey_key,
            base_url=env("PORTKEY_BASE_URL", DEFAULT_PORTKEY_BASE_URL),
            default_headers={
                "x-portkey-api-key": portkey_key,
                "x-portkey-provider": env("PORTKEY_PROVIDER", DEFAULT_PORTKEY_PROVIDER),
            },
            timeout=120,
            max_tokens=4096,
            stop=None,
        ), None

    if backend == "ollama":
        return ChatOllama(
            model=env("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            base_url=env("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            # browser-use prompts (system prompt + DOM state) far exceed Ollama's 2048 default.
            num_ctx=int(env("OLLAMA_NUM_CTX", "16384")),
        ), None

    return None, f"Unknown BROWSER_AGENT_LLM={backend!r}; use anthropic, portkey or ollama. {RESTART_HINT}"


@app.post("/run_task", response_model=TaskResponse)
async def run_task(req: TaskRequest) -> TaskResponse:
    llm, error = build_llm()
    if error:
        return TaskResponse(result=error, steps=0, success=False)

    browser = Browser(config=BrowserConfig(headless=True))

    try:
        # Screenshots only for Claude; text-only local models (hermes3) reject images.
        agent = Agent(task=req.task, llm=llm, browser=browser, use_vision=not isinstance(llm, ChatOllama))
        history = await agent.run(max_steps=req.max_steps)
    except Exception as exc:  # surface everything to the caller, never fail silently
        log.exception("task failed")
        return TaskResponse(result=f"Agent error: {type(exc).__name__}: {exc}", steps=0, success=False)
    finally:
        try:
            await browser.close()
        except Exception:
            log.warning("browser close failed", exc_info=True)

    steps = len(history.history)
    final = history.final_result()
    if history.is_done() and final:
        return TaskResponse(result=final, steps=steps, success=True)

    errors = [e for e in history.errors() if e]
    if errors:
        detail = errors[-1]
    elif not history.is_done():
        detail = f"Task did not finish within {req.max_steps} steps."
    else:
        detail = "Agent finished without producing a result."
    if final:
        detail = f"{detail}\nPartial result: {final}"
    return TaskResponse(result=detail, steps=steps, success=False)
