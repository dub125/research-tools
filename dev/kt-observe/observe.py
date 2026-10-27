#!/usr/bin/env python3
"""Test-only observation logging for knowledge-track.

One script for every hook; the event comes from the hook's stdin JSON. It
appends to ~/.claude/knowledge-track-log/events.jsonl (override:
KT_OBSERVE_DIR) and copies transcripts at session end. It never prints and
always exits 0, so it cannot change or break a session.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(os.environ.get("KT_OBSERVE_DIR") or Path.home() / ".claude" / "knowledge-track-log")
KT_CALL = re.compile(r"(?:^|[\s;&|(])kt\s+([a-z]+)")
WRITES = {"set", "merge", "rm", "init"}
FLAG = re.compile(r"^\s*/kt-flag\b\s*(.*)", re.S)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(event):
    LOG.mkdir(parents=True, exist_ok=True)
    with open(LOG / "events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")


def state(session, name):
    d = LOG / "state" / session
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def kb_dir(command):
    m = re.search(r"KNOWLEDGE_TRACK_DIR=(\S+)", command)
    if m:
        return os.path.expanduser(m.group(1).strip("'\""))
    return os.environ.get("KNOWLEDGE_TRACK_DIR") or str(Path.home() / ".claude" / "knowledge")


def kb_head(kb):
    try:
        out = subprocess.run(["git", "-C", kb, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def base(h):
    return {"ts": now(), "event": None, "session": h.get("session_id"), "cwd": h.get("cwd")}


def on_prompt(h):
    prompt = h.get("prompt") or ""
    state(h["session_id"], "last_prompt").write_text(prompt)
    m = FLAG.match(prompt)
    if m:
        append(dict(base(h), event="flag", text=m.group(1).strip()))


def on_pre_bash(h):
    command = (h.get("tool_input") or {}).get("command") or ""
    if not KT_CALL.search(command):
        return
    head = kb_head(kb_dir(command))
    state(h["session_id"], "pre-%s" % h.get("tool_use_id")).write_text(head or "")


def on_post_bash(h, failed):
    command = (h.get("tool_input") or {}).get("command") or ""
    subs = KT_CALL.findall(command)
    if not subs:
        return
    kb = kb_dir(command)
    pre = state(h["session_id"], "pre-%s" % h.get("tool_use_id"))
    before = pre.read_text() or None if pre.exists() else None
    pre.unlink(missing_ok=True)
    last = state(h["session_id"], "last_prompt")
    response = h.get("error") if failed else h.get("tool_response")
    append(dict(
        base(h),
        event="kt",
        kind="write" if WRITES & set(subs) else "read",
        subcommands=subs,
        failed=failed,
        command=command,
        response=response,
        prompt=last.read_text() if last.exists() else None,
        kb=kb,
        kb_head_before=before,
        kb_head_after=kb_head(kb),
    ))


def on_skill(h):
    skill = (h.get("tool_input") or {}).get("skill") or ""
    if "knowledge-track" in skill:
        append(dict(base(h), event="skill_loaded", skill=skill))


def on_session_end(h):
    session = h.get("session_id") or "unknown"
    copied = None
    src = h.get("transcript_path")
    if src and os.path.exists(src):
        dst = LOG / "sessions" / ("%s.jsonl" % session)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied = str(dst)
    calls = 0
    events = LOG / "events.jsonl"
    if events.exists():
        with open(events) as f:
            calls = sum(1 for line in f if '"event": "kt"' in line and session in line)
    append(dict(base(h), event="session_end", reason=h.get("reason"), kt_calls=calls,
                transcript=copied))
    shutil.rmtree(LOG / "state" / session, ignore_errors=True)


def main():
    h = json.load(sys.stdin)
    h.setdefault("session_id", "unknown")
    name = h.get("hook_event_name")
    tool = h.get("tool_name")
    if name == "UserPromptSubmit":
        on_prompt(h)
    elif name == "PreToolUse" and tool == "Bash":
        on_pre_bash(h)
    elif name in ("PostToolUse", "PostToolUseFailure") and tool == "Bash":
        on_post_bash(h, failed=name == "PostToolUseFailure")
    elif name == "PostToolUse" and tool == "Skill":
        on_skill(h)
    elif name == "SessionEnd":
        on_session_end(h)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            append({"ts": now(), "event": "logger_error", "error": repr(e)})
        except Exception:
            pass
    sys.exit(0)
