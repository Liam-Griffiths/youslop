# Local models only

Every stage that uses a language model can run on your own machines with no
account and no per-token bill: research, scripts, picture planning, titles,
pronunciation, and the steps that look at pictures. Narration already has a
local voice (Kokoro). Nothing in the pipeline needs Claude.

## The app

1. Install [LM Studio](https://lmstudio.ai) and download a model.
2. Load it with a **context length of 32k or more**. Research sends long
   prompts; a small context is the commonest cause of failures.
3. Start the server: Developer tab → Start Server (or `lms server start`).
4. In Settings → Writing model, choose **Local model (LM Studio)**, click
   **Check LM Studio**, save, and restart the app.

Leave "LM Studio model" blank to use whichever model is loaded. Ollama works
the same way: choose it, and set its address if it runs on another machine.
Any OpenAI-compatible server (llama.cpp's `llama-server`, Jan, vLLM) can use
the LM Studio option with its own address.

### What the app does for local models

- Uses the context length the model was **loaded** with (from LM Studio) and
  summarises research sources in chunks to fit it.
- Asks LM Studio for grammar-constrained JSON on JSON calls, so replies parse.
  If the server rejects that, it stops asking for the rest of the session.
  Set `CORKBORED_LMSTUDIO_JSON_MODE=0` to turn it off.
- Strips `<think>…</think>` from reasoning models before reading the answer.
- Lets reasoning models think only when writing the script ("Local model
  thinking": Auto). Everything else is sent with `reasoning_effort: none`. On
  Qwen 3.5 9B that took a small JSON call from 84 s to 4 s with the same
  answer. A server that rejects the field gets calls without it.
- Finds LM Studio's port from its own settings
  (`~/.lmstudio/apps/*/.internal/http-server-config.json`) when no address
  is set, since installs don't always use 1234.
- Multiplies call timeouts by 3 (`CORKBORED_LOCAL_TIMEOUT_FACTOR`).
- Sends pictures to a loaded vision model (LM Studio type `vlm`) or the one
  named in "LM Studio vision model".
- Explains failures in plain words: server not started, no model loaded,
  prompt too long for the loaded context, or a text-only model given pictures.

### Choosing models

Models change monthly, so choose by size and job rather than by name. The
smallest models supported are around 8–9B (Granite 4.1 8B, Qwen 3.5 9B).

| Job | Fields | What works |
|---|---|---|
| Scripts and research | LM Studio model | The largest instruct model that fits in memory at 32k context. 30B-class and up writes far better prose than 7B. |
| Planning, titles | LM Studio utility model | Optional. A smaller fast model, if both fit in memory at once; otherwise leave blank to avoid model swaps. |
| Shot review, footage labels | LM Studio vision model | Any vision-language model. Without one, those steps fail with a clear message. |

Research grounding does not depend on the model: searches run over SearXNG,
Brave or a DuckDuckGo scrape, and only fetched pages reach the model.

## The agent

The producer workflow (`.claude/skills/corkbored-producer/SKILL.md`) drives
the CLI: `new`, `check`, `snapshot`, `review`, `fix`. It is plain Markdown plus
shell commands, so any agent that reads skills can run it. OpenCode finds
skills under `.claude/skills/` and reads `CLAUDE.md`, so it works from this
repository unchanged. Point it at LM Studio in `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "lmstudio": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LM Studio",
      "options": { "baseURL": "http://127.0.0.1:1234/v1" },
      "models": { "your-model-id": { "name": "Your model" } }
    }
  }
}
```

Use the model id that `lms ls` or the Check LM Studio button shows. For the
agent, choose a model that is good at tool calling; coding-tuned models
usually are. The review step reads contact sheets, so the agent model needs
vision or should leave picture judgement to `review PID --json`, which uses
the app's vision model.

The agent and the app can share one LM Studio server and one loaded model.
