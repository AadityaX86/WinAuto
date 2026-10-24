"""Terminal mode, handy for testing skills without the popup.

    python -m winauto --cli
"""

from __future__ import annotations

import sys

from winauto.core.agent import ConfirmRequest, Decision
from winauto.log import setup_logging


class ConsoleConfirmer:
    def confirm(self, request: ConfirmRequest) -> Decision:
        print(f"\n--- {request.title} ---\n{request.preview}")
        edits = {}
        for name in request.editable:
            current = request.args.get(name, "")
            new = input(f"{name} [{current}] (Enter keeps it): ").strip()
            if new:
                edits[name] = new
        answer = input(f"{request.confirm_label}? [y/N] ").strip().lower()
        return Decision(answer in ("y", "yes"), edits or None)


def main() -> None:
    import logging

    setup_logging(logging.WARNING)
    from winauto.runtime import Runtime

    rt = Runtime(ConsoleConfirmer(), notify=lambda t, m: print(f"\n[{t}] {m}"),
                 on_status=lambda s: print(f"  ({s})", file=sys.stderr))
    rt.start()
    ok, msg = rt.llm.check()
    print(f"WinAuto terminal mode. {msg}\nType a request, 'reset' to start over, or 'quit'.")
    try:
        while True:
            try:
                text = input("\n> ").strip()
            except EOFError:
                break
            if text in ("quit", "exit"):
                break
            if text == "reset":
                rt.agent.reset()
                print("Started a new conversation.")
                continue
            reply = rt.agent.handle(text)
            for step in reply.steps:
                mark = "ok" if step.result.ok else ("cancelled" if step.result.cancelled else "failed")
                print(f"  [{step.tool}: {mark}]")
            print(reply.text)
    except KeyboardInterrupt:
        pass
    finally:
        rt.stop()


if __name__ == "__main__":
    main()
