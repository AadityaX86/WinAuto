# AI models

WinAuto's AI runs on your own PC. Out of the box it uses its **built-in AI**, which it downloads and sets up by itself. This page explains how that works, how to tune it, and how to use Ollama or another server instead.

## How WinAuto uses the model

- **Instant commands don't use it.** "open spotify", "volume 30", "todo buy milk" and most everyday commands are recognised directly and run in milliseconds, even before the AI is downloaded.
- **Everything else does.** The model reads your request, picks tools (WinAuto offers only the relevant ones to keep it fast), runs them, and writes the answer.
- **Writing tools and screen questions** send the text or screenshot to the model with an instruction and show its answer.

## The built-in AI

WinAuto runs [llama.cpp](https://github.com/ggml-org/llama.cpp), the open-source engine Ollama itself builds on, with a **Qwen3-VL** model. One model handles everything: conversation, choosing WinAuto's tools, and understanding screenshots and images.

| Model | Download | Picked when |
|---|---|---|
| **Qwen3-VL 8B** (standard) | 5.8 GB | Your graphics card has 7 GB of memory or more (or no card was detected and the PC has 16 GB of RAM or more) |
| **Qwen3-VL 4B** (small) | 3.0 GB | Smaller graphics cards, or PCs without one |

On first run WinAuto checks your graphics card and downloads the right model, plus the 37 MB engine, with a progress card on the home screen. Every file is pinned to an exact version and checked against its SHA-256 checksum, so a damaged or tampered download is rejected. Downloads resume after a pause, a lost connection or a restart.

**How it runs:**
- The engine starts in the background when WinAuto starts. Loading takes a few seconds; the dot at the bottom left turns green when it's ready.
- It uses your graphics card through **Vulkan**, which works with NVIDIA, AMD and Intel cards using their normal drivers. As much of the model as fits goes in graphics memory, the rest on the processor. If the graphics card can't be used at all, it falls back to the processor.
- It only listens on this PC (`127.0.0.1`), with a new random key each time, so other devices and web pages can't use it.
- It stops when you quit WinAuto, and Windows ends it automatically if WinAuto crashes.

**Switching models:** **Settings → AI model → Model**, then **Save**. The new one downloads right away; the old one stays on disk until you delete it (see below).

**Where the files are:** `%LOCALAPPDATA%\WinAuto\ai`, with `engine\` (the engine), `models\` (one folder per model) and `logs\engine.log`. To free space, quit WinAuto and delete a model's folder; it downloads again if needed.

## Speed tips

- **Graphics memory matters most.** If answers are slow, check the engine log for how much of the model is on the graphics card, close games and video editors while you use WinAuto, or switch to the small model.
- **Update your graphics drivers.** The Vulkan support in older drivers can be slow or missing.
- **Turn off skills you don't use** (Settings → Skills): fewer tools means faster, more accurate answers.
- **Stream answers** (on by default) shows words as they're written, so long answers feel faster.

## Using Ollama instead

If you already use [Ollama](https://ollama.com), WinAuto can use it instead of the built-in AI:

1. Install Ollama and download a model with tool support:

   | Graphics card memory | Model | Download |
   |---|---|---|
   | 4–6 GB | `qwen3:4b` | `ollama pull qwen3:4b` |
   | 6–8 GB | `qwen3:8b` | `ollama pull qwen3:8b` |
   | 12–16 GB | `qwen3:14b` | `ollama pull qwen3:14b` |
   | 24 GB or more | `qwen3:32b` | `ollama pull qwen3:32b` |

   For screen questions also download a vision model, e.g. `ollama pull qwen2.5vl:7b` (or `gemma3:4b` on smaller cards).
2. In **Settings → AI model**, set **AI engine** to **Ollama**, pick the **Chat model** (**Find installed** lists what you have) and **Vision model**, and press **Test connection**.

The built-in AI stops when you switch, freeing your graphics card. "Thinking" models (Qwen3, DeepSeek-R1) are told not to think step by step for every command, which makes them much faster. **Context size** (8,192 by default) is how much text Ollama lets the model read at once.

WinAuto 0.1 used Ollama. When upgrading, WinAuto keeps Ollama if it's installed and running, and switches to the built-in AI otherwise.

### Ollama on another computer

If a different PC on your network has a better graphics card, run Ollama there with `OLLAMA_HOST=0.0.0.0` set, and put `http://<that-pc>:11434` in **Server address**. Your requests then travel over your local network to that PC (still not to any company).

## Other servers

Any **OpenAI-compatible** server works: [LM Studio](https://lmstudio.ai), a llama.cpp server you run yourself, Jan, vLLM, LocalAI.

1. Start the server and load a model with tool support.
2. In **Settings → AI model**, set **AI engine** to "OpenAI-compatible", the **Server address** (LM Studio: `http://localhost:1234/v1`), and the model name the server uses.
3. Press **Test connection**.
