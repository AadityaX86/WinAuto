# AI models

WinAuto uses a language model running on your own PC. This page helps you pick one and tune it.

## How WinAuto uses the model

- **Instant commands don't use it.** "open spotify", "volume 30", "todo buy milk" and most everyday commands are recognised directly and run in milliseconds, even with no model installed.
- **Everything else does.** The model reads your request, picks tools (WinAuto offers only the relevant ones to keep it fast), runs them, and writes the answer.
- **Writing tools and screen questions** send the text or screenshot to the model with an instruction and show its answer.

A model needs **tool calling** (function calling) support. Not every model has it.

## Choosing a chat model

| Graphics card memory (VRAM) | Model | Download |
|---|---|---|
| 4–6 GB | `qwen3:4b` (fast, less reliable with complex requests) | `ollama pull qwen3:4b` |
| 6–8 GB | **`qwen3:8b`** (default, good balance) | `ollama pull qwen3:8b` |
| 12–16 GB | `qwen3:14b` (noticeably better at multi-step requests) | `ollama pull qwen3:14b` |
| 24 GB or more | `qwen3:32b` | `ollama pull qwen3:32b` |

Other models that handle tools well: `llama3.1:8b`, `mistral-nemo:12b`, `qwen2.5:7b`. No dedicated graphics card? `qwen3:4b` runs on the CPU, slowly.

After downloading, pick the model in **Settings → AI model** (**Find installed** lists what you have) and press **Test connection**.

"Thinking" models (Qwen3, DeepSeek-R1) are told not to think step by step for every command, which makes them much faster; WinAuto falls back automatically on older Ollama versions that don't support that.

## Vision models

For "what's on my screen?", "explain this error" and questions about images, WinAuto uses a separate **vision model**:

| VRAM | Model | Download |
|---|---|---|
| 4–6 GB | `gemma3:4b` | `ollama pull gemma3:4b` |
| 8 GB+ | **`qwen2.5vl:7b`** (default, best at reading text on screen) | `ollama pull qwen2.5vl:7b` |
| 12 GB+ | `gemma3:12b` or `llama3.2-vision:11b` | |

Set it in **Settings → AI model → Vision model**. Ollama loads one model at a time on smaller cards, so the first screen question after a chat takes a few extra seconds.

## Speed tips

- **Keep it loaded.** The model stays in memory for 30 minutes after use (`keep_alive` in [config.json](configuration.md)), so only the first request after a break is slow.
- **Context size** (Settings → AI model) is how much text the model reads at once. The default 8,192 fits WinAuto's tools comfortably. Raise it for long emails or pages if you have spare VRAM; lower it if the model doesn't fit in VRAM.
- **Close other GPU-heavy apps** (games, video editors) while using WinAuto.
- **Turn off skills you don't use** (Settings → Skills): fewer tools means faster, more accurate answers.
- **Stream answers** (on by default) shows words as they're written, so long answers feel faster.

## Other model servers

Any **OpenAI-compatible** server works: [LM Studio](https://lmstudio.ai), the llama.cpp server, Jan, vLLM, LocalAI.

1. Start the server and load a model with tool support.
2. In **Settings → AI model**, set **Server** to "OpenAI-compatible", the **Server address** (LM Studio: `http://localhost:1234/v1`), and the model name the server uses.
3. Press **Test connection**.

Vision questions use the same server with the vision model name, so load a vision model there too.

### Ollama on another computer

If a different PC on your network has the better graphics card, run Ollama there with `OLLAMA_HOST=0.0.0.0` set, and put `http://<that-pc>:11434` in **Server address**. Your requests then travel over your local network to that PC (still not to any company).
