# The local voice model

`narrator.mode = "ai"` reads the script with [Kokoro][k], an 82M-parameter
text-to-speech model that runs on the CPU through onnxruntime. Nothing leaves
this machine and nothing is metered.

Two files go in this directory. They are ~337MB together, which is why they are
not in the repository:

```sh
pip install kokoro-onnx soundfile
B=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
curl -L -o assets/tts/kokoro-v1.0.onnx "$B/kokoro-v1.0.onnx"
curl -L -o assets/tts/voices-v1.0.bin  "$B/voices-v1.0.bin"
```

The record tab shows what is missing if either step has not been done.

**Licence.** Kokoro's weights are Apache-2.0, which is the reason it is the one
wired up here: a channel that earns money can use the output without asking
anyone. Several better-known local models are research-only or explicitly
non-commercial — XTTS-v2 is under Coqui's CPML, which forbids commercial use —
and are a bad foundation for a tool whose whole point is publishing.

[k]: https://huggingface.co/hexgrad/Kokoro-82M
