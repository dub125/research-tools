#!/usr/bin/env python3
"""Register (or with --uninstall, remove) the observation hooks in
~/.claude/settings.json and the /kt-flag command in ~/.claude/commands."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLAUDE = Path.home() / ".claude"
SETTINGS = CLAUDE / "settings.json"
COMMAND = CLAUDE / "commands" / "kt-flag.md"
CMD = "python3 %s" % (HERE / "observe.py")
EVENTS = {
    "UserPromptSubmit": None,
    "PreToolUse": "Bash",
    "PostToolUse": "Bash|Skill",
    "PostToolUseFailure": "Bash",
    "SessionEnd": None,
}


def ours(group):
    return any(h.get("command") == CMD for h in group.get("hooks", []))


def main():
    uninstall = "--uninstall" in sys.argv
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    hooks = settings.setdefault("hooks", {})
    for event, matcher in EVENTS.items():
        groups = [g for g in hooks.get(event, []) if not ours(g)]
        if not uninstall:
            group = {"hooks": [{"type": "command", "command": CMD, "timeout": 10}]}
            if matcher:
                group["matcher"] = matcher
            groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    if COMMAND.is_symlink() or COMMAND.exists():
        COMMAND.unlink()
    if not uninstall:
        COMMAND.parent.mkdir(parents=True, exist_ok=True)
        COMMAND.symlink_to(HERE / "kt-flag.md")
    print("%s observation hooks and /kt-flag" % ("removed" if uninstall else "installed"))


if __name__ == "__main__":
    main()
