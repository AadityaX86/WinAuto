"""Helpers more than one skill uses (the contact book, units, formatting).

Skill modules never import each other; shared code lives here instead, and a
skill that needs another *loaded* skill asks for it with ctx.skill(name).
"""
