"""WinAuto's built-in AI: llama.cpp's server plus a Qwen3-VL model, downloaded on first run.

No separate install (like Ollama) is needed. `catalog` pins the files,
`download` fetches them (resumable, checksum-verified), `server` runs the
engine, and `manager.LocalAI` ties it together.
"""
