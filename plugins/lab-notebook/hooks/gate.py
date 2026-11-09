#!/usr/bin/env python3
"""PreToolUse gate for lab-notebook.

Reads the hook input on stdin. For Bash commands that run a gated `nb` verb
(freeze, confirm, invalidate, retract, verdict --replace, nothing-yet,
config set) or that unset or clear CLAUDECODE, it prints a
permissionDecision of "ask" so the user approves the step. A freeze that the
freeze gate would refuse gets "deny" with what blocks it instead. Every other
call passes through with no output.

Matching is a conservative text scan, not a shell parse: a false match only
costs an extra prompt. It guards against a well-meaning agent, not an
adversary (see SPEC.md, Authorship).
"""

import json
import os
import re
import subprocess
import sys

# Arguments stop at the end of the line: a newline starts another command, which is scanned on its own.
GATED = re.compile(r"(?:^|[\s;&|()`'\"/])nb[ \t]+(freeze|confirm|invalidate|retract|verdict|nothing-yet|config[ \t]+set)"
                   r"(?![\w-])((?:[ \t]+[^\s;&|()`]+)*)")
UNSETS = re.compile(r"(-u\s*CLAUDECODE\b|\bunset\b[^;&|\n]*\bCLAUDECODE\b|\bCLAUDECODE=|\benv\s+(?:-\S+\s+)*-i\b)")
WHY = {
    "freeze": "approves this experiment design; after freezing its spec and predictions cannot change",
    "confirm": "turns a pending proposal into an established part of the record",
    "invalidate": "withdraws a result from the record, and the verdicts judged on it",
    "retract": "removes a piece of evidence (a supports or contradicts link) from the record",
    "verdict": "overrides how a frozen decision rule was applied (replaces the current verdict)",
    "nothing-yet": "records that you reviewed these results and have nothing to conclude from them yet",
    "config set": "changes the notebook's thresholds, gates or run gating",
}
NB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "nb")


def nb_json(args, cwd):
    """Run nb with --json; the parsed output, or None."""
    try:
        res = subprocess.run([sys.executable, NB] + args + ["--json"], cwd=cwd or None,
                             capture_output=True, text=True, timeout=5)
        return json.loads(res.stdout) if res.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def describe(nid, cwd, verb):
    """Lines about the node, best effort: title and what matters for approving it."""
    n = nb_json(["show", nid], cwd)
    if not n:
        return ""
    bits = ["%s %s (%s): %s" % (n["type"], n["id"], n.get("status", ""), n["title"])]
    if n.get("retro"):
        bits.append("retrospective: predictions written after the results" if n["type"] == "experiment"
                    else "rests on a retrospective experiment")
    for p in n.get("predictions", []):
        bits.append("predicts for %s: %s; rule: %s" % (p["hypothesis"], p["prediction"], p["decision_rule"]))
    if verb == "freeze" and n["type"] in ("experiment", "exploration"):
        words = {"variant-of": "variant of", "uses": "uses"}
        parts = ["%s %s (%s)" % (words.get(b["rel"], b["rel"]), b["title"], b["id"]) for b in n.get("builds_on", [])]
        if n.get("fresh"):
            parts.append("fresh: builds on nothing in the notebook")
        bits.append("builds on: " + ("; ".join(parts) or "nothing stated, so nb will refuse to freeze it"))
    for k in ("scope", "confidence"):
        if n.get(k):
            bits.append("%s: %s" % (k, n[k]))
    if n["type"] in ("conclusion", "lead", "decision") and n.get("author") == "claude":
        bits.append("proposed by Claude")
    if verb == "confirm" and n["type"] in ("conclusion", "lead"):
        origin = n.get("origin")
        if origin == "user":
            bits.append("origin: drafted from your read. Your words: \"%s\"" % n.get("user_words", ""))
        elif origin == "claude":
            bits.append("origin: Claude's read, given because you asked")
        a = n.get("latest_audit")
        if a:
            bits.append("latest audit %s: %s%s. Findings: %s" % (a["id"], a["verdict"],
                                                               "" if a.get("current") else " (stale: the draft changed since)",
                                                               a.get("findings", "")))
        elif n.get("author") == "claude":
            bits.append("not audited")
    return "\n".join(bits)


def follow_on_lines(conf_id, also, cwd):
    n = nb_json(["show", conf_id], cwd) or {}
    offers = {f["id"]: f for f in n.get("follow_ons", [])}
    lines = []
    for term in also:
        f = next((v for k, v in offers.items() if k.startswith(term)), None)
        if f:
            lines.append("also: %s %s %s -> %s: %s" % (f["type"], f["id"], f["status"], f["to"], f["title"]))
        else:
            lines.append("also: %s (not a follow-on this node allows; nb will refuse it)" % term)
    return lines


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
    cmd = cmd.replace("\\\n", " ")  # a backslash-newline continues the same command
    cwd = data.get("cwd")
    reasons, deny = [], []
    for m in GATED.finditer(cmd):
        verb = " ".join(m.group(1).split())
        args = m.group(2).split()
        if verb == "verdict" and "--replace" not in args:
            continue  # a first verdict applies the frozen rule; only a replacement is gated
        reasons.append("lab-notebook: `nb %s%s` %s." % (verb, " " + " ".join(args) if args else "", WHY[verb]))
        if verb == "freeze":
            gate = nb_json(["gate"], cwd)
            if gate and gate.get("blocked"):
                deny.append("lab-notebook: the freeze gate is closed, so `nb freeze` would be refused. Close these "
                            "first (nb gate; review with nb brief, then a conclusion or nb nothing-yet; or nb verdict):")
                deny.extend("  %s %s: %s" % (b["id"], b["title"], b["why"]) for b in gate["blockers"])
        if verb in ("config set", "nothing-yet") or not args or args[0].startswith("-"):
            continue
        info = describe(args[0], cwd, verb)
        if info:
            reasons.append(info)
        if verb == "confirm":
            also = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--also"]
            reasons.extend(follow_on_lines(args[0], also, cwd))
    if UNSETS.search(cmd):
        reasons.append("lab-notebook: this command unsets or overrides CLAUDECODE, which nb uses to record "
                       "that Claude (not you) is the author.")
    if deny:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "\n".join(deny),
        }}))
    elif reasons:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "\n".join(reasons),
        }}))


if __name__ == "__main__":
    main()
