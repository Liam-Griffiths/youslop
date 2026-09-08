"""Claude adapter that shells out to the local `claude` CLI.

Uses the user's Claude subscription rather than a raw ANTHROPIC_API_KEY. Every
call is one-shot (`--print`), with tools disabled so the model can only answer.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any, Callable

from .config import CLAUDE_BIN, MODEL_SCRIPT, MODEL_UTILITY


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


def complete(
    prompt: str,
    system: str = "",
    model: str = MODEL_UTILITY,
    timeout: int = 600,
    allow_search: bool = False,
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

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Unparseable CLI envelope: {proc.stdout[:400]}") from exc

    if payload.get("is_error"):
        said = str(payload.get("result"))
        if _CLOSED_DOOR.search(said):
            raise LLMUnavailable(_readable(said)[:500])
        raise LLMError(f"Claude reported an error: {said[:500]}")

    result = payload.get("result")
    if not isinstance(result, str) or not result.strip():
        raise LLMError("Claude returned an empty response")
    return result.strip()


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
                            allow_search=allow_search)
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


__all__ = ["complete", "complete_json", "LLMError", "MODEL_SCRIPT", "MODEL_UTILITY"]
