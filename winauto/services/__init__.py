"""Application services: what the UI asks of the app, in plain Python.

The UI (winauto/ui) talks to these and to the core types only. It never
reaches into a skill, the database or a Windows API itself, so the same
logic can be tested without Qt and reused by another front end.
"""
