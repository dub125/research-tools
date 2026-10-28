#!/usr/bin/env python3
"""PreToolUse gate for lab-notebook.

Reads the hook input on stdin. For Bash commands that run a gated `nb` verb
(freeze, confirm, invalidate, config set) or that unset or clear CLAUDECODE,
it prints a permissionDecision of "ask" so the user approves the step. Every
other call passes through with no output.

Matching is a conservative text scan, not a shell parse: a false match only
costs an extra prompt. It guards against a well-meaning agent, not an
adversary (see SPEC.md, Authorship).
"""

import json
import os
import re
import subprocess
import sys

GATED = re.compile(r"(?:^|[\s;&|()`'\"/])nb\s+(freeze|confirm|invalidate|config\s+set)\b((?:\s+[^\s;&|()`]+)*)")
UNSETS = re.compile(r"(-u\s*CLAUDECODE\b|\bunset\b[^;&|\n]*\bCLAUDECODE\b|\bCLAUDECODE=|\benv\s+(?:-\S+\s+)*-i\b)")
WHY = {
    "freeze": "approves this experiment design; after freezing its spec and predictions cannot change",
    "confirm": "turns a pending proposal into an established part of the record",
    "invalidate": "withdraws a result from the record",
    "config set": "changes the notebook's thresholds or run gating",
}
NB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "nb")


def describe(nid, cwd):
    """One line about the node, best effort: title and what matters for approving it."""
    try:
        res = subprocess.run([sys.executable, NB, "show", nid, "--json"], cwd=cwd or None,
                             capture_output=True, text=True, timeout=3)
        n = json.loads(res.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""
    bits = ["%s %s (%s): %s" % (n["type"], n["id"], n.get("status", ""), n["title"])]
    if n.get("retro"):
        bits.append("retrospective: predictions written after the results" if n["type"] == "experiment"
                    else "rests on a retrospective experiment")
    for p in n.get("predictions", []):
        bits.append("predicts for %s: %s; rule: %s" % (p["hypothesis"], p["prediction"], p["decision_rule"]))
    for k in ("scope", "confidence"):
        if n.get(k):
            bits.append("%s: %s" % (k, n[k]))
    if n["type"] in ("conclusion", "lead", "decision") and n.get("author") == "claude":
        bits.append("proposed by Claude")
    return "\n".join(bits)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if "nb" not in cmd and "CLAUDECODE" not in cmd:
        return
    reasons = []
    for m in GATED.finditer(cmd):
        verb = " ".join(m.group(1).split())
        args = m.group(2).split()
        reasons.append("lab-notebook: `nb %s%s` %s." % (verb, " " + " ".join(args) if args else "", WHY[verb]))
        if verb != "config set" and args and not args[0].startswith("-"):
            info = describe(args[0], data.get("cwd"))
            if info:
                reasons.append(info)
    if UNSETS.search(cmd):
        reasons.append("lab-notebook: this command unsets or overrides CLAUDECODE, which nb uses to record "
                       "that Claude (not you) is the author.")
    if reasons:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "\n".join(reasons),
        }}))


if __name__ == "__main__":
    main()
