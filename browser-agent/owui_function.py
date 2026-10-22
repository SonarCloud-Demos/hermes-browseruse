"""
title: BrowserUse-Opus
description: Forwards the chat message as a task to the browser-agent service (browser-use + Claude Opus).
version: 1.0.0
requirements:
"""

import aiohttp
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        BROWSER_AGENT_URL: str = Field(
            default="http://browser-agent:8000",
            description="Base URL of the browser-agent service",
        )
        MAX_STEPS: int = Field(default=25, description="Maximum browser-use agent steps per task")
        TIMEOUT_SECONDS: int = Field(default=900, description="HTTP timeout for one task")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": "browseruse-opus", "name": "BrowserUse-Opus"}]

    @staticmethod
    def _last_user_message(messages) -> str:
        for message in reversed(messages or []):
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if isinstance(content, list):  # multimodal: keep the text parts
                content = "\n".join(
                    part.get("text", "") for part in content if part.get("type") == "text"
                )
            return content
        return ""

    async def pipe(self, body: dict, __event_emitter__=None) -> str:
        task = self._last_user_message(body.get("messages"))
        if not task.strip():
            return "❌ BrowserUse-Opus: no task found in the chat message."

        async def status(description: str, done: bool):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": description, "done": done}}
                )

        url = self.valves.BROWSER_AGENT_URL.rstrip("/") + "/run_task"
        await status("Browser agent is working on the task…", False)
        try:
            timeout = aiohttp.ClientTimeout(total=self.valves.TIMEOUT_SECONDS)
            payload = {"task": task, "max_steps": self.valves.MAX_STEPS}
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(url, json=payload) as resp,
            ):
                if resp.status != 200:
                    text = await resp.text()
                    await status("Browser agent request failed", True)
                    return f"❌ BrowserUse-Opus: browser-agent returned HTTP {resp.status}:\n\n{text}"
                data = await resp.json()
        except Exception as exc:
            await status("Browser agent unreachable", True)
            return f"❌ BrowserUse-Opus: could not reach {url}: {type(exc).__name__}: {exc}"

        steps = data.get("steps", 0)
        result = data.get("result", "")
        if not data.get("success"):
            await status(f"Task failed after {steps} steps", True)
            return f"❌ **BrowserUse-Opus task failed** (after {steps} steps):\n\n{result}"

        await status(f"Done in {steps} steps", True)
        return result


# ---------------------------------------------------------------------------
# Auto-registration: `python owui_function.py --register` is run inside the
# openwebui container at startup (see docker-compose.yml). It waits for the
# OpenWebUI API, then creates/updates this file as function "browseruse" and
# activates it. Not executed when OpenWebUI loads this file as a function.
# ---------------------------------------------------------------------------
def _register(base_url: str = "http://localhost:8080", function_id: str = "browseruse"):
    import json
    import time
    import urllib.error
    import urllib.request

    def call(method, path, payload=None, token=None):
        req = urllib.request.Request(
            base_url + path,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or "null")

    for _ in range(300):
        try:
            if call("GET", "/health").get("status"):
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise SystemExit("[browseruse-register] OpenWebUI did not become healthy")

    # WEBUI_AUTH=False: signin returns a token for the built-in admin user.
    token = call("POST", "/api/v1/auths/signin", {"email": "", "password": ""})["token"]

    with open(__file__, encoding="utf-8") as f:
        content = f.read()
    form = {
        "id": function_id,
        "name": "BrowserUse-Opus",
        "content": content,
        "meta": {"description": "browser-use agent powered by Claude Opus"},
    }
    try:
        existing = call("GET", f"/api/v1/functions/id/{function_id}", token=token)
    except urllib.error.HTTPError:
        existing = None

    if existing:
        call("POST", f"/api/v1/functions/id/{function_id}/update", form, token=token)
        print(f"[browseruse-register] updated function '{function_id}'")
    else:
        call("POST", "/api/v1/functions/create", form, token=token)
        print(f"[browseruse-register] created function '{function_id}'")
        existing = {"is_active": False}

    if not existing.get("is_active"):
        call("POST", f"/api/v1/functions/id/{function_id}/toggle", token=token)
        print(f"[browseruse-register] activated function '{function_id}'")


if __name__ == "__main__":
    import sys

    if "--register" in sys.argv:
        _register()
