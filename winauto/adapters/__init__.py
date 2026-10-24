"""Adapters: the only code that talks to the outside world.

Windows APIs (winos), the SQLite database (storage), web requests (http),
the AI model servers (llm), Gmail (gmail) and Windows Credential Manager
(secrets) all live here, so features and the engine stay plain Python that
is easy to test.
"""
