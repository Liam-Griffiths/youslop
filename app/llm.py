"""Reaches Claude one of two ways: the local `claude` CLI, or the Anthropic API.

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

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .config import (
    ANTHROPIC_API_KEY, CLAUDE_BIN, EFFORT, LLM_BACKEND, MODEL_SCRIPT,
    MODEL_UTILITY, OLLAMA_MODEL, OLLAMA_URL,
)


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


def resolve_backend() -> str:
    """Which backend a call will actually use, right now.

    "auto" — the default — prefers the CLI: it costs the user nothing beyond
    their existing subscription, where the API backend bills per token. The
    API is the fallback for a machine that was never going to have Claude Code
    on it, which is the entire point of a backend that takes a key. "ollama"
    is never chosen by auto — see the note on `OLLAMA_URL` in config.py for
    why a fully-local fallback needs to be a decision, not a default.
    """
    if LLM_BACKEND in ("cli", "api", "ollama"):
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
    return {
        "configured": LLM_BACKEND if LLM_BACKEND in ("cli", "api") else "auto",
        "resolved": resolve_backend(),
        "cli_found": cli_found,
        "cli_path": CLAUDE_BIN if cli_found else "",
        "api_key_set": bool(ANTHROPIC_API_KEY),
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
    effort: str = "",
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
    cmd.append(prompt)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
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


def _complete_api(
    prompt: str, system: str, model: str, timeout: int, allow_search: bool,
    effort: str = "",
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
        "messages": [{"role": "user", "content": prompt}],
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

    if response.stop_reason == "refusal":
        raise LLMError("Claude declined to answer this prompt.")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise LLMError("Claude returned an empty response")
    return text


def _complete_ollama(
    prompt: str, system: str, model: str, timeout: int, allow_search: bool,
    effort: str = "",
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

    body = {
        "model": OLLAMA_MODEL,
        "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.3},
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

    text = (response.json().get("message") or {}).get("content", "").strip()
    if not text:
        raise LLMError("Ollama returned an empty response")
    return text


def complete(
    prompt: str,
    system: str = "",
    model: str = MODEL_UTILITY,
    timeout: int = 600,
    allow_search: bool = False,
    effort: str = "",
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
    fn = {"api": _complete_api, "ollama": _complete_ollama}.get(backend, _complete_cli)
    return fn(prompt, system, model, timeout, allow_search, effort or EFFORT)


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
) -> Any:
    """Complete and parse a JSON reply, retrying on malformed *or wrong-shaped* output.

    `require` is the caller's definition of a usable answer. Retrying on shape as
    well as on syntax matters: a reply that parses but nests the payload under a
    wrapper key used to escape this function and blow up somewhere less obvious.
    """
    last: Exception | None = None
    original = prompt
    for attempt in range(retries + 1):
        try:
            text = complete(prompt, system=system, model=model, timeout=timeout,
                            allow_search=allow_search, effort=effort)
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
           "MODEL_SCRIPT", "MODEL_UTILITY", "resolve_backend", "backend_status"]
