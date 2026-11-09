"""Reaches a language model: the `claude` CLI or the Anthropic API by default,
or, when chosen in Settings, a local model (LM Studio or Ollama) or another
hosted provider. The first two paragraphs below describe the original pair.

The CLI is billed to the user's own Claude subscription and was the only
backend that existed before this — every call is one-shot (`--print`), with
tools disabled so the model can only answer. The API backend exists for a
machine that was never going to have Claude Code installed: it takes an
`ANTHROPIC_API_KEY` and calls `POST /v1/messages` directly. `resolve_backend()`
picks between them; everything downstream of `complete()` is the same either
way, which is the point — `script_gen.py` and `research.py` write "opus" or
"sonnet" and never know which backend answered.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from . import brand
from .config import (
    ANTHROPIC_API_KEY, CLAUDE_BIN, EFFORT, LLM_BACKEND, LMSTUDIO_JSON_MODE,
    LMSTUDIO_MODEL, LMSTUDIO_MODEL_UTILITY, LMSTUDIO_THINKING, LMSTUDIO_MODEL_VISION, LMSTUDIO_URL,
    LOCAL_TIMEOUT_FACTOR, MODEL_SCRIPT, MODEL_UTILITY, OLLAMA_CONTEXT,
    OLLAMA_MODEL, OLLAMA_URL, OPENAI_COMPAT,
)

log = logging.getLogger(f"{brand.SLUG}.llm")
_USAGE = ContextVar('llm_usage', default=None)
# Set by complete_json() so a backend that can constrain its output to JSON
# does, without changing complete()'s signature for every caller.
_WANT_JSON = ContextVar('llm_want_json', default=False)


@contextmanager
def capture_usage():
    records = []
    token = _USAGE.set(records)
    try:
        yield records
    finally:
        _USAGE.reset(token)


def _record_usage(model, usage):
    records = _USAGE.get()
    if records is not None:
        records.append(dict(model=model, usage=usage or {}))


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """A failure that retrying cannot fix: usage limits, auth, a missing CLI.

    Separate from LLMError because the retry loop treats a bad *reply* as
    something a re-prompt might correct. A closed door is not that: three
    attempts against a spent usage limit only spend the time.
    """


def _readable(said: str) -> str:
    """The CLI reports a reset as `...limit reached|1748955600`. Say the time."""
    m = re.search(r"\|(\d{9,11})\b", said)
    if not m:
        return said
    try:
        when = time.localtime(int(m.group(1)))
    except (ValueError, OSError):
        return said
    return (said[:m.start()].strip()
            + f" — it resets at {time.strftime('%H:%M on %a %d %b', when)}")


# Things the CLI says when the problem is the account rather than the prompt.
_CLOSED_DOOR = re.compile(
    r"usage limit|rate.?limit|quota|too many requests|429|"
    r"not logged in|log ?in|authenticat|unauthorized|invalid api key|"
    r"credit balance|billing|subscription",
    re.I,
)

# CLI aliases mapped onto real Anthropic model ids, for the API backend. A
# model id passed straight through (anyone who set VB_MODEL_SCRIPT to a real
# id rather than an alias) is used as-is.
MODEL_API_IDS = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
}


def _api_model_id(model: str) -> str:
    return MODEL_API_IDS.get(model, model)


# Every backend that can be named explicitly. "auto" is not one: it resolves
# to "cli" or "api", never to a local model (see resolve_backend()).
BACKENDS = ("cli", "api", "ollama", "lmstudio", *OPENAI_COMPAT)
LOCAL_BACKENDS = ("ollama", "lmstudio")
BACKEND_LABELS = {"cli": "Claude CLI", "api": "Anthropic API", "ollama": "Ollama",
                  "lmstudio": "LM Studio",
                  **{k: v["label"] for k, v in OPENAI_COMPAT.items()}}


def resolve_backend() -> str:
    """Which backend a call will actually use, right now.

    "auto" — the default — prefers the CLI: it costs the user nothing beyond
    their existing subscription, where the API backend bills per token. The
    API is the fallback for a machine that was never going to have Claude Code
    on it, which is the entire point of a backend that takes a key. "ollama"
    is never chosen by auto — see the note on `OLLAMA_URL` in config.py for
    why a fully-local fallback needs to be a decision, not a default.
    """
    if LLM_BACKEND in BACKENDS:
        return LLM_BACKEND
    if shutil.which(CLAUDE_BIN) or Path(CLAUDE_BIN).is_file():
        return "cli"
    if ANTHROPIC_API_KEY:
        return "api"
    return "cli"      # neither is available; fail there with the clearer message


def backend_status() -> dict:
    """What Settings (and a startup self-check) should show about this.

    Deliberately doesn't try either backend — this is "what would run",
    not "does it work", which a cheap check should never need a network call
    or a subprocess to answer.
    """
    cli_found = bool(shutil.which(CLAUDE_BIN)
                     or Path(CLAUDE_BIN).is_file())
    resolved = resolve_backend()
    return {
        "configured": LLM_BACKEND if LLM_BACKEND in BACKENDS else "auto",
        "resolved": resolved,
        "label": BACKEND_LABELS.get(resolved, resolved),
        "local": resolved in LOCAL_BACKENDS,
        "cli_found": cli_found,
        "cli_path": CLAUDE_BIN if cli_found else "",
        "api_key_set": bool(ANTHROPIC_API_KEY),
        "lmstudio_url": LMSTUDIO_URL,
    }


def _envelope(stdout: str) -> dict | None:
    """The CLI's JSON result, found in whatever else landed on stdout.

    A version manager's shim can print its own line first — mise announces
    "mise ~/.config/mise/config.toml tools: claude@…" before handing over — so
    the envelope is not always the whole of stdout. It is the last line that
    parses as a JSON object; failing that, the text from the first "{".
    """
    text = stdout.strip()
    try:
        whole = json.loads(text)
        return whole if isinstance(whole, dict) else None
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    at = text.find("{")
    if at > 0:
        try:
            obj = json.loads(text[at:])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
    return None


def _complete_cli(
    prompt: str, system: str, model: str, timeout: int, allow_search: bool,
    effort: str = "", images: list[bytes] | None = None,
) -> str:
    """Run a single prompt through the Claude CLI and return the text reply.

    Every call disallows touching this machine — no filesystem, no shell, no
    sub-agents. `allow_search` is the one exception: a research call is let
    loose on `WebSearch`/`WebFetch` so it can ground what it writes in an
    actual source instead of only what the model already remembers.
    """
    disallowed = "Bash,Edit,Write,Read,Glob,Grep,Task"
    if not allow_search:
        disallowed += ",WebFetch,WebSearch"
    cmd = [
        CLAUDE_BIN,
        "--print",
        "--output-format", "json",
        "--model", model,
        # `=`, not a separate argv token: --disallowed-tools takes a variadic
        # list and a bare token straight after it — the prompt, whenever there
        # is no --system-prompt to stop it first — gets read as one more tool
        # name, and the prompt silently vanishes. `=` binds the value to the
        # flag with nothing left for it to swallow.
        f"--disallowed-tools={disallowed}",
    ]
    if effort:
        cmd += ["--effort", effort]
    if system:
        cmd += ["--system-prompt", system]
    stdin = None
    if images:
        # Pictures go in as one stream-json user message with inline image
        # blocks, so the CLI never needs to read a file from this machine.
        # Its reply comes back as stream-json too; _envelope() takes the last
        # line, which is the same result object --output-format json gives.
        i = cmd.index("json")
        cmd[i] = "stream-json"
        cmd += ["--input-format", "stream-json", "--verbose"]
        stdin = json.dumps({"type": "user", "message": {"role": "user", "content": _image_blocks(images, prompt)}}) + "\n"
    else:
        cmd.append(prompt)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False, input=stdin
        )
    except FileNotFoundError as exc:
        raise LLMError(
            f"Could not find the Claude CLI at {CLAUDE_BIN!r}. Install Claude Code "
            "or set CLAUDE_BIN in .env"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMError(f"Claude call timed out after {timeout}s") from exc

    if proc.returncode != 0:
        said = (proc.stderr.strip() or proc.stdout.strip()
                or "no output on stderr or stdout")
        if _CLOSED_DOOR.search(said):
            raise LLMUnavailable(_readable(said)[:800])
        raise LLMError(f"claude exited {proc.returncode}: {said[:800]}")

    payload = _envelope(proc.stdout)
    if payload is None:
        raise LLMError(f"Unparseable CLI envelope: {proc.stdout[:400]}")
    _record_usage(model, payload.get('usage'))

    if payload.get("is_error"):
        said = str(payload.get("result"))
        if _CLOSED_DOOR.search(said):
            raise LLMUnavailable(_readable(said)[:500])
        raise LLMError(f"Claude reported an error: {said[:500]}")

    result = payload.get("result")
    if not isinstance(result, str) or not result.strip():
        raise LLMError("Claude returned an empty response")
    return result.strip()


# Generous enough for a script-writing call (a handful of paragraphs of
# prose) without the SDK's streaming requirement, which only bites above
# ~21,000 tokens on a non-streaming call. Nothing in this codebase writes
# that much in one completion.
API_MAX_TOKENS = 8192


def _image_blocks(images: list[bytes], prompt: str) -> list[dict]:
    """Anthropic content blocks: each picture (JPEG or PNG bytes), then the text."""
    blocks: list[dict] = []
    for data in images:
        kind = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": kind,
                                                   "data": base64.b64encode(data).decode()}})
    blocks.append({"type": "text", "text": prompt})
    return blocks


def _complete_api(
    prompt: str, system: str, model: str, timeout: int, allow_search: bool,
    effort: str = "", images: list[bytes] | None = None,
) -> str:
    """The same prompt, answered by the Anthropic API instead of the CLI.

    No sandbox to disallow tools from here — a raw API call touches nothing
    on this machine by construction. `allow_search` turns on Anthropic's
    server-side web search, which runs on Anthropic's infrastructure and
    returns its results as part of the same response; there is no client-side
    loop to drive, the way there would be for a tool this process executes
    itself.
    """
    import anthropic

    if not ANTHROPIC_API_KEY:
        cli_found = bool(shutil.which(CLAUDE_BIN) or Path(CLAUDE_BIN).is_file())
        raise LLMUnavailable(
            "No Anthropic API key configured"
            + (", and the Claude CLI was not found either"
               if not cli_found else " (the API backend was selected explicitly)")
            + ". Set an API key in Settings, or install Claude Code and sign in."
        )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=float(timeout))
    kwargs: dict[str, Any] = {
        "model": _api_model_id(model),
        "max_tokens": API_MAX_TOKENS,
        "messages": [{"role": "user", "content": _image_blocks(images, prompt) if images else prompt}],
    }
    if system:
        kwargs["system"] = system
    if allow_search:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]
    if effort:
        kwargs["output_config"] = {"effort": effort}

    try:
        response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable(f"The Anthropic API key was rejected: {exc}") from exc
    except anthropic.RateLimitError as exc:
        retry_after = exc.response.headers.get("retry-after", "") if exc.response else ""
        said = "Anthropic API rate limit hit"
        if retry_after:
            said += f" — retry after {retry_after}s"
        raise LLMUnavailable(said) from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMUnavailable(f"The Anthropic API key lacks permission: {exc}") from exc
    except anthropic.APIStatusError as exc:
        # >=500 (including 529 "overloaded") is the API's own door being
        # closed for the moment, not a problem with this particular prompt —
        # same reasoning the CLI's _CLOSED_DOOR regex encodes.
        if exc.status_code >= 500:
            raise LLMUnavailable(f"Anthropic API error {exc.status_code}: {exc}") from exc
        raise LLMError(f"Anthropic API error {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable(f"Could not reach the Anthropic API: {exc}") from exc

    _record_usage(response.model, response.usage.model_dump())
    if response.stop_reason == "refusal":
        raise LLMError("Claude declined to answer this prompt.")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise LLMError("Claude returned an empty response")
    return text


def _complete_ollama(
    prompt: str, system: str, model: str, timeout: int, allow_search: bool,
    effort: str = "", images: list[bytes] | None = None,
) -> str:
    """The same prompt, answered by a local Ollama daemon.

    `model` — the "opus"/"sonnet" alias every caller writes — is accepted but
    ignored: a single local 7B-class model has no cheap/capable split the way
    Claude does, so `OLLAMA_MODEL` always answers, whichever alias was asked
    for. `allow_search` is ignored too; nothing here can run a tool. `effort`
    is also ignored — there is no equivalent knob on a plain chat completion,
    and a fixed `temperature` already does the only tuning this backend has.
    """
    import httpx

    # Roughly four characters to a token for English prose. A prompt that
    # cannot fit is cut off by Ollama without a word, so say so in the log.
    approx_tokens = (len(system) + len(prompt)) // 4
    if approx_tokens > OLLAMA_CONTEXT:
        log.warning("ollama: prompt is about %d tokens, over the %d-token context "
                    f"({brand.ENV_PREFIX}OLLAMA_CONTEXT); the model will not see all of it",
                    approx_tokens, OLLAMA_CONTEXT)
    body = {
        "model": OLLAMA_MODEL,
        "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt,
                        # a vision model reads these; a text-only one ignores them
                        **({"images": [base64.b64encode(d).decode() for d in images]} if images else {})}],
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": OLLAMA_CONTEXT},
    }
    try:
        response = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
    except httpx.ConnectError as exc:
        raise LLMUnavailable(
            f"Could not reach Ollama at {OLLAMA_URL} — is `ollama serve` "
            f"running? ({exc})"
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMError(f"Ollama call timed out after {timeout}s") from exc

    if response.status_code == 404:
        raise LLMUnavailable(
            f"Ollama has no model called {OLLAMA_MODEL!r}. "
            f"Run: ollama pull {OLLAMA_MODEL}"
        )
    if response.status_code != 200:
        raise LLMError(f"Ollama error {response.status_code}: {response.text[:400]}")

    payload = response.json()
    _record_usage(payload.get('model', OLLAMA_MODEL),
                  dict(input_tokens=payload.get('prompt_eval_count', 0), output_tokens=payload.get('eval_count', 0)))
    text = strip_reasoning((payload.get("message") or {}).get("content", ""))
    if not text:
        raise LLMError("Ollama returned an empty response")
    return text


def _complete_openai_compat(
    provider: str, prompt: str, system: str, model: str, timeout: int,
    allow_search: bool, effort: str = "",
) -> str:
    """The same prompt, answered by OpenAI, DeepSeek or xAI through their
    chat-completions endpoint. One client for all three, because they share the
    protocol; only the base URL, key and model names differ.

    `model` is the alias every caller writes: MODEL_SCRIPT and MODEL_UTILITY map
    to that provider's script and utility model, and anything else is passed
    through as a real model id. `allow_search` and `effort` are ignored — these
    are plain completions here, and research's search runs in app/research.py.
    """
    import httpx

    cfg = OPENAI_COMPAT[provider]
    if not cfg["key"]:
        raise LLMUnavailable(f"No {cfg['label']} API key configured. Set one in "
                             "Settings, or choose another way to reach Claude.")
    if model == MODEL_SCRIPT:
        model = cfg["script"]
    elif model == MODEL_UTILITY:
        model = cfg["utility"]

    messages = ([{"role": "system", "content": system}] if system else []) \
               + [{"role": "user", "content": prompt}]
    try:
        response = httpx.post(
            f"{cfg['base']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['key']}"},
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise LLMError(f"{cfg['label']} call timed out after {timeout}s") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Could not reach {cfg['label']}: {exc}") from exc

    if response.status_code in (401, 403):
        raise LLMUnavailable(f"The {cfg['label']} API key was rejected "
                             f"({response.status_code}).")
    # 429 is "slow down" or "out of credit" — the provider's door is shut for
    # now, not a problem with this prompt, so the retry loop should not spin.
    if response.status_code == 429 or response.status_code >= 500:
        raise LLMUnavailable(f"{cfg['label']} is unavailable right now "
                             f"({response.status_code}): {response.text[:300]}")
    if response.status_code != 200:
        raise LLMError(f"{cfg['label']} error {response.status_code}: "
                       f"{response.text[:400]}")

    try:
        _record_usage(model, response.json().get('usage'))
        text = response.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected {cfg['label']} reply: {response.text[:300]}") from exc
    text = text.strip()
    if not text:
        raise LLMError(f"{cfg['label']} returned an empty response")
    return text

# ------------------------------------------------------------------ LM Studio
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def strip_reasoning(text: str) -> str:
    """The answer without a local reasoning model's visible thinking.

    Qwen3, DeepSeek-R1 distills and similar write `<think>…</think>` before
    the answer. Left in, that block holds draft JSON and stray braces which
    `_extract_json` can take for the real reply. Some chat templates send the
    opening tag in the prompt, so the reply has only the closing one.
    """
    text = _THINK.sub("", text or "")
    if "</think>" in text.lower():
        text = text[text.lower().rindex("</think>") + len("</think>"):]
    return text.strip()


# What LM Studio says when a prompt overflows the loaded context. llama.cpp
# and MLX word it differently, and so do LM Studio versions.
_CONTEXT_FULL = re.compile(
    r"context (length|window|size)|n_ctx|tokens to keep|exceeds? the|"
    r"too (long|many tokens)|maximum context", re.I)

# The loaded model, detected rather than configured, cached for a short time.
# One models request per call would be cheap, but a project makes hundreds of
# calls; 30 seconds still notices a model swapped in LM Studio between stages.
_DETECT_TTL = 30.0
_detected: dict[str, Any] = {"at": 0.0, "models": None}


LOCAL_MAX_TOKENS = 6144
LOCAL_MAX_TOKENS_THINKING = 16384
_json_mode = {"on": LMSTUDIO_JSON_MODE}
_effort_ok = {"on": True}


def _lmstudio_effort(alias: str, effort: str) -> str | None:
    """`reasoning_effort` for this call, or None to leave the model's default.

    LM Studio honours "none" on reasoning models (Qwen 3.5 measured: 84 s →
    4 s on a small JSON call); `reasoning.effort` and `enable_thinking` were
    ignored. The app-wide effort setting picks the level when thinking is on.
    """
    if LMSTUDIO_THINKING == "off":
        return "none"
    if LMSTUDIO_THINKING != "on" and alias != MODEL_SCRIPT:
        return "none"
    if effort in ("low", "medium", "high"):
        return effort
    if effort in ("xhigh", "max"):
        return "high"
    return None


def _lmstudio_root() -> str:
    """The server root without the OpenAI `/v1` suffix, for LM Studio's own
    REST API, which reports which models are loaded and their context."""
    return re.sub(r"/v1$", "", LMSTUDIO_URL)


def lmstudio_models(timeout: float = 5.0, fresh: bool = False) -> list[dict]:
    """What the server has: id, kind, loaded and context per model.

    LM Studio's own `/api/v0/models` gives the loaded state and context
    length. A plain OpenAI-compatible server only has `/v1/models`, and for
    those `loaded` and `context` are None ("not known"), not False.
    Raises LLMUnavailable when the server cannot be reached at all.
    """
    import httpx

    now = time.monotonic()
    if not fresh and _detected["models"] is not None and now - _detected["at"] < _DETECT_TTL:
        return _detected["models"]
    models: list[dict] | None = None
    try:
        r = httpx.get(f"{_lmstudio_root()}/api/v0/models", timeout=timeout)
        if r.status_code == 200 and isinstance(r.json().get("data"), list):
            models = [{
                "id": m.get("id", ""),
                "kind": m.get("type") or "",
                "loaded": m.get("state") == "loaded",
                "context": (m.get("loaded_context_length")
                            or (m.get("max_context_length") if m.get("state") == "loaded"
                                and "loaded_context_length" not in m else None)),
                "max_context": m.get("max_context_length"),
            } for m in r.json()["data"] if m.get("id")]
        if models is None:
            r = httpx.get(f"{LMSTUDIO_URL}/models", timeout=timeout)
            r.raise_for_status()
            models = [{"id": m.get("id", ""), "kind": "", "loaded": None,
                       "context": None, "max_context": None}
                      for m in r.json().get("data", []) if m.get("id")]
    except httpx.HTTPError as exc:
        raise LLMUnavailable(
            f"Could not reach LM Studio at {LMSTUDIO_URL}. Open LM Studio, go to "
            "the Developer tab and start the server (or run `lms server start`). "
            f"({type(exc).__name__}: {exc})") from exc
    except ValueError as exc:
        raise LLMUnavailable(f"{LMSTUDIO_URL} did not answer like an "
                             "OpenAI-compatible server.") from exc
    _detected.update(at=now, models=models)
    return models


def _is_chat_model(m: dict) -> bool:
    return m["kind"] not in ("embeddings", "embedding") and "embed" not in m["id"].lower()


def _lmstudio_model(alias: str, vision: bool = False) -> str:
    """The model id to send for an "opus"/"sonnet"-style alias.

    `vision` is a call that carries pictures: it takes the vision model when
    one is named, else a loaded vision model (LM Studio reports type "vlm")
    ahead of the usual choice."""
    if vision:
        if LMSTUDIO_MODEL_VISION:
            return LMSTUDIO_MODEL_VISION
        try:
            vlm = [m for m in lmstudio_models() if m["kind"] == "vlm" and m["loaded"]]
        except LLMUnavailable:
            vlm = []
        if vlm:
            return vlm[0]["id"]
    if alias == MODEL_UTILITY and LMSTUDIO_MODEL_UTILITY:
        return LMSTUDIO_MODEL_UTILITY
    if alias in (MODEL_SCRIPT, MODEL_UTILITY, *MODEL_API_IDS):
        if LMSTUDIO_MODEL:
            return LMSTUDIO_MODEL
        chat = [m for m in lmstudio_models() if _is_chat_model(m)]
        loaded = [m for m in chat if m["loaded"]]
        if loaded:
            return loaded[0]["id"]
        if chat and all(m["loaded"] is None for m in chat):
            return chat[0]["id"]          # a generic server: it serves what it lists
        raise LLMUnavailable(
            "LM Studio is running but has no model loaded. Load one in LM Studio "
            "(Developer tab, or `lms load <model>`), or name a model in Settings."
            + (f" Downloaded: {', '.join(m['id'] for m in chat[:6])}." if chat else ""))
    return alias                          # a real model id, passed straight through


def local_context_tokens() -> int | None:
    """The local model's context window in tokens, or None for a hosted
    backend whose window is large enough not to plan around.

    For LM Studio this is the loaded model's actual context length when the
    server reports it, because that, not a setting here, is what LM Studio
    truncates or refuses at. Falls back to the context-window setting.
    """
    backend = resolve_backend()
    if backend == "ollama":
        return OLLAMA_CONTEXT
    if backend != "lmstudio":
        return None
    try:
        model = _lmstudio_model(MODEL_SCRIPT)
        for m in lmstudio_models():
            if m["id"] == model and m["context"]:
                return int(m["context"])
    except LLMError:
        pass
    return OLLAMA_CONTEXT


def _openai_user_content(prompt: str, images: list[bytes] | None) -> Any:
    if not images:
        return prompt
    parts: list[dict] = [{"type": "text", "text": prompt}]
    for data in images:
        kind = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        parts.append({"type": "image_url", "image_url": {
            "url": f"data:{kind};base64,{base64.b64encode(data).decode()}"}})
    return parts


def _complete_lmstudio(
    prompt: str, system: str, model: str, timeout: int, allow_search: bool,
    effort: str = "", images: list[bytes] | None = None,
) -> str:
    """The same prompt, answered by a model loaded in LM Studio.

    `model` is the usual alias; see `_lmstudio_model()` for how it becomes a
    loaded model. `allow_search` and `effort` are ignored: research searches
    on its own in app/research.py. `effort` and the thinking setting become
    `reasoning_effort`; see `_lmstudio_effort()`.
    Pictures are sent as OpenAI image parts, which a vision model (VLM) reads.
    """
    import httpx

    model_id = _lmstudio_model(model, vision=bool(images))
    approx_tokens = (len(system) + len(prompt)) // 4
    window = local_context_tokens()
    if window and approx_tokens > window:
        log.warning("lmstudio: prompt is about %d tokens, over the loaded %d-token "
                    "context of %s", approx_tokens, window, model_id)
    body = {
        "model": model_id,
        "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": _openai_user_content(prompt, images)}],
        "temperature": 0.3,
        "stream": False,
    }
    # Grammar-constrained JSON: the commonest way a local model fails a JSON
    # call is prose or a cut-off brace, and constraining the sampler removes
    # that. The schema allows any object or array; each caller's `require`
    # still checks the shape.
    level = _lmstudio_effort(model, effort) if _effort_ok["on"] else None
    if level:
        body["reasoning_effort"] = level
    # A ceiling on the reply. Small local models can loop: Qwen 3.5 9B once
    # wrote 16,000 tokens into one JSON string on a fact check that needed
    # 300, until the timeout ended it 19 minutes later. Measured normal
    # replies: chores 88–302 tokens; script calls 4–8k thinking + ~1k answer.
    body["max_tokens"] = LOCAL_MAX_TOKENS if level == "none" else LOCAL_MAX_TOKENS_THINKING
    constrained = _WANT_JSON.get() and _json_mode["on"]
    if constrained:
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "reply", "schema": {"anyOf": [{"type": "object"}, {"type": "array"}]}}}

    def send(payload):
        try:
            return httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=payload,
                              timeout=timeout)
        except httpx.TimeoutException as exc:
            raise LLMError(f"LM Studio call timed out after {timeout}s. A large model "
                           "on this machine may need a smaller model or GPU offload.") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                f"Could not reach LM Studio at {LMSTUDIO_URL}. Open LM Studio, go to "
                f"the Developer tab and start the server. ({exc})") from exc

    response = send(body)
    if (constrained and response.status_code == 400
            and re.search(r"response_format|json_schema|grammar|schema", response.text, re.I)):
        log.info("lmstudio: server rejected response_format; sending JSON calls "
                 "unconstrained for this session")
        _json_mode["on"] = False
        body.pop("response_format")
        response = send(body)
    if (level and response.status_code == 400
            and re.search(r"reasoning", response.text, re.I)):
        log.info("lmstudio: server rejected reasoning_effort; leaving it out "
                 "for this session")
        _effort_ok["on"] = False
        body.pop("reasoning_effort")
        response = send(body)

    said = response.text[:600]
    if response.status_code != 200:
        _detected["models"] = None        # the loaded model may have changed
        if _CONTEXT_FULL.search(said):
            raise LLMUnavailable(
                f"The prompt (about {approx_tokens} tokens) does not fit the context "
                f"{model_id} was loaded with in LM Studio. Reload it with a larger "
                "context length (model settings → Context Length; 32k or more suits "
                f"research), or pick a smaller research depth. LM Studio said: {said}")
        if response.status_code == 404 or re.search(r"model.*(not found|not loaded)|no models? loaded", said, re.I):
            raise LLMUnavailable(f"LM Studio could not use model {model_id!r}: {said}")
        if images and re.search(r"image|vision|multimodal", said, re.I):
            raise LLMUnavailable(f"{model_id} cannot read pictures. Load a vision "
                                 f"model in LM Studio for this step. ({said})")
        if response.status_code >= 500:
            raise LLMError(f"LM Studio error {response.status_code}: {said}")
        raise LLMError(f"LM Studio error {response.status_code}: {said}")

    try:
        payload = response.json()
        text = payload["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise LLMError(f"Unexpected LM Studio reply: {said[:300]}") from exc
    usage = payload.get("usage") or {}
    _record_usage(payload.get("model", model_id),
                  dict(usage, input_tokens=usage.get("prompt_tokens", 0),
                       output_tokens=usage.get("completion_tokens", 0)))
    if payload["choices"][0].get("finish_reason") == "length":
        # Cut off at max_tokens. A JSON reply then fails to parse and is
        # retried with the rejection noted; plain text is used as it stands.
        log.warning("lmstudio: %s hit the %d-token reply limit", model_id, body["max_tokens"])
    text = strip_reasoning(text)
    if not text:
        raise LLMError(f"LM Studio ({model_id}) returned an empty response")
    return text


def local_probe() -> dict:
    """A live check of the LM Studio server, for the Settings button.

    One GET to the configured local URL, nothing else: no prompt is sent, so
    it is quick and loads no model. Says what would answer and warns about the
    one setting that most often breaks research: a small loaded context.
    """
    out: dict[str, Any] = {"url": LMSTUDIO_URL, "reachable": False, "models": [],
                           "model": "", "context": None, "warning": ""}
    try:
        models = lmstudio_models(fresh=True)
    except LLMUnavailable as exc:
        out["warning"] = str(exc)
        return out
    out["reachable"] = True
    out["models"] = [m for m in models if _is_chat_model(m)]
    try:
        out["model"] = _lmstudio_model(MODEL_SCRIPT)
    except LLMUnavailable as exc:
        out["warning"] = str(exc)
        return out
    match = next((m for m in models if m["id"] == out["model"]), None)
    out["context"] = match["context"] if match else None
    if out["context"] and out["context"] < 16384:
        out["warning"] = (f"{out['model']} is loaded with a {out['context']}-token "
                          "context. Research sends long prompts; reload it in LM "
                          "Studio with 16k or more (32k is better).")
    elif match is None and LMSTUDIO_MODEL:
        out["warning"] = (f"LM Studio does not list {LMSTUDIO_MODEL!r}. Check the "
                          "model name in Settings, or leave it blank to use "
                          "whichever model is loaded.")
    return out


def complete(
    prompt: str,
    system: str = "",
    model: str = MODEL_UTILITY,
    timeout: int = 600,
    allow_search: bool = False,
    effort: str = "",
    images: list[bytes] | None = None,
) -> str:
    """Run a single prompt through whichever backend is configured.

    Everything above `complete()` is backend-specific; everything below it —
    `script_gen.py`, `research.py`, every `complete_json` caller — reaches
    Claude through this one function and never knows which backend answered.
    See `resolve_backend()` for how the choice is made. `effort` defaults to
    the app-wide `EFFORT` setting rather than to nothing, so changing it in
    Settings doesn't require updating every call site — a caller that wants a
    different level for just this one call can still pass its own.
    """
    backend = resolve_backend()
    if backend in LOCAL_BACKENDS:
        timeout = int(timeout * LOCAL_TIMEOUT_FACTOR)
    if backend in OPENAI_COMPAT:
        return _complete_openai_compat(backend, prompt, system, model, timeout,
                                       allow_search, effort or EFFORT)
    fn = {"api": _complete_api, "ollama": _complete_ollama,
          "lmstudio": _complete_lmstudio}.get(backend, _complete_cli)
    return fn(prompt, system, model, timeout, allow_search, effort or EFFORT, images)


# --------------------------------------------------------------- json helpers
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _balanced(text: str, opener: str, closer: str) -> list[Any]:
    """Every top-level balanced {...} or [...] in the text that parses."""
    found, i, n = [], 0, len(text)
    while i < n:
        start = text.find(opener, i)
        if start == -1:
            break
        depth, in_str, esc, end = 0, False, False, -1
        for j in range(start, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end == -1:
            break
        try:
            found.append(json.loads(text[start : end + 1]))
        except json.JSONDecodeError:
            pass
        i = end + 1
    return found


def _extract_json(text: str, require: Callable[[Any], bool] | None = None) -> Any:
    """Pull a JSON value out of a reply that may be fenced or have chatter.

    Collects every candidate rather than returning the first that parses. A model
    that emits a short aside object before the real answer used to hand us the
    aside; `require` lets the caller say what the real answer looks like, and the
    largest candidate wins otherwise.
    """
    candidates: list[Any] = []
    for blob in (text, *(m.group(1) for m in _FENCE.finditer(text))):
        try:
            candidates.append(json.loads(blob.strip()))
        except json.JSONDecodeError:
            pass
    for opener, closer in (("{", "}"), ("[", "]")):
        candidates.extend(_balanced(text, opener, closer))

    if not candidates:
        raise LLMError(f"No JSON found in reply: {text[:400]}")
    if require:
        for c in candidates:
            if require(c):
                return c
    # Prefer the richest structure: a nested aside is almost always the small one.
    return max(candidates, key=lambda c: len(json.dumps(c)))


JSON_SYSTEM = (
    "You are a backend component in a video production pipeline. You reply with "
    "one raw JSON value and nothing else: no prose, no markdown fences, no "
    "commentary before or after. Never apologise, never explain."
)


def complete_json(
    prompt: str,
    system: str = JSON_SYSTEM,
    model: str = MODEL_UTILITY,
    timeout: int = 600,
    retries: int = 2,
    require: Callable[[Any], bool] | None = None,
    require_hint: str = "",
    allow_search: bool = False,
    effort: str = "",
    images: list[bytes] | None = None,
) -> Any:
    """Complete and parse a JSON reply, retrying on malformed *or wrong-shaped* output.

    `require` is the caller's definition of a usable answer. Retrying on shape as
    well as on syntax matters: a reply that parses but nests the payload under a
    wrapper key used to escape this function and blow up somewhere less obvious.
    """
    want = _WANT_JSON.set(True)
    try:
        return _complete_json_attempts(prompt, prompt, system, model, timeout, retries,
                                       require, require_hint, allow_search, effort, images)
    finally:
        _WANT_JSON.reset(want)


def _complete_json_attempts(prompt, original, system, model, timeout, retries,
                            require, require_hint, allow_search, effort, images):
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            text = complete(prompt, system=system, model=model, timeout=timeout,
                            allow_search=allow_search, effort=effort, images=images)
            value = _extract_json(text, require)
            if require and not require(value):
                shape = (f"a {type(value).__name__} with keys "
                         f"{sorted(value)[:12]}" if isinstance(value, dict)
                         else f"a {type(value).__name__}")
                raise LLMError(f"Reply had the wrong shape: got {shape}")
            return value
        except LLMUnavailable:
            raise
        except LLMError as exc:
            last = exc
            if attempt < retries:
                prompt = (
                    original
                    + f"\n\nYour previous reply was rejected: {exc}. "
                    + (f"{require_hint} " if require_hint else "")
                    + "Return the raw JSON value only, at the top level, "
                    "with no wrapper object around it."
                )
    raise LLMError(f"Failed after {retries + 1} attempts: {last}")


__all__ = ["complete", "complete_json", "LLMError", "LLMUnavailable",
           "MODEL_SCRIPT", "MODEL_UTILITY", "resolve_backend", "backend_status",
           "local_context_tokens", "local_probe", "strip_reasoning"]
