# Phase 16: local models, first class

Owner, 2026-11-08: support creators who use no frontier model at all. Local
models are getting capable, and these projects use a lot of tokens.

The LM Studio backend, thinking control, reply caps, port detection and the
"Writing model" settings landed in commit f2cef05 (see `docs/local-models.md`).
These tickets come from live test runs on the owner's machine (Radeon 780M
iGPU, about 14 tokens/s on a 9B model):

- Granite 4.1 8B built a full `--test` project in about 4½ minutes.
- Qwen 3.5 9B with thinking on took 45+ minutes, then looped on the fact check.

The smallest supported models are around 8–9B (Granite 4.1 8B, Qwen 3.5 9B).

| Ticket | What |
|---|---|
| T16.1 | Live progress during model calls |
| T16.2 | Write sections in order for local models |
| T16.3 | A default User-Agent that archives accept (done) |
| T16.4 | Script consistency check |
| T16.5 | Speed test and thinking advice in Check LM Studio |

Picture queries that no archive can match ("airburst explosion energy release
megatons TNT") were seen too. That finding is folded into T15.2.

**Testing rule for this phase:** unit tests never call a real model. When a
ticket asks for a live check, the reviewer runs it against the owner's LM
Studio (`~/.lmstudio/bin/lms`, port 1235), one `--test` project at most.
