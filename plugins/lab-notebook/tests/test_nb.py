#!/usr/bin/env python3
"""Test suite for the `nb` CLI. Run: python3 plugins/lab-notebook/tests/test_nb.py

Behaviour is checked against plugins/lab-notebook/SPEC.md. Tests marked `# BUG:` failed against
bin/nb when written and are left failing on purpose.

Most classes share one repo built once (SnapCase): the notebook is snapshotted as a ref sha
("draft": goal, question, hypothesis, draft experiment with a prediction; "full": the experiment
frozen with one result) and every test resets refs/notebook/data to a snapshot.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NB = HERE.parent / "bin" / "nb"
sys.path.insert(0, str(HERE / "fixtures"))
import bioemu  # noqa: E402

TODAY = "2026-10-28"
REF = "refs/notebook/data"
ID_RE = r"%s-[0-9a-hjkmnp-tv-z]{4}$"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


def make_env(home):
    skip = ("CLAUDECODE", "NB_TODAY", "NB_REF", "NB_IN_HOOK", "NB_AUTHOR")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in skip}
    env.update({"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CEILING_DIRECTORIES": str(home), "NB_TODAY": TODAY})
    return env


def run_nb(env, cwd, args, author="user", today=None, input=None):
    e = dict(env)
    if author == "claude":
        e["CLAUDECODE"] = "1"
    if today:
        e["NB_TODAY"] = today
    res = subprocess.run([sys.executable, str(NB)] + list(args), env=e, cwd=str(cwd), capture_output=True,
                         text=True, input=input)
    return res.returncode, res.stdout, res.stderr


def git(env, repo, *args, input=None):
    res = subprocess.run(["git", "-C", str(repo)] + list(args), env=env, capture_output=True, text=True, input=input)
    if res.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), res.stderr))
    return res.stdout.strip()


def init_repo(env, path):
    Path(path).mkdir(parents=True, exist_ok=True)
    git(env, path, "init", "-q", "-b", "main")
    git(env, path, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "root")


class NbCase(unittest.TestCase):
    """A fresh temp git repo per test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="nb-test-")
        self.addCleanup(self._td.cleanup)
        self.td = Path(self._td.name)
        self.env = make_env(self.td)
        self.repo = self.td / "repo"
        init_repo(self.env, self.repo)

    # ---- running nb
    def nb(self, *args, author="user", cwd=None, today=None, input=None):
        return run_nb(self.env, cwd or self.repo, args, author, today, input)

    def ok(self, *args, **kw):
        rc, out, err = self.nb(*args, **kw)
        self.assertEqual(rc, 0, "nb %s failed\nstdout: %s\nstderr: %s" % (" ".join(args), out, err))
        return out.strip()

    def fails(self, *args, **kw):
        rc, out, err = self.nb(*args, **kw)
        self.assertNotEqual(rc, 0, "nb %s should fail\nstdout: %s" % (" ".join(args), out))
        return err

    def init(self):
        self.ok("init")

    def add(self, typ, title, *args, **kw):
        if typ in ("conclusion", "lead") and kw.get("author") == "claude" and "--origin" not in args:
            args += ("--origin", "claude")  # required for Claude's drafts; the origin tests pass it explicitly
        return self.ok("add", typ, title, *args, **kw).split()[-1]

    def audit(self, nid, verdict="sound", findings="none", **kw):
        """Record an audit of nid (Claude records it; not gated)."""
        kw.setdefault("author", "claude")
        return self.add("audit", "Audit", "--of", nid, "--verdict", verdict, "--findings", findings, **kw)

    def confirm(self, nid, *args, **kw):
        """Audit a pending Claude draft, then confirm it (audit_before_confirm is on by default)."""
        n = self.show(nid)
        if n["type"] in ("conclusion", "lead") and n["author"] == "claude":
            self.audit(nid)
        return self.ok("confirm", nid, *args, **kw)

    def show(self, nid, **kw):
        return json.loads(self.ok("show", nid, "--json", **kw))

    def query(self, *args):
        return [r["id"] for r in json.loads(self.ok("query", *args, "--json"))]

    def git(self, *args, repo=None, input=None):
        return git(self.env, repo or self.repo, *args, input=input)

    def head(self, repo=None):
        return self.git("rev-parse", REF, repo=repo)

    def commit_file(self, name="a.txt", text="x\n"):
        (self.repo / name).write_text(text)
        self.git("add", name)
        self.git(*GIT_ID, "commit", "-q", "-m", "add " + name)

    def predict(self, e, h, **kw):
        return self.ok("predict", e, h, "--prediction", "p", "--metric", "m", "--rule", "r", **kw)

    def concl(self, res, *extra, author="user", title="Concl", **kw):
        return self.add("conclusion", title, "--rationale", "why", "--scope", "here", "--alternatives", "none",
                        "--from", res, *extra, author=author, **kw)

    def new_exp(self, q_or_h, freeze=True, result=True, retro=False, title="E2"):
        """Another experiment testing hypothesis q_or_h. Returns (exp, result-or-None)."""
        e = self.add("experiment", title, "--spec", "S", "--exec", "command", *(["--retro"] if retro else []))
        self.predict(e, q_or_h)
        r = None
        if freeze:
            self.ok("freeze", e)
            if result:
                r = self.ok("result", e, "second result")
        return e, r

    # ---- hand-made commits
    def edit_ref(self, fn, repo=None):
        """Load the notebook tree, call fn(nodes, meta) to mutate dicts, write a new commit on the ref."""
        repo = repo or self.repo
        g = lambda *a, inp=None: git(self.env, repo, *a, input=inp)
        head = g("rev-parse", REF)
        nodes, meta = {}, {}
        for line in g("ls-tree", "-r", head).splitlines():
            m, path = line.split("\t")
            obj = json.loads(g("cat-file", "-p", m.split()[2]))
            if path == "meta.json":
                meta = obj
            else:
                nodes[obj["id"]] = obj
        fn(nodes, meta)
        entries = ""
        for nid, n in nodes.items():
            sha = g("hash-object", "-w", "--stdin", inp=json.dumps(n, indent=2) + "\n")
            entries += "100644 blob %s\t%s.json\n" % (sha, nid)
        nodes_tree = g("mktree", inp=entries)
        meta_sha = g("hash-object", "-w", "--stdin", inp=json.dumps(meta) + "\n")
        root = g("mktree", inp="100644 blob %s\tmeta.json\n040000 tree %s\tnodes\n" % (meta_sha, nodes_tree))
        commit = g(*GIT_ID, "commit-tree", root, "-p", head, "-m", "manual edit")
        g("update-ref", REF, commit, head)
        return commit

    @staticmethod
    def raw(nid, typ, title, status, links=(), **kw):
        n = {"id": nid, "type": typ, "title": title, "author": "user", "created": "2026-10-01", "updated": "2026-10-01",
             "links": [{"rel": r, "to": t} for r, t in links],
             "log": [{"date": "2026-10-01", "author": "user", "event": "add"}]}
        if status:
            n["status"] = status
        n.update(kw)
        return n

    def link_raw(self, nid, rel, to):
        self.edit_ref(lambda n, m: n[nid].setdefault("links", []).append({"rel": rel, "to": to}))

    # ---- lint helpers
    def lint(self, **kw):
        rc, out, err = self.nb("lint", "--json", **kw)
        return rc, json.loads(out)

    def lint_msgs(self, **kw):
        rc, items = self.lint(**kw)
        return rc, [(i["level"], i["id"], i["message"]) for i in items]

    def assertLint(self, level, nid, needle, **kw):
        rc, msgs = self.lint_msgs(**kw)
        hit = [m for m in msgs if m[0] == level and m[1] == nid and needle in m[2]]
        self.assertTrue(hit, "no %s on %s containing %r in %s" % (level, nid, needle, msgs))
        return rc

    def assertNoLint(self, nid, needle, **kw):
        _, msgs = self.lint_msgs(**kw)
        hit = [m for m in msgs if m[1] == nid and needle in m[2]]
        self.assertFalse(hit, hit)

    # ---- remotes
    def setup_remote(self):
        self.bare = self.td / "origin.git"
        self.bare.mkdir()
        git(self.env, self.bare, "init", "-q", "--bare", "-b", "main")
        self.git("remote", "add", "origin", str(self.bare))
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")

    def clone(self, name="clone"):
        path = self.td / name
        subprocess.run(["git", "clone", "-q", str(self.bare), str(path)], env=self.env, check=True, capture_output=True)
        return path

    def nb_in(self, repo, *args, **kw):
        return run_nb(self.env, repo, args, kw.get("author", "user"), kw.get("today"))

    def ok_in(self, repo, *args, **kw):
        rc, out, err = self.nb_in(repo, *args, **kw)
        self.assertEqual(rc, 0, "nb %s in %s failed\nstdout: %s\nstderr: %s" % (" ".join(args), repo, out, err))
        return out.strip()


class SnapCase(NbCase):
    """One repo per class; tests start from a snapshot of the ref instead of replaying a chain.

    self.d holds the ids: g (active goal), q (open question), h (hypothesis), e (experiment) and, in
    the "full" snapshot, r (valid result). reset("draft") gives the experiment as a draft with its
    prediction (no r); the default is "full": the experiment frozen with result r.
    """

    def setUp(self):
        cls = type(self)
        if "_shared" not in cls.__dict__:
            cls._shared = None
        if cls._shared is None:
            cls._tdobj = tempfile.TemporaryDirectory(prefix="nb-test-")
            self.td = Path(cls._tdobj.name)
            self.env = make_env(self.td)
            self.repo = self.td / "repo"
            init_repo(self.env, self.repo)
            self.init()
            d = {"g": self.add("goal", "Goal")}
            d["q"] = self.add("question", "Question?", "--link", "refines:" + d["g"])
            d["h"] = self.add("hypothesis", "Hyp", "--prediction", "P", "--link", "addresses:" + d["q"])
            d["e"] = self.add("experiment", "Exp", "--spec", "S", "--exec", "command")
            self.predict(d["e"], d["h"])
            draft = self.head()
            self.ok("freeze", d["e"])
            d["r"] = self.ok("result", d["e"], "summary of facts")
            cls._shared = dict(d=d, draft=draft, full=self.head(), base=self.git("rev-parse", "HEAD"))
        else:
            self.td = Path(cls._tdobj.name)
            self.env = make_env(self.td)
            self.repo = self.td / "repo"
        self.d = cls._shared["d"]
        self.reset("full")

    @classmethod
    def tearDownClass(cls):
        if "_tdobj" in cls.__dict__:
            cls._tdobj.cleanup()

    def reset(self, which="full"):
        sh = type(self)._shared
        self.git("update-ref", REF, sh[which])
        self.git("reset", "-q", "--hard", sh["base"])
        self.git("clean", "-fdq")


# ================================================================ 1 init ===

class TestInit(NbCase):
    def test_creates_ref_and_is_idempotent(self):
        self.assertIn("created", self.ok("init"))
        h = self.head()
        self.assertRegex(h, r"^[0-9a-f]{40}$")
        self.assertIn("already exists", self.ok("init"))
        self.assertEqual(self.head(), h)
        self.assertFalse((self.repo / ".git" / "hooks" / "pre-push").exists())  # no origin, no hook

    def test_commands_without_init_fail(self):
        self.assertIn("nb init", self.fails("query"))

    def test_clone_adopts_origin_notebook(self):
        self.setup_remote()
        self.init()
        g = self.add("goal", "Goal")
        self.ok("sync")
        other = self.clone()
        self.assertIn("fetched from origin", self.ok_in(other, "init"))
        rows = json.loads(self.ok_in(other, "query", "--all", "--json"))
        self.assertEqual([r["id"] for r in rows], [g])
        self.assertEqual(len(git(self.env, other, "rev-list", "--max-parents=0", REF).split()), 1)
        self.assertEqual(git(self.env, other, "rev-parse", REF), self.head())

    def test_refspec_and_hook_added_once(self):
        self.setup_remote()
        self.init()
        self.init()
        spec = "+%s:refs/notebook/origin" % REF
        self.assertEqual(self.git("config", "--get-all", "remote.origin.fetch").split().count(spec), 1)
        path = self.repo / ".git" / "hooks" / "pre-push"
        text = path.read_text()
        self.assertEqual(text.count("# >>> nb sync >>>"), 1)
        self.assertEqual(text.count("# <<< nb sync <<<"), 1)
        self.assertTrue(os.access(path, os.X_OK))

    def test_existing_pre_push_hook_preserved(self):
        self.setup_remote()
        hooks = self.repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        (hooks / "pre-push").write_text("#!/bin/sh\necho foam-check\n")
        self.init()
        self.init()
        text = (hooks / "pre-push").read_text()
        self.assertIn("echo foam-check", text)
        self.assertEqual(text.count("# >>> nb sync >>>"), 1)


# ================================================================= 2 ids ===

class TestIds(SnapCase):
    def test_id_format_per_type(self):
        d = self.d
        c = self.concl(d["r"])
        lead = self.add("lead", "Lead", "--rationale", "r", "--from", d["r"])
        dec = self.add("decision", "Dec", "--rationale", "r")
        aud = self.add("audit", "Aud", "--of", c, "--verdict", "sound", "--findings", "f")
        xpl = self.add("exploration", "Xpl", "--link", "investigates:" + d["q"])
        for nid, prefix in [(d["g"], "goal"), (d["q"], "q"), (d["h"], "hyp"), (d["e"], "exp"), (d["r"], "res"),
                            (c, "con"), (lead, "lead"), (dec, "dec"), (aud, "aud"), (xpl, "xpl")]:
            self.assertRegex(nid, ID_RE % prefix)

    def test_prefix_lookup(self):
        d = self.d
        self.assertEqual(self.show(d["g"][:6])["id"], d["g"])
        self.ok("context", d["g"][:6])
        self.ok("path", d["e"][:6])
        q2 = self.add("question", "Another?", "--link", "refines:" + d["g"])
        err = self.fails("show", "q-")
        self.assertIn("ambiguous", err)
        self.assertIn(d["q"], err)
        self.assertIn(q2, err)
        self.assertIn("no node", self.fails("show", "goal-zzzz"))


# ======================================================= 3 authorship ===

class TestAuthorship(SnapCase):
    def test_user_established_claude_pending(self):
        d = self.d
        for author, want in (("user", ("active", "supported", "active", "active")),
                             ("claude", ("pending",) * 4)):
            ids = [self.add("goal", "G", author=author), self.concl(d["r"], author=author),
                   self.add("lead", "L", "--rationale", "r", "--from", d["r"], author=author),
                   self.add("decision", "D", "--rationale", "r", author=author)]
            for nid, st in zip(ids, want):
                n = self.show(nid)
                self.assertEqual((n["status"], n["author"]), (st, author), nid)

    def test_claude_question_and_hypothesis_not_pending(self):
        q = self.add("question", "Q?", "--link", "refines:" + self.d["g"], author="claude")
        h = self.add("hypothesis", "H", "--prediction", "p", "--link", "addresses:" + q, author="claude")
        self.assertEqual((self.show(q)["status"], self.show(q)["author"]), ("open", "claude"))
        self.assertEqual(self.show(h)["status"], "open")
        self.assertEqual(self.show(h)["log"][0]["author"], "claude")

    def test_nothing_sets_author(self):
        self.fails("add", "goal", "G", "--author", "claude")
        self.fails("add", "goal", "G", "--author", "user", author="claude")
        self.env["NB_AUTHOR"] = "claude"
        self.assertEqual(self.show(self.add("goal", "G"))["author"], "user")


# ================================================== 4 add validation ===

class TestAddValidation(SnapCase):
    def test_required_links(self):
        d = self.d
        h = self.head()
        self.assertIn("refines", self.fails("add", "question", "Q?"))
        self.assertIn("addresses", self.fails("add", "hypothesis", "H", "--prediction", "p"))
        self.assertIn("investigates", self.fails("add", "exploration", "X"))
        self.fails("add", "conclusion", "C", "--rationale", "r", "--scope", "s", "--alternatives", "a")
        self.assertIn("suggested-by", self.fails("add", "lead", "L", "--rationale", "r"))
        self.assertIn("audits", self.fails("add", "audit", "A", "--verdict", "sound", "--findings", "f"))
        self.assertEqual(self.head(), h)  # refusals write nothing

    def test_required_fields(self):
        d = self.d
        self.assertIn("prediction", self.fails("add", "hypothesis", "H", "--link", "addresses:" + d["q"]))
        base = {"--rationale": "r", "--scope": "s", "--alternatives": "a"}
        for drop in base:
            args = [x for k, v in base.items() if k != drop for x in (k, v)]
            self.fails("add", "conclusion", "C", *args, "--from", d["r"])

    def test_stray_type_flags_refused(self):
        d = self.d
        self.assertIn("--spec", self.fails("add", "goal", "G2", "--spec", "x"))
        self.fails("add", "question", "Q?", "--link", "refines:" + d["g"], "--prediction", "p")
        self.fails("add", "hypothesis", "H", "--prediction", "p", "--link", "addresses:" + d["q"], "--rationale", "r")
        self.fails("add", "exploration", "X", "--link", "investigates:" + d["q"], "--retro")
        self.fails("add", "decision", "D", "--rationale", "r", "--verdict", "sound")

    def test_bad_links(self):
        d = self.d
        self.assertIn("unknown relation", self.fails("add", "question", "Q?", "--link", "bogus:" + d["g"]))
        self.fails("add", "question", "Q?", "--link", d["g"])  # no REL:
        self.fails("add", "hypothesis", "H", "--prediction", "p", "--link", "refines:" + d["g"],
                   "--link", "addresses:" + d["q"])
        self.fails("add", "hypothesis", "H", "--prediction", "p", "--link", "addresses:" + d["g"])
        self.fails("add", "question", "Q?", "--link", "refines:" + d["h"])
        self.fails("add", "question", "Q?", "--link", "refines:" + d["g"], "--link", "refines:" + d["g"])

    def test_produces_and_tests_via_link_refused(self):
        d = self.d
        self.assertIn("nb predict", self.fails("add", "experiment", "E", "--link", "tests:" + d["h"]))
        self.assertIn("nb result", self.fails("add", "exploration", "X", "--link", "investigates:" + d["q"],
                                              "--link", "produces:" + d["r"]))

    def test_stdin_body_and_enums(self):
        g = self.add("goal", "G2", "--body", "-", input="line one\nline two\n")
        self.assertEqual(self.show(g)["body"], "line one\nline two")
        self.fails("add", "experiment", "E", "--exec", "magic")


# ================================================ 5 predict and freeze ===

class TestPredictFreeze(SnapCase):
    def setUp(self):
        super().setUp()
        self.reset("draft")

    def test_predict_creates_link_and_rejects_duplicates(self):
        d = self.d
        e = self.show(d["e"])
        self.assertIn({"rel": "tests", "to": d["h"]}, e["links"])
        self.assertEqual(e["predictions"], [{"hypothesis": d["h"], "prediction": "p", "metric": "m", "decision_rule": "r"}])
        self.assertIn("already", self.fails("predict", d["e"], d["h"], "--prediction", "p", "--metric", "m", "--rule", "r"))

    def test_predict_only_on_draft_experiment(self):
        d = self.d
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"])
        x = self.add("exploration", "X", "--link", "investigates:" + d["q"])
        self.fails("predict", x, h2, "--prediction", "p", "--metric", "m", "--rule", "r")
        self.ok("freeze", d["e"])
        self.assertIn("draft", self.fails("predict", d["e"], h2, "--prediction", "p", "--metric", "m", "--rule", "r"))

    def test_freeze_requirements(self):
        d = self.d
        e2 = self.add("experiment", "E2")
        self.predict(e2, d["h"])
        err = self.fails("freeze", e2)
        self.assertIn("spec", err)
        self.assertIn("execution", err)
        e3 = self.add("experiment", "E3", "--spec", "s", "--exec", "analysis")
        self.assertIn("prediction", self.fails("freeze", e3))
        x = self.add("exploration", "X", "--link", "investigates:" + d["q"])
        self.fails("freeze", x)

    def test_freeze_needs_path_to_active_goal(self):
        d = self.d
        # pending goal does not count
        g2 = self.add("goal", "G2", author="claude")
        q2 = self.add("question", "Q2?", "--link", "refines:" + g2)
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + q2)
        e2 = self.add("experiment", "E2", "--spec", "s", "--exec", "command")
        self.predict(e2, h2)
        self.assertIn("active goal", self.fails("freeze", e2))
        self.ok("confirm", g2)
        self.ok("freeze", e2)
        # superseded goal does not count
        self.add("goal", "G3", "--link", "supersedes:" + d["g"])
        self.assertEqual(self.show(d["g"])["status"], "superseded")
        self.assertIn("active goal", self.fails("freeze", d["e"]))
        g3 = self.query("--type", "goal", "--status", "active")
        self.assertEqual(len(g3), 2)

    def test_freeze_sets_hash_and_frozen_at(self):
        d = self.d
        before = self.head()
        self.ok("freeze", d["e"])
        e = self.show(d["e"])
        self.assertEqual((e["status"], e["frozen_at"]), ("frozen", before))
        keys = {"title": "Exp", "spec": "S", "execution": "command",
                "predictions": [{"hypothesis": d["h"], "prediction": "p", "metric": "m", "decision_rule": "r"}]}
        want = hashlib.sha256(json.dumps(keys, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(e["spec_hash"], want)
        self.fails("freeze", d["e"])  # only from draft

    def test_draft_editable_frozen_immutable(self):
        d = self.d
        self.ok("set", d["e"], "spec", "better")
        self.ok("set", d["e"], "title", "Better")
        self.ok("freeze", d["e"])
        for f in ("title", "spec", "execution", "predictions"):
            self.fails("set", d["e"], f, "New")
        self.ok("set", d["e"], "body", "notes")
        self.ok("set", d["e"], "refs", "foam-1", "--append")
        self.ok("set", d["e"], "tags", "t1", "--append")
        e = self.show(d["e"])
        self.assertEqual((e["body"], e["refs"], e["tags"]), ("notes", ["foam-1"], ["t1"]))
        self.assertEqual(self.lint_msgs()[0], 0)

    def test_deviate(self):
        d = self.d
        self.assertIn("frozen", self.fails("deviate", d["e"], "text"))
        self.ok("freeze", d["e"])
        h = self.show(d["e"])["spec_hash"]
        self.ok("deviate", d["e"], "ran 3 seeds not 5", author="claude")
        dev = self.show(d["e"])["deviations"]
        self.assertEqual([(x["text"], x["author"], x["date"]) for x in dev], [("ran 3 seeds not 5", "claude", TODAY)])
        self.ok("result", d["e"], "res", "--verdict", d["h"], "supported", "m 1 > 0")
        self.assertEqual(self.show(d["e"])["status"], "done")
        self.ok("deviate", d["e"], "later note")
        e = self.show(d["e"])
        self.assertEqual(len(e["deviations"]), 2)
        self.assertEqual(e["spec_hash"], h)
        self.assertEqual(self.lint_msgs()[0], 0)

    def test_exploration_freezes_without_predictions(self):
        x = self.add("exploration", "X", "--spec", "look", "--exec", "analysis", "--link", "investigates:" + self.d["q"])
        self.ok("freeze", x)
        self.assertEqual(self.show(x)["status"], "frozen")

    def test_retro_propagates(self):
        d = self.d
        e, r = self.new_exp(d["h"], retro=True)
        c = self.concl(r)
        self.assertTrue(self.show(e)["retro"])
        self.assertTrue(self.show(e)["retrospective"])
        self.assertTrue(self.show(r)["retro"])
        self.assertTrue(self.show(c)["retro"])
        self.assertIn("retro", self.ok("show", c))
        self.assertIn("retro", self.ok("prime"))
        self.assertFalse(self.show(d["e"])["retro"])
        self.fails("set", e, "retrospective", "false")


# ===================================================== 6 results ===

class TestResults(SnapCase):
    def test_only_on_frozen(self):
        d = self.d
        self.reset("draft")
        self.assertIn("frozen", self.fails("result", d["e"], "s"))
        self.ok("freeze", d["e"])
        r = self.ok("result", d["e"], "s")
        self.assertIn({"rel": "produces", "to": r}, self.show(d["e"])["links"])
        self.ok("verdict", r, d["h"], "refuted", "--basis", "m 0.1 < 0.5")
        self.assertIn("done", self.fails("result", d["e"], "again"))

    def test_provenance_commit_dirty_cwd(self):
        d = self.d
        self.commit_file()
        r = self.ok("result", d["e"], "clean")
        p = self.show(r)["provenance"]
        self.assertEqual(p["commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(len(p["commit"]), 40)
        self.assertIs(p["dirty"], False)
        self.assertNotIn("cwd", p)
        (self.repo / "scratch.txt").write_text("untracked")
        self.assertIs(self.show(self.ok("result", d["e"], "untracked"))["provenance"]["dirty"], False)
        (self.repo / "a.txt").write_text("changed\n")
        sub = self.repo / "runs" / "a"
        sub.mkdir(parents=True)
        p = self.show(self.ok("result", d["e"], "dirty", cwd=sub))["provenance"]
        self.assertIs(p["dirty"], True)
        self.assertEqual(p["cwd"], "runs/a")

    def test_commit_flag(self):
        d = self.d
        p = self.show(self.ok("result", d["e"], "s", "--commit", "deadbeef1234"))["provenance"]
        self.assertEqual(p["commit"], "deadbeef1234")
        self.assertNotIn("dirty", p)
        p = self.show(self.ok("result", d["e"], "s", "--commit", "HEAD"))["provenance"]
        self.assertEqual(p["commit"], self.git("rev-parse", "HEAD"))

    def test_run_dir_ext_ids_artifacts_tags(self):
        r = self.ok("result", self.d["e"], "s", "--run-dir", "runs/1", "--ext-id", "wb1", "--ext-id", "wb2",
                    "--artifact", "out/a.npy", "--artifact", "https://x/y", "--tag", "a", "--tag", "b")
        n = self.show(r)
        self.assertEqual(n["provenance"]["run_dir"], "runs/1")
        self.assertEqual(n["provenance"]["external_ids"], ["wb1", "wb2"])
        self.assertEqual(n["provenance"]["artifacts"], ["out/a.npy", "https://x/y"])
        self.assertEqual(n["tags"], ["a", "b"])

    def test_metrics(self):
        d = self.d
        m = {"chignolin": {"brier": -0.28, "n": 108}, "villin": {"brier": -0.3}}
        (self.repo / "metrics.json").write_text(json.dumps(m))
        n = self.show(self.ok("result", d["e"], "s", "--metrics", "metrics.json"))
        self.assertEqual(n["metrics"], m)
        self.assertIn("metrics.json", n["provenance"]["artifacts"])
        sub = self.repo / "sub"
        sub.mkdir()
        (sub / "m.json").write_text('{"a": 1}')
        n = self.show(self.ok("result", d["e"], "s", "--metrics", "m.json", cwd=sub))
        self.assertIn("sub/m.json", n["provenance"]["artifacts"])

    def test_non_object_metrics_refused(self):
        d = self.d
        (self.repo / "m.json").write_text("[1, 2]")
        self.assertIn("object", self.fails("result", d["e"], "s", "--metrics", "m.json"))
        (self.repo / "bad.json").write_text("{nope")
        self.fails("result", d["e"], "s", "--metrics", "bad.json")
        self.fails("result", d["e"], "s", "--metrics", "missing.json")

    def test_link_at_creation(self):
        d = self.d
        r = self.ok("result", d["e"], "s", "--link", "supports:" + d["h"])
        r2 = self.ok("result", d["e"], "s2", "--link", "contradicts:" + d["h"])
        self.assertIn({"rel": "supports", "to": d["h"]}, self.show(r)["links"])
        self.assertIn({"rel": "contradicts", "to": d["h"]}, self.show(r2)["links"])
        h = self.head()
        for rel in ("answers", "uses", "produces"):
            self.fails("result", d["e"], "s", "--link", "%s:%s" % (rel, d["h"]))
        self.assertEqual(self.head(), h)

    def test_result_later_gains_only_supports_contradicts(self):
        d = self.d
        self.ok("link", d["r"], "supports", d["h"])
        self.ok("link", d["r"], "contradicts", d["h"])
        self.fails("link", d["r"], "answers", d["q"])
        self.fails("link", d["r"], "uses", d["h"])

    def test_result_fields_immutable_except_tags(self):
        d = self.d
        for f in ("summary", "title", "body", "refs", "provenance", "metrics"):
            self.fails("set", d["r"], f, "x")
        self.ok("set", d["r"], "tags", "keep", "--append")
        self.assertEqual(self.show(d["r"])["tags"], ["keep"])

    def test_exploration_result(self):
        x = self.add("exploration", "X", "--spec", "look", "--exec", "analysis", "--link", "investigates:" + self.d["q"])
        self.ok("freeze", x)
        r = self.ok("result", x, "found something")
        self.assertIn({"rel": "produces", "to": r}, self.show(x)["links"])


# ================================================== 7 conclusions ===

class TestConclusions(SnapCase):
    def basis_args(self, res):
        return ["--rationale", "r", "--scope", "s", "--alternatives", "a", "--from", res]

    def test_exploration_only_basis_refused(self):
        d = self.d
        x = self.add("exploration", "X", "--spec", "look", "--exec", "analysis", "--link", "investigates:" + d["q"])
        self.ok("freeze", x)
        xr = self.ok("result", x, "saw things")
        self.assertIn("exploration", self.fails("add", "conclusion", "C", *self.basis_args(xr)))
        # as context next to an experiment result it is fine
        self.add("conclusion", "C2", *self.basis_args(d["r"]), "--from", xr)

    def test_basis_must_be_valid_experiment_result(self):
        d = self.d
        self.fails("add", "conclusion", "C", *self.basis_args(d["h"]))
        self.ok("invalidate", d["r"], "--reason", "bug")
        self.fails("add", "conclusion", "C", *self.basis_args(d["r"]))

    def test_user_conclusion_confirmed_at(self):
        before = self.head()
        c = self.concl(self.d["r"], "--confidence", "high")
        n = self.show(c)
        self.assertEqual((n["status"], n["confirmed_at"], n["confidence"]), ("supported", before, "high"))
        self.fails("add", "conclusion", "C", *self.basis_args(self.d["r"]), "--confidence", "certain")

    def test_claude_conclusion_confirm(self):
        c = self.concl(self.d["r"], author="claude")
        n = self.show(c)
        self.assertEqual(n["status"], "pending")
        self.assertNotIn("confirmed_at", n)
        self.audit(c)
        before = self.head()
        self.ok("confirm", c)
        n = self.show(c)
        self.assertEqual((n["status"], n["confirmed_at"]), ("supported", before))
        self.assertEqual((n["log"][-1]["event"], n["log"][-1]["author"]), ("confirm", "user"))
        self.assertIn("not pending", self.fails("confirm", c))
        self.fails("confirm", self.d["q"])

    def test_supersedes_user_authored_immediate(self):
        d = self.d
        c1 = self.concl(d["r"])
        c2 = self.concl(d["r"], "--link", "supersedes:" + c1, title="Newer")
        self.assertEqual(self.show(c1)["status"], "superseded")
        self.assertEqual(self.show(c2)["status"], "supported")
        ev = self.show(c1)["log"][-1]
        self.assertEqual((ev["event"], ev["to"]), ("superseded", "superseded"))

    def test_supersedes_claude_authored_on_confirm(self):
        d = self.d
        c1 = self.concl(d["r"])
        c2 = self.concl(d["r"], "--link", "supersedes:" + c1, author="claude", title="Newer")
        self.assertEqual(self.show(c1)["status"], "supported")
        self.confirm(c2)
        self.assertEqual(self.show(c1)["status"], "superseded")

    def test_hypothesis_supersession_immediate_even_for_claude(self):
        d = self.d
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"],
                      "--link", "supersedes:" + d["h"], author="claude")
        self.assertEqual(self.show(d["h"])["status"], "superseded")
        self.assertEqual(self.show(h2)["status"], "open")
        self.fails("add", "conclusion", "C", *self.basis_args(d["r"]), "--link", "supersedes:" + d["h"])  # type mismatch

    def test_basis_links_frozen_once_established(self):
        d = self.d
        r2 = self.ok("result", d["e"], "second")
        c1, c2 = self.concl(d["r"]), self.concl(d["r"], title="C2")
        self.assertIn("basis", self.fails("link", c1, "derived-from", r2))
        self.fails("link", c1, "supersedes", c2)
        for f in ("rationale", "scope", "alternatives", "title", "confidence"):
            self.fails("set", c1, f, "x")
        self.ok("set", c1, "body", "ok")
        # still allowed while pending
        c3 = self.concl(d["r"], author="claude", title="C3")
        self.ok("link", c3, "derived-from", r2)

    def test_reject(self):
        d = self.d
        c = self.concl(d["r"], author="claude")
        lead = self.add("lead", "L", "--rationale", "r", "--from", d["r"], author="claude")
        g = self.add("goal", "G2", author="claude")
        self.fails("reject", c)  # --reason required
        self.ok("reject", c, "--reason", "overclaims")
        self.ok("reject", lead, "--reason", "no")
        self.ok("reject", g, "--reason", "no")
        n = self.show(c)
        self.assertEqual((n["status"], n["log"][-1]["reason"]), ("rejected", "overclaims"))
        self.assertEqual(self.show(lead)["status"], "dropped")
        self.assertEqual(self.show(g)["status"], "rejected")
        self.fails("reject", d["g"], "--reason", "x")  # not pending


# =================================================== 8 status rules ===

class TestStatusRules(SnapCase):
    def test_hypothesis_status_not_set_by_hand(self):
        d = self.d
        self.assertIn("verdict", self.fails("status", d["h"], "supported"))
        c = self.concl(d["r"], "--link", "supports:" + d["h"])  # a supported conclusion is not enough now
        self.fails("status", d["h"], "supported")
        self.fails("status", d["h"], "refuted", "--reason", "x")
        self.assertIn("reason", self.fails("status", d["h"], "superseded"))
        self.ok("status", d["h"], "superseded", "--reason", "folded into a broader hypothesis")
        self.assertEqual(self.show(d["h"])["status"], "superseded")
        self.assertTrue(c)

    def test_question_answered_and_settled(self):
        d = self.d
        self.assertIn("answers", self.fails("status", d["q"], "answered"))
        self.assertIn("decision", self.fails("status", d["q"], "settled"))
        c = self.concl(d["r"], "--link", "answers:" + d["q"], author="claude")
        dec = self.add("decision", "D", "--rationale", "r", "--link", "affects:" + d["q"], author="claude")
        self.fails("status", d["q"], "answered")
        self.fails("status", d["q"], "settled")
        self.ok("confirm", dec)
        self.fails("status", d["q"], "answered")  # a decision does not answer
        self.ok("status", d["q"], "settled")
        self.ok("status", d["q"], "open", "--reason", "revisit")
        self.confirm(c)
        self.ok("status", d["q"], "answered")
        self.assertIn("--reason", self.fails("status", d["q"], "open"))

    def test_experiment_done_only_by_verdicts(self):
        d = self.d
        self.reset("draft")
        self.ok("freeze", d["e"])
        self.assertIn("verdict", self.fails("status", d["e"], "done"))
        self.ok("result", d["e"], "s")
        self.fails("status", d["e"], "done")
        x = self.add("exploration", "X", "--spec", "look", "--exec", "analysis", "--link", "investigates:" + d["q"])
        self.ok("freeze", x)
        self.assertIn("result", self.fails("status", x, "done"))
        self.ok("result", x, "s")
        self.ok("status", x, "done")

    def test_lead_followed(self):
        d = self.d
        lead = self.add("lead", "L", "--rationale", "r", "--from", d["r"])
        self.fails("status", lead, "followed")
        q2 = self.add("question", "Q2?", "--link", "refines:" + d["g"])
        self.ok("link", lead, "raises", q2)
        self.ok("status", lead, "followed")
        lead2 = self.add("lead", "L2", "--rationale", "r", "--from", d["r"])
        e2 = self.add("experiment", "E2")
        self.ok("link", lead2, "spawns", e2)
        self.ok("status", lead2, "followed")
        lead3 = self.add("lead", "L3", "--rationale", "r", "--from", d["r"], author="claude")
        self.ok("link", lead3, "raises", q2)
        self.fails("status", lead3, "followed")  # pending

    def test_reasons_required(self):
        d = self.d
        for typ_id, st in ((d["q"], "abandoned"), (d["q"], "parked"), (d["e"], "abandoned")):
            self.assertIn("--reason", self.fails("status", typ_id, st))
        lead = self.add("lead", "L", "--rationale", "r", "--from", d["r"])
        self.assertIn("--reason", self.fails("status", lead, "dropped"))
        c = self.concl(d["r"])
        self.assertIn("--reason", self.fails("status", c, "refuted"))
        self.ok("status", d["q"], "parked", "--reason", "later")
        self.assertIn("--reason", self.fails("status", d["q"], "open"))
        self.ok("status", d["q"], "open", "--reason", "now")
        self.ok("status", d["e"], "abandoned", "--reason", "dead end")
        self.ok("status", lead, "dropped", "--reason", "meh")
        self.ok("status", c, "refuted", "--reason", "new data")
        self.assertEqual(self.show(d["e"])["log"][-1]["reason"], "dead end")

    def test_disallowed_moves(self):
        d = self.d
        self.reset("draft")
        self.assertIn("nb freeze", self.fails("status", d["e"], "frozen"))
        self.fails("status", d["e"], "done")
        g2 = self.add("goal", "G2", author="claude")
        self.assertIn("confirm", self.fails("status", g2, "active"))
        self.fails("status", g2, "rejected", "--reason", "x")
        for s in ("superseded", "rejected", "pending"):
            self.fails("status", d["g"], s, "--reason", "x")
        self.reset("full")
        self.assertIn("invalidate", self.fails("status", d["r"], "invalidated", "--reason", "x"))
        self.assertIn("no status", self.fails("status", d["q"], "frozen"))

    def test_status_change_logged(self):
        self.ok("status", self.d["q"], "parked", "--reason", "r", author="claude")
        ev = self.show(self.d["q"])["log"][-1]
        self.assertEqual((ev["event"], ev["from"], ev["to"], ev["author"], ev["reason"]),
                         ("status", "open", "parked", "claude", "r"))


# ================================================ 9 links/unlink/set ===

class TestLinksSet(SnapCase):
    def test_later_links(self):
        d = self.d
        dec = self.add("decision", "D", "--rationale", "r")
        self.ok("link", dec, "affects", d["e"])
        self.ok("link", dec, "affects", d["q"], author="claude")
        self.assertEqual(len(self.show(dec)["links"]), 2)
        self.assertEqual(self.show(dec)["log"][-1]["author"], "claude")
        self.assertIn("already", self.fails("link", dec, "affects", d["q"]))
        self.fails("link", dec, "affects", d["r"])  # type mismatch
        lead = self.add("lead", "L", "--rationale", "r", "--from", d["r"])
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"])
        self.ok("link", lead, "spawns", h2)
        self.assertIn({"rel": "spawns", "to": h2}, self.show(lead)["links"])

    def test_link_guards(self):
        d = self.d
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"])
        self.assertIn("nb predict", self.fails("link", d["e"], "tests", h2))
        self.assertIn("nb result", self.fails("link", d["e"], "produces", d["r"]))
        q2 = self.add("question", "Q2?", "--link", "refines:" + d["q"])
        self.fails("link", d["q"], "refines", d["q"])
        self.assertIn("cycle", self.fails("link", d["q"], "refines", q2))

    def test_audit_immutable(self):
        d = self.d
        c = self.concl(d["r"])
        c2 = self.concl(d["r"], title="C2")
        a = self.add("audit", "A", "--of", c, "--verdict", "sound", "--findings", "fine")
        self.assertIn("immutable", self.fails("link", a, "audits", c2))
        self.fails("set", a, "findings", "x")
        self.fails("set", a, "body", "x")
        self.fails("unlink", a, "audits", c)
        self.fails("status", a, "open")
        self.ok("set", a, "tags", "t", "--append")
        n = self.show(a)
        self.assertNotIn("status", n)
        self.assertEqual((n["tags"], n["verdict"]), (["t"], "sound"))

    def test_unlink_rules(self):
        d = self.d
        q0 = self.add("question", "Parent?", "--link", "refines:" + d["g"])
        q2 = self.add("question", "Q2?", "--link", "refines:" + d["g"], "--link", "refines:" + q0)
        self.assertIn("no", self.fails("unlink", q2, "answers", d["g"]))
        self.ok("unlink", q2, "refines", q0)
        self.assertEqual(self.show(q2)["links"], [{"rel": "refines", "to": d["g"]}])
        self.fails("unlink", q2, "refines", d["g"])  # the only required link
        self.fails("unlink", d["h"], "addresses", d["q"])
        q3 = self.add("question", "Q3?", "--link", "refines:" + d["g"], "--link", "refines:" + q0)
        self.ok("status", q3, "parked", "--reason", "r")
        self.fails("unlink", q3, "refines", q0)  # not initial status any more
        self.fails("unlink", d["e"], "tests", d["h"])  # frozen
        self.fails("unlink", d["e"], "produces", d["r"])
        dec = self.add("decision", "D", "--rationale", "r", "--link", "affects:" + d["q"])
        self.fails("unlink", dec, "affects", d["q"])  # active
        dec2 = self.add("decision", "D2", "--rationale", "r", "--link", "affects:" + d["q"], author="claude")
        self.ok("unlink", dec2, "affects", d["q"])  # pending

    def test_unlink_tests_removes_prediction(self):
        d = self.d
        self.reset("draft")
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"])
        self.predict(d["e"], h2)
        self.assertEqual(len(self.show(d["e"])["predictions"]), 2)
        self.ok("unlink", d["e"], "tests", h2)
        e = self.show(d["e"])
        self.assertEqual([p["hypothesis"] for p in e["predictions"]], [d["h"]])
        self.assertEqual([l["to"] for l in e["links"] if l["rel"] == "tests"], [d["h"]])
        self.assertEqual(self.lint_msgs()[0], 0)

    def test_set_tags(self):
        d = self.d
        c = self.concl(d["r"])
        for nid in (d["g"], d["q"], d["h"], d["e"], d["r"], c):
            self.ok("set", nid, "tags", "a", "--append")
            self.ok("set", nid, "tags", "b", "--append")
            self.assertEqual(self.show(nid)["tags"], ["a", "b"])
            self.ok("set", nid, "tags", "a", "--remove")
            self.assertEqual(self.show(nid)["tags"], ["b"])
        self.ok("set", d["q"], "tags", "y")  # without --append: replaces
        self.assertEqual(self.show(d["q"])["tags"], ["y"])
        self.fails("set", d["q"], "tags", "nope", "--remove")
        self.fails("set", d["q"], "tags", "y", "--append")  # duplicate
        self.fails("set", d["q"], "title", "x", "--append")

    def test_set_field_rules(self):
        d = self.d
        c = self.concl(d["r"])
        self.ok("set", c, "body", "notes")
        self.ok("set", c, "refs", "foam-1", "--append")
        self.ok("set", d["g"], "body", "more")
        self.ok("set", d["q"], "title", "Renamed?")
        self.assertEqual(self.show(d["q"])["title"], "Renamed?")
        self.fails("set", d["g"], "title", "Reworded")  # active goal: supersede instead
        self.ok("status", d["q"], "parked", "--reason", "r")
        self.fails("set", d["q"], "title", "Again?")
        for f in ("bogus", "status", "author", "links", "log", "created", "id", "prediction"):
            self.fails("set", d["q"], f, "x")
        self.ok("set", d["q"], "body", "-", input="multi\nline\n")
        self.assertEqual(self.show(d["q"])["body"], "multi\nline")
        ev = self.show(d["q"])["log"][-1]
        self.assertEqual((ev["event"], ev["field"]), ("set", "body"))

    def test_hypothesis_locked_by_frozen_experiment(self):
        d = self.d
        self.reset("draft")
        self.ok("set", d["h"], "prediction", "P2")  # a draft experiment does not lock it
        self.ok("set", d["h"], "title", "Hyp2")
        self.ok("freeze", d["e"])
        self.assertIn("supersede", self.fails("set", d["h"], "prediction", "P3"))
        self.fails("set", d["h"], "title", "Hyp3")
        self.ok("set", d["h"], "body", "ok")


# ================================================== 10 invalidate ===

class TestInvalidate(SnapCase):
    def test_invalidate(self):
        d = self.d
        self.fails("invalidate", d["r"])  # --reason required
        self.fails("invalidate", d["q"], "--reason", "x")
        self.ok("invalidate", d["r"], "--reason", "wrong seed")
        n = self.show(d["r"])
        self.assertEqual((n["status"], n["log"][-1]["reason"]), ("invalidated", "wrong seed"))
        self.assertIn("already", self.fails("invalidate", d["r"], "--reason", "x"))

    def test_lint_flags_supported_conclusion_on_invalidated_result(self):
        c = self.concl(self.d["r"])
        self.ok("invalidate", self.d["r"], "--reason", "bug")
        self.assertEqual(self.assertLint("error", c, "invalidated"), 1)


# ======================================================== 11 lint ===

class TestLint(SnapCase):
    def test_clean_and_json_shape(self):
        rc, items = self.lint()
        self.assertEqual((rc, items), (0, []))
        self.assertEqual(self.ok("lint"), "ok")
        self.add("goal", "G2", "--link", "supersedes:" + self.d["g"])
        rc, items = self.lint()
        self.assertEqual(rc, 1)
        for i in items:
            self.assertEqual(set(i), {"level", "id", "message"})
        levels = [i["level"] for i in items]
        self.assertEqual(levels, sorted(levels, key=lambda l: l != "error"))
        self.assertRegex(self.nb("lint")[1], r"(?m)^error\s+" + self.d["e"])

    def test_dangling_link_error(self):
        self.link_raw(self.d["q"], "refines", "goal-zzzz")
        self.assertEqual(self.assertLint("error", self.d["q"], "dangling"), 1)

    def test_cycles(self):
        d = self.d
        q2 = self.add("question", "Q2?", "--link", "refines:" + d["q"])
        self.link_raw(d["q"], "refines", q2)
        _, msgs = self.lint_msgs()
        self.assertTrue([m for m in msgs if m[0] == "error" and "cycle in refines" in m[2]], msgs)
        self.reset()
        g2 = self.add("goal", "G2", "--link", "supersedes:" + d["g"])
        self.link_raw(d["g"], "supersedes", g2)
        _, msgs = self.lint_msgs()
        self.assertTrue([m for m in msgs if "cycle in supersedes" in m[2]], msgs)

    def test_edge_type_mismatch_and_schema_errors(self):
        d = self.d
        self.link_raw(d["h"], "refines", d["g"])
        self.assertLint("error", d["h"], "refines")
        self.reset()
        self.edit_ref(lambda n, m: n[d["q"]].update(links=[]))
        self.assertLint("error", d["q"], "refines")
        self.reset()
        self.edit_ref(lambda n, m: n[d["q"]].update(bogus=1))
        self.assertLint("error", d["q"], "unknown field")
        self.reset()
        self.edit_ref(lambda n, m: n[d["q"]].update(status="frozen"))
        self.assertLint("error", d["q"], "status")

    def test_spec_hash_mismatch_error(self):
        d = self.d
        self.edit_ref(lambda n, m: n[d["e"]].update(spec="changed after freezing"))
        self.assertEqual(self.assertLint("error", d["e"], "spec_hash"), 1)

    def test_experiment_under_superseded_goal_error(self):
        d = self.d
        self.reset("draft")
        self.add("goal", "G2", "--link", "supersedes:" + d["g"])
        self.assertEqual(self.assertLint("error", d["e"], "no path to an active goal"), 1)
        self.reset("full")
        self.add("goal", "G2", "--link", "supersedes:" + d["g"])
        self.assertLint("error", d["e"], "no path to an active goal")
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "m 1 > 0")  # done experiments are history
        self.assertEqual(self.show(d["e"])["status"], "done")
        self.assertEqual([m for m in self.lint_msgs()[1] if m[1] == d["e"]], [])

    def test_drift_warning_for_chain_of_two_leads(self):
        d = self.d
        l1 = self.add("lead", "L1", "--rationale", "r", "--from", d["r"])
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"])
        self.ok("link", l1, "spawns", h2)
        e2, r2 = self.new_exp(h2)
        l2 = self.add("lead", "L2", "--rationale", "r", "--from", r2)
        e3, _ = self.new_exp(h2, freeze=False, title="E3")
        self.ok("link", l2, "spawns", e3)
        rc = self.assertLint("warn", e3, "drift")
        self.assertEqual(rc, 0)
        _, msgs = self.lint_msgs()
        self.assertEqual([m for m in msgs if m[1] in (e2, d["e"]) and "drift" in m[2]], [])
        p = json.loads(self.ok("path", e3, "--json"))
        self.assertEqual((len(p["lineage_leads"]), p["drift"]), (2, 2))
        self.ok("config", "set", "drift_leads", "1")
        self.assertLint("warn", e2, "drift")
        self.ok("config", "set", "drift_leads", "3")
        self.assertNoLint(e3, "drift")

    def test_open_question_under_superseded_goal_warns(self):
        d = self.d
        self.add("goal", "G2", "--link", "supersedes:" + d["g"])
        self.assertLint("warn", d["q"], "no path to an active goal")
        self.ok("status", d["q"], "parked", "--reason", "old goal")
        self.assertNoLint(d["q"], "no path")

    def test_lost_hypothesis_verdict(self):
        d = self.d
        c1 = self.concl(d["r"], "--link", "supports:" + d["h"], author="claude")
        self.confirm(c1, "--also", d["h"])
        self.assertEqual(self.show(d["h"])["status"], "supported")
        self.assertNoLint(d["h"], "neither a current verdict")
        self.concl(d["r"], "--link", "supersedes:" + c1, title="Newer")
        self.assertEqual(self.assertLint("warn", d["h"], "neither a current verdict nor a supported conclusion"), 0)

    def test_hypothesis_backed_by_verdict_does_not_warn(self):
        d = self.d
        self.ok("verdict", d["r"], d["h"], "refuted", "--basis", "m 0.1 < 0.5")
        self.assertNoLint(d["h"], "neither")
        self.ok("invalidate", d["r"], "--reason", "bug")  # withdraws the verdict; status recomputed, no warning
        self.assertEqual(self.show(d["h"])["status"], "open")
        self.assertNoLint(d["h"], "neither")

    def test_lost_answered_verdict(self):
        d = self.d
        c1 = self.concl(d["r"], "--link", "answers:" + d["q"])
        self.ok("status", d["q"], "answered")
        self.concl(d["r"], "--link", "supersedes:" + c1, title="Newer")
        self.assertLint("warn", d["q"], "answered")

    def test_settled_question_whose_decision_superseded(self):
        d = self.d
        d1 = self.add("decision", "D1", "--rationale", "r", "--link", "affects:" + d["q"])
        self.ok("status", d["q"], "settled")
        self.assertNoLint(d["q"], "settled")
        self.add("decision", "D2", "--rationale", "r", "--link", "supersedes:" + d1)
        self.assertEqual(self.assertLint("warn", d["q"], "settled"), 0)

    def test_pending_age(self):
        g = self.add("goal", "G2", author="claude", today="2026-10-01")
        self.assertLint("warn", g, "pending", today="2026-10-20")
        self.assertNoLint(g, "pending for", today="2026-10-08")  # 7 days is not older than 7
        self.assertLint("warn", g, "pending", today="2026-10-09")
        self.ok("config", "set", "pending_days", "30", today="2026-10-01")
        self.assertNoLint(g, "pending", today="2026-10-20")

    def test_contradicted_after_confirmation(self):
        d = self.d
        c = self.concl(d["r"])
        self.assertNoLint(c, "contradicted")
        r2 = self.ok("result", d["e"], "later result")
        self.ok("link", r2, "contradicts", c)
        self.assertEqual(self.assertLint("warn", c, "contradicted by " + r2), 0)

    def test_contradiction_before_confirmation_does_not_warn(self):
        d = self.d
        c = self.concl(d["r"], author="claude")
        r2 = self.ok("result", d["e"], "other result")
        self.ok("link", r2, "contradicts", c)
        self.confirm(c)
        self.assertNoLint(c, "contradicted")

    def test_audit_verdicts(self):
        d = self.d
        c1, c2, c3 = (self.concl(d["r"], title=t) for t in ("C1", "C2", "C3"))
        self.add("audit", "A", "--of", c1, "--verdict", "concerns", "--findings", "weak controls")
        self.add("audit", "B", "--of", c2, "--verdict", "unsound", "--findings", "bad")
        self.add("audit", "C", "--of", c3, "--verdict", "sound", "--findings", "good")
        self.assertLint("warn", c1, "concerns")
        self.assertLint("warn", c2, "unsound")
        self.assertNoLint(c3, "audit")
        self.assertEqual(self.nb("lint")[0], 0)  # warnings only

    def test_provenance_commit_unreachable(self):
        d = self.d
        tree = self.git("hash-object", "-t", "tree", "-w", "--stdin", input="")
        orphan = self.git(*GIT_ID, "commit-tree", tree, "-m", "orphan")
        r = self.ok("result", d["e"], "s", "--commit", orphan)
        r_gone = self.ok("result", d["e"], "s", "--commit", "0123456789abcdef")
        r_ok = self.ok("result", d["e"], "s2")
        self.assertLint("warn", r, "not reachable")
        self.assertLint("warn", r_gone, "not reachable")
        self.assertNoLint(r_ok, "reachable")

    def test_missing_artifact(self):
        d = self.d
        (self.repo / "out").mkdir()
        (self.repo / "out" / "here.npy").write_text("x")
        r = self.ok("result", d["e"], "s", "--artifact", "out/gone.npy", "--artifact", "https://example.org/x",
                    "--artifact", "out/here.npy")
        r2 = self.ok("result", d["e"], "s", "--artifact", "out/gone2.npy")
        self.assertNoLint(r, "gone")  # nothing rests on it yet
        self.concl(r)
        self.assertLint("warn", r, "out/gone.npy")
        _, msgs = self.lint_msgs()
        self.assertFalse([m for m in msgs if "example.org" in m[2] or "here.npy" in m[2] or m[1] == r2])

    def test_min_results_supported(self):
        c = self.concl(self.d["r"])
        self.ok("config", "set", "min_results_supported", "2")
        self.assertLint("warn", c, "fewer than 2")

    def test_hand_made_derivation_errors(self):
        d = self.d
        x = self.add("exploration", "X", "--spec", "s", "--exec", "analysis", "--link", "investigates:" + d["q"])
        self.ok("freeze", x)
        xr = self.ok("result", x, "saw")
        c = self.concl(d["r"])
        self.edit_ref(lambda n, m: n[c].update(links=[{"rel": "derived-from", "to": xr}]))
        self.assertLint("error", c, "exploration")
        self.reset()
        self.edit_ref(lambda n, m: n[d["e"]].update(links=[l for l in n[d["e"]]["links"] if l["rel"] != "produces"]))
        self.assertLint("error", d["r"], "produced by")

    def test_write_refuses_only_new_errors(self):
        self.link_raw(self.d["q"], "refines", "goal-zzzz")
        self.add("goal", "Another")  # a pre-existing error does not block unrelated writes
        self.assertEqual(self.lint_msgs()[0], 1)


# ======================================================== 12 prime ===

def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:]
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return out


class TestPrimeEmpty(NbCase):
    def test_silent_outside_repo_and_without_notebook(self):
        plain = self.td / "plain"
        plain.mkdir()
        for args in (["prime"], ["prime", "--hook-json"]):
            self.assertEqual(self.nb(*args, cwd=plain), (0, "", ""))
            self.assertEqual(self.nb(*args), (0, "", ""))

    def test_empty_notebook_header_only(self):
        self.init()
        self.assertTrue(self.ok("prime").startswith("# lab-notebook"))

    def test_sections_only_when_non_empty(self):
        self.init()
        g = self.add("goal", "The goal")
        self.assertEqual(list(sections(self.ok("prime"))), ["Goals"])
        q = self.add("question", "Open one?", "--link", "refines:" + g)
        s = sections(self.ok("prime"))
        self.assertEqual(list(s), ["Goals", "Open questions"])
        self.assertIn(q, s["Open questions"][0])

    def test_limit_cap_and_hook_json(self):
        self.init()
        g = self.add("goal", "G " + "x" * 60)
        for i in range(7):
            self.add("question", "Q%d " % i + "y" * 70 + "?", "--link", "refines:" + g)
        for i in range(5):
            self.add("goal", "Pending %d " % i + "z" * 70, author="claude")
        full = self.ok("prime")
        lines = sections(full)["Open questions"]
        self.assertEqual(len(lines), 6)
        self.assertIn("+2 more", lines[-1])
        cap = len(full) - 150
        out = self.ok("prime", "--max-chars", str(cap))
        self.assertLessEqual(len(out), cap)
        self.assertRegex(out, r"(?m)^## [A-Za-z ()]+: \d+ \(nb ")
        self.assertLessEqual(len(self.ok("prime", "--max-chars", "400")), 400)
        self.ok("config", "set", "prime_max_chars", "600")
        self.assertLessEqual(len(self.ok("prime")), 600)
        obj = json.loads(self.ok("prime", "--hook-json"))
        self.assertEqual(list(obj), ["hookSpecificOutput"])
        self.assertEqual(obj["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertEqual(obj["hookSpecificOutput"]["additionalContext"], self.ok("prime"))


class TestPrime(SnapCase):
    def test_all_sections_in_order(self):
        d = self.d
        self.concl(d["r"], "--confidence", "high")
        self.add("lead", "Lead", "--rationale", "r", "--from", d["r"])
        self.add("goal", "Pending goal", author="claude")
        r2 = self.ok("result", d["e"], "another result")  # unreviewed, and the experiment lacks a verdict
        s = sections(self.ok("prime"))
        self.assertEqual(list(s)[:7], ["Goals", "Awaiting the user (pending, not established)", "Needs closing",
                                       "In flight (frozen)", "Open questions", "Recent conclusions", "Active leads"])
        closing = "\n".join(s["Needs closing"])
        self.assertIn(r2 + " ", closing)
        self.assertIn("unreviewed", closing)
        self.assertIn("verdict missing", closing)
        self.assertIn("2 result", s["In flight (frozen)"][0])
        self.assertIn("0 runs", s["In flight (frozen)"][0])
        self.assertIn("confidence high", s["Recent conclusions"][0])

    def test_pending_only_under_awaiting(self):
        d = self.d
        ids = [self.add("goal", "Pending goal", author="claude"), self.concl(d["r"], author="claude"),
               self.add("lead", "Pending lead", "--rationale", "r", "--from", d["r"], author="claude")]
        s = sections(self.ok("prime"))
        awaiting = "\n".join(s["Awaiting the user (pending, not established)"])
        for title, lines in s.items():
            for nid in ids:
                if title.startswith("Awaiting"):
                    self.assertIn(nid, awaiting)
                else:
                    self.assertNotIn(nid, "\n".join(lines), title)
        self.assertNotIn("Recent conclusions", s)
        self.assertNotIn("Active leads", s)

    def test_superseded_goal_hides_questions_and_counts_lint(self):
        self.add("goal", "G2", "--link", "supersedes:" + self.d["g"])
        s = sections(self.ok("prime"))
        self.assertNotIn("Open questions", s)
        self.assertTrue([t for t in s if t.startswith("Lint: ") and "error" in t and "warning" in t], list(s))


# ======================================================== 13 reads ===

class TestReads(SnapCase):
    def setUp(self):
        super().setUp()
        self.c = self.concl(self.d["r"], author="claude")

    def test_json_parseable(self):
        d = self.d
        for c in [("show", d["e"]), ("context", d["q"]), ("path", d["r"]), ("pending",), ("query",), ("log",),
                  ("config", "get"), ("config", "get", "pending_days"), ("lint",)]:
            rc, out, err = self.nb(*c, "--json")
            self.assertIn(rc, (0, 1), (c, err))
            json.loads(out)

    def test_show(self):
        d = self.d
        n = self.show(d["q"])
        self.assertEqual(n["type"], "question")
        self.assertIn(("addresses", d["h"]), {(i["rel"], i["from"]) for i in n["inbound"]})
        self.assertIn("retro", n)
        out = self.ok("show", d["e"])
        for needle in (d["e"], "frozen", "predictions:", "produces", "log:"):
            self.assertIn(needle, out)
        self.assertIn("incoming:", self.ok("show", d["q"]))

    def test_context(self):
        d = self.d
        one = json.loads(self.ok("context", d["h"], "--json"))
        self.assertEqual({n["node"]["id"] for n in one["neighbours"]}, {d["q"], d["e"]})
        two = json.loads(self.ok("context", d["h"], "--depth", "2", "--json"))
        self.assertTrue({d["g"], d["r"]} <= {n["node"]["id"] for n in two["neighbours"]})
        self.assertEqual(len(self.ok("context", d["h"]).splitlines()), 3)

    def test_path(self):
        d = self.d
        p = json.loads(self.ok("path", d["r"], "--json"))
        self.assertEqual(p["paths"], [[d["r"], d["e"], d["h"], d["q"], d["g"]]])
        self.assertEqual(p["goal_status"][d["g"]], "active")
        self.assertIn(d["g"], self.ok("path", d["r"]))
        e2 = self.add("experiment", "Lonely")
        self.assertEqual(json.loads(self.ok("path", e2, "--json"))["paths"], [])
        self.assertIn("no path", self.ok("path", e2))

    def test_pending(self):
        d = self.d
        rows = json.loads(self.ok("pending", "--json"))
        self.assertEqual([(r["id"], r["awaiting"]) for r in rows],
                         [(self.c, "confirm"), (d["e"], "closing"), (d["r"], "review")])
        self.assertEqual(rows[0]["origin"], "claude")
        self.assertIn("not audited", rows[0]["notes"])
        out = self.ok("pending")
        self.assertIn(self.c, out)
        self.assertIn("Claude's read", out)
        self.assertIn("Needs closing", out)
        self.confirm(self.c)  # reviews d["r"]
        self.assertEqual([(r["id"], r["awaiting"]) for r in json.loads(self.ok("pending", "--json"))],
                         [(d["e"], "closing")])
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "m 1 > 0")
        self.assertEqual(json.loads(self.ok("pending", "--json")), [])
        self.assertIn("nothing pending", self.ok("pending"))

    def test_query_filters(self):
        d = self.d
        self.assertEqual(self.query("--type", "goal"), [d["g"]])
        self.assertEqual(self.query("--type", "question", "--status", "open"), [d["q"]])
        self.assertEqual(self.query("--status", "pending"), [self.c])
        self.assertEqual(self.query("--author", "claude"), [self.c])
        self.assertEqual(self.query("--tag", "nothing"), [])
        for nid, t in ((d["h"], "alpha"), (d["h"], "beta"), (d["q"], "alpha")):
            self.ok("set", nid, "tags", t, "--append")
        self.assertEqual(sorted(self.query("--tag", "alpha")), sorted([d["h"], d["q"]]))
        self.assertEqual(self.query("--tag", "alpha", "--tag", "beta"), [d["h"]])
        self.assertEqual(self.query("--text", "HYP"), [d["h"]])
        self.assertEqual(self.query("--text", "summary of facts"), [d["r"]])
        self.assertEqual(self.query("--text", "zzzzzz"), [])
        self.assertIn("no matches", self.ok("query", "--text", "zzzzzz"))

    def test_query_since_and_order(self):
        d = self.d
        self.ok("set", d["q"], "tags", "late", "--append", today="2026-11-05")
        self.assertEqual(self.query("--since", "2026-11-01"), [d["q"]])
        self.assertIn(d["g"], self.query("--since", "2026-10-28"))
        self.assertEqual(self.query("--since", "2027-01-01"), [])
        late = self.add("question", "Late?", "--link", "refines:" + d["g"], today="2026-12-01")
        self.assertEqual(self.query()[0], late)

    def test_query_limit_and_all(self):
        d = self.d
        chars = "0123456789abcdefghjkmnpqrstvwxyz"

        def many(nodes, meta):
            for i in range(60):
                nid = "q-%s%saa" % (chars[i // 32], chars[i % 32])
                nodes[nid] = self.raw(nid, "question", "Bulk %d" % i, "open", links=[("refines", d["g"])])
        self.edit_ref(many)
        total = len(self.query("--all"))
        self.assertGreater(total, 50)
        self.assertEqual(len(self.query()), 50)
        out = self.ok("query").splitlines()
        self.assertEqual(len(out), 51)
        self.assertEqual(out[-1], "(+%d more; --all)" % (total - 50))
        out_all = self.ok("query", "--all").splitlines()
        self.assertEqual(len(out_all), total)

    def test_log(self):
        rows = json.loads(self.ok("log", "--json"))
        self.assertEqual(rows[0]["message"], "nb: add " + self.c)
        self.assertEqual(set(rows[0]), {"commit", "date", "message"})
        self.assertEqual(rows[-1]["message"], "nb: init")
        self.assertEqual(len(json.loads(self.ok("log", "-n", "2", "--json"))), 2)
        msgs = [r["message"] for r in rows]
        self.assertIn("nb: freeze " + self.d["e"], msgs)
        self.assertIn("nb: result " + self.d["r"], msgs)
        self.assertIn("nb: add", self.ok("log"))

    def test_errors(self):
        for cmd in (("show", "zzz-none"), ("context", "zzz-none"), ("path", "zzz-none"),
                    ("config", "get", "bogus")):
            rc, out, err = self.nb(*cmd, "--json")
            self.assertEqual((rc, out), (1, ""))
            self.assertIn("error", json.loads(err))
        rc, out, err = self.nb("show", "zzz-none")
        self.assertEqual(rc, 1)
        self.assertTrue(err.startswith("nb: "))
        self.assertEqual(self.nb("bogus-command")[0], 2)
        self.assertEqual(self.nb("add", "goal")[0], 2)
        plain = self.td / "plain"
        plain.mkdir()
        rc, out, err = self.nb("query", cwd=plain)
        self.assertEqual(rc, 1)
        self.assertIn("git repository", err)


# ======================================================= 14 config ===

class TestConfig(NbCase):
    def test_defaults_and_get(self):
        self.init()
        self.assertEqual(json.loads(self.ok("config", "get", "--json")),
                         {"prime_max_chars": 4000, "prime_section_limit": 5, "pending_days": 7, "drift_leads": 2,
                          "min_results_supported": 1, "run_patterns": [], "freeze_gate": False,
                          "audit_before_confirm": True, "auditor_model": "sonnet", "brief_tier_limit": 8,
                          "brief_related_limit": 5})
        self.assertEqual(json.loads(self.ok("config", "get", "pending_days", "--json")), {"pending_days": 7})
        self.assertIn("pending_days = 7", self.ok("config", "get", "pending_days"))

    def test_set_and_survive(self):
        self.init()
        self.ok("config", "set", "drift_leads", "4")
        self.ok("config", "set", "run_patterns", '["^python train"]')
        self.add("goal", "G")
        c = json.loads(self.ok("config", "get", "--json"))
        self.assertEqual((c["drift_leads"], c["run_patterns"]), (4, ["^python train"]))
        self.assertEqual(json.loads(self.git("show", REF + ":meta.json"))["config"]["drift_leads"], 4)

    def test_bad_sets_refused(self):
        self.init()
        h = self.head()
        self.assertIn("int", self.fails("config", "set", "pending_days", "abc"))
        for k, v in (("pending_days", "true"), ("pending_days", "1.5"), ("run_patterns", "5"), ("bogus", "1"),
                     ("freeze_gate", "1"), ("freeze_gate", "yes"), ("auditor_model", "3")):
            self.fails("config", "set", k, v)
        self.fails("config", "set", "pending_days")
        self.fails("config", "get", "bogus")
        self.assertEqual(self.head(), h)


# =================================================== 15 concurrency ===

class TestConcurrency(NbCase):
    def parallel_adds(self, n):
        self.init()
        g = self.add("goal", "G")
        procs = [subprocess.Popen([sys.executable, str(NB), "add", "question", "Parallel %d?" % i, "--link", "refines:" + g],
                                  cwd=str(self.repo), env=dict(self.env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for i in range(n)]
        results = [p.communicate(timeout=60) + (p.returncode,) for p in procs]
        ids = [out.strip() for out, err, rc in results if rc == 0]
        failed = [err for out, err, rc in results if rc != 0]
        return g, ids, failed

    def check_all_landed(self, n, ids):
        self.assertEqual(len(set(ids)), n)
        self.assertEqual(set(self.query("--type", "question", "--all")), set(ids))
        self.assertEqual(self.lint_msgs(), (0, []))
        self.assertEqual(self.git("rev-list", "--count", REF), str(2 + n))  # init, goal, n adds: linear history
        self.assertEqual(self.git("rev-list", "--merges", "--count", REF), "0")

    def test_four_parallel_adds_all_succeed(self):
        g, ids, failed = self.parallel_adds(4)
        self.assertEqual(failed, [])
        self.check_all_landed(4, ids)

    def test_eight_parallel_adds_all_succeed(self):
        g, ids, failed = self.parallel_adds(8)
        self.assertEqual(failed, [])
        self.check_all_landed(8, ids)


# ========================================================= 16 sync ===

class TestRetract(SnapCase):
    def test_retract_evidence_link(self):
        d = self.d
        self.ok("link", d["r"], "supports", d["h"])
        self.assertIn("only be removed", self.fails("unlink", d["r"], "supports", d["h"]))  # still refused on a result
        self.fails("retract", d["r"], "supports", d["h"])  # --reason required
        self.fails("retract", d["r"], "produces", d["h"], "--reason", "x")  # only evidence links
        self.assertIn("no contradicts", self.fails("retract", d["r"], "contradicts", d["h"], "--reason", "x"))
        self.ok("retract", d["r"], "supports", d["h"], "--reason", "backfill bug")
        n = self.show(d["r"])
        self.assertNotIn({"rel": "supports", "to": d["h"]}, n.get("links", []))
        self.assertEqual((n["log"][-1]["event"], n["log"][-1]["to"], n["log"][-1]["reason"]),
                         ("retract", "supports " + d["h"], "backfill bug"))
        self.assertEqual(n["status"], "valid")


class TestSync(NbCase):
    def two_clones(self):
        """origin (bare), self.repo (A) and a clone (B), both holding a goal and a question."""
        self.setup_remote()
        self.init()
        self.g = self.add("goal", "Goal")
        self.q = self.add("question", "Shared?", "--link", "refines:" + self.g)
        self.ok("sync")
        self.B = self.clone("B")
        self.ok_in(self.B, "init")
        return self.B

    def remote_head(self):
        return git(self.env, self.bare, "rev-parse", REF)

    def test_no_origin(self):
        self.init()
        self.assertIn("origin", self.fails("sync"))

    def test_push_up_to_date_quiet(self):
        self.setup_remote()
        self.init()
        self.add("goal", "G")
        self.assertIn("pushed", self.ok("sync"))
        self.assertEqual(self.remote_head(), self.head())
        self.assertIn("up to date", self.ok("sync"))
        self.add("goal", "G2")
        self.assertEqual(self.ok("sync", "--quiet"), "")
        self.assertEqual(self.remote_head(), self.head())

    def test_fast_forward(self):
        B = self.two_clones()
        a = self.add("question", "From A?", "--link", "refines:" + self.g)
        self.ok("sync")
        self.assertIn("fast-forwarded", self.ok_in(B, "sync"))
        self.assertEqual(self.head(repo=B), self.head())
        self.assertIn(a, json.loads(self.ok_in(B, "query", "--all", "--json")).__repr__())

    def test_diverged_adds_merge(self):
        B = self.two_clones()
        a = self.add("question", "From A?", "--link", "refines:" + self.g)
        b = self.ok_in(B, "add", "question", "From B?", "--link", "refines:" + self.g).split()[-1]
        self.ok("sync")
        self.assertIn("merged", self.ok_in(B, "sync"))
        self.ok("sync")
        for repo in (self.repo, B):
            ids = {r["id"] for r in json.loads(self.ok_in(repo, "query", "--all", "--json"))}
            self.assertTrue({a, b, self.q, self.g} <= ids, ids)
        self.assertEqual(self.head(), self.head(repo=B))
        self.assertEqual(self.remote_head(), self.head())
        self.assertEqual(len(git(self.env, B, "log", "-1", "--format=%P", REF).split()), 2)
        self.assertEqual(json.loads(self.ok_in(B, "lint", "--json")), [])

    def test_list_fields_union_and_disjoint_nodes(self):
        B = self.two_clones()
        self.ok("set", self.q, "tags", "alpha", "--append")
        self.ok_in(B, "set", self.q, "tags", "beta", "--append")
        d1 = self.add("decision", "D1", "--rationale", "r")
        self.ok("sync")
        self.ok_in(B, "sync")
        self.ok("sync")
        for repo in (self.repo, B):
            n = json.loads(self.ok_in(repo, "show", self.q, "--json"))
            self.assertEqual(sorted(n["tags"]), ["alpha", "beta"])
            # identical log entries (same date, author, event, field) from both sides are deduplicated by the merge
            self.assertGreaterEqual(len([e for e in n["log"] if e["event"] == "set"]), 1)
        # links on one node, added on both sides
        self.ok("link", d1, "affects", self.q)
        g2 = self.ok_in(B, "add", "goal", "G2").split()[-1]
        self.ok_in(B, "link", d1, "affects", g2)
        self.ok("sync")
        self.ok_in(B, "sync")
        n = json.loads(self.ok_in(B, "show", d1, "--json"))
        self.assertEqual({(l["rel"], l["to"]) for l in n["links"]}, {("affects", self.q), ("affects", g2)})

    def test_removed_link_stays_removed(self):
        B = self.two_clones()
        q2 = self.add("question", "Q2?", "--link", "refines:" + self.g, "--link", "refines:" + self.q)
        q3 = self.add("question", "Q3?", "--link", "refines:" + self.g)
        self.ok("sync")
        self.ok_in(B, "sync")
        self.ok("link", q2, "refines", q3)  # A adds a link while B removes another
        self.ok_in(B, "unlink", q2, "refines", self.q)
        self.ok("sync")
        self.ok_in(B, "sync")
        n = json.loads(self.ok_in(B, "show", q2, "--json"))
        self.assertEqual({(l["rel"], l["to"]) for l in n["links"]}, {("refines", self.g), ("refines", q3)})

    def test_scalar_conflict_stops_and_resolves(self):
        B = self.two_clones()
        self.ok("set", self.q, "title", "Title from A?")
        self.ok_in(B, "set", self.q, "title", "Title from B?")
        self.ok("sync")
        before_b, before_remote = self.head(repo=B), self.remote_head()
        rc, out, err = self.nb_in(B, "sync")
        self.assertEqual(rc, 1)
        self.assertIn(self.q, err)
        self.assertIn("title", err)
        self.assertEqual(self.head(repo=B), before_b)
        self.assertEqual(self.remote_head(), before_remote)
        self.assertEqual(self.head(), before_remote)
        # resolve by making B agree with A
        self.ok_in(B, "set", self.q, "title", "Title from A?")
        self.ok_in(B, "sync")
        self.assertEqual(json.loads(self.ok_in(B, "show", self.q, "--json"))["title"], "Title from A?")
        self.assertEqual(self.remote_head(), self.head(repo=B))
        self.ok("sync")
        self.assertEqual(self.head(), self.head(repo=B))

    def test_status_conflict_reported(self):
        B = self.two_clones()
        self.ok("status", self.q, "parked", "--reason", "A parks")
        self.ok_in(B, "status", self.q, "abandoned", "--reason", "B abandons")
        self.ok("sync")
        rc, out, err = self.nb_in(B, "sync")
        self.assertEqual(rc, 1)
        self.assertIn("status", err)

    def test_merge_that_fails_validation_writes_nothing(self):
        B = self.two_clones()
        q2 = self.add("question", "Q2?", "--link", "refines:" + self.g)
        self.ok("sync")
        self.ok_in(B, "sync")
        self.ok("link", self.q, "refines", q2)
        self.ok_in(B, "link", q2, "refines", self.q)
        self.ok("sync")
        before_b, before_remote = self.head(repo=B), self.remote_head()
        rc, out, err = self.nb_in(B, "sync")
        self.assertEqual(rc, 1)
        self.assertIn("cycle", err)
        self.assertEqual(self.head(repo=B), before_b)
        self.assertEqual(self.remote_head(), before_remote)

    def test_pre_push_hook_syncs_notebook(self):
        self.setup_remote()
        self.init()
        self.add("goal", "G")
        self.commit_file()
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        self.assertEqual(self.remote_head(), self.head())


# ======================================================= 17 schema ===

class TestSchema(SnapCase):
    def test_newer_schema_refused_everywhere(self):
        d = self.d
        self.edit_ref(lambda n, m: m.update(schema=99))
        h = self.head()
        for cmd in (("query",), ("show", d["g"]), ("add", "goal", "G"), ("lint",), ("config", "get"),
                    ("status", d["q"], "parked", "--reason", "r")):
            rc, out, err = self.nb(*cmd)
            self.assertEqual(rc, 1, cmd)
            self.assertIn("schema", err, cmd)
        rc, out, err = self.nb("query", "--json")
        self.assertIn("schema", json.loads(err)["error"])
        self.assertEqual(self.head(), h)
        self.assertEqual(self.nb("prime"), (0, "", ""))

    def test_older_schema_written_back_current(self):
        self.edit_ref(lambda n, m: m.update(schema=0))
        self.add("goal", "G")
        self.assertEqual(json.loads(self.git("show", REF + ":meta.json"))["schema"], 1)


# ===================================================== 18 fixture ===

class TestFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory(prefix="nb-fixture-")
        cls.td = Path(cls._td.name)
        cls.env = make_env(cls.td)
        cls.repo = cls.td / "repo"
        init_repo(cls.env, cls.repo)
        assert run_nb(cls.env, cls.repo, ["init"])[0] == 0

        def run(argv, author, date):
            rc, out, err = run_nb(cls.env, cls.repo, argv, author, date)
            if rc != 0:
                raise AssertionError("fixture step failed: nb %s\n%s" % (" ".join(argv), err))
            return out

        cls.ids = bioemu.build(run)

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def nb(self, *args):
        return run_nb(self.env, self.repo, args, "user")

    def node(self, name):
        rc, out, err = self.nb("show", self.ids[name], "--json")
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def test_replay_lints_clean_and_primes_within_cap(self):
        rows = json.loads(self.nb("query", "--all", "--json")[1])
        self.assertEqual(len(rows), len(self.ids))
        self.assertGreaterEqual(len(rows), 69)
        rc, out, err = self.nb("lint", "--json")
        items = json.loads(out)
        self.assertEqual([i for i in items if i["level"] == "error"], [])
        self.assertEqual(rc, 0)
        rc, out, err = self.nb("prime")
        self.assertEqual(rc, 0)
        self.assertLessEqual(len(out), 4000)

    def test_spot_statuses(self):
        for name, st in (("G1", "superseded"), ("G2", "superseded"), ("G3", "active"), ("C_ignore", "superseded"),
                         ("C7", "pending"), ("Q_base", "settled"), ("L_v2", "followed"), ("E_steer", "draft")):
            self.assertEqual(self.node(name)["status"], st, name)
        active = json.loads(self.nb("query", "--type", "goal", "--status", "active", "--json")[1])
        self.assertEqual([r["id"] for r in active], [self.ids["G3"]])
        self.assertIn(self.ids["C7"], [r["id"] for r in json.loads(self.nb("pending", "--json")[1])])

    def test_retro_flags(self):
        self.assertFalse(self.node("E_multi")["retro"])
        self.assertTrue(self.node("E_cmt2")["retro"])


# ============================================ 19 closing the loop ===

def nb_full(case, *args, **kw):
    """(stdout, stderr) of a successful nb call."""
    rc, out, err = case.nb(*args, **kw)
    case.assertEqual(rc, 0, "nb %s failed\nstdout: %s\nstderr: %s" % (" ".join(args), out, err))
    return out.strip(), err


class TestVerdicts(SnapCase):
    def second_hyp(self, title="H2"):
        return self.add("hypothesis", title, "--prediction", "p2", "--link", "addresses:" + self.d["q"])

    def test_result_with_verdict_applies_at_once(self):
        d = self.d
        self.reset("draft")
        self.ok("freeze", d["e"])
        out, err = nb_full(self, "result", d["e"], "m was 0.1", "--verdict", d["h"], "refuted", "m 0.1 < 0.5")
        self.assertRegex(out, ID_RE % "res")
        self.assertIn("added result %s: m was 0.1" % out, err)
        self.assertIn("verdict %s refuted: m 0.1 < 0.5" % d["h"], err)
        self.assertIn("%s open -> refuted" % d["h"], err)
        self.assertIn("%s frozen -> done" % d["e"], err)
        self.assertEqual(self.show(d["h"])["status"], "refuted")
        e = self.show(d["e"])
        self.assertEqual(e["status"], "done")
        self.assertEqual(e["verdicts"], [{"hypothesis": d["h"], "verdict": "refuted", "result": out,
                                          "basis": "m 0.1 < 0.5", "date": TODAY, "author": "user"}])
        self.assertEqual(self.lint_msgs()[0], 0)

    def test_invalid_verdict_refuses_whole_result(self):
        d = self.d
        h2 = self.second_hyp()
        before, n = self.head(), len(self.query("--type", "result"))
        for extra in (["--verdict", d["h"], "supported", "b", "--verdict", h2, "supported", "b"],  # h2 not predicted
                      ["--verdict", d["h"], "proven", "b"],
                      ["--verdict", d["h"], "supported", "  "],
                      ["--verdict", d["h"], "supported", "b", "--verdict", d["h"], "refuted", "b"],
                      ["--verdict", d["h"], "supported", "b", "--interim"]):
            self.fails("result", d["e"], "s", *extra)
        self.assertIn("does not predict", self.fails("result", d["e"], "s", "--verdict", h2, "supported", "b"))
        self.assertEqual((self.head(), len(self.query("--type", "result"))), (before, n))
        x = self.add("exploration", "X", "--spec", "look", "--exec", "analysis", "--link", "investigates:" + d["q"])
        self.ok("freeze", x)
        self.assertIn("exploration", self.fails("result", x, "s", "--verdict", d["h"], "supported", "b"))
        self.assertIn("unknown field", self.fails("set", x, "verdicts", "x") + "unknown field")

    def test_backfill_and_replace_flags(self):
        d = self.d
        self.assertIn("no current verdict", self.fails("verdict", d["r"], d["h"], "supported", "--basis", "b",
                                                       "--replace", "--reason", "x"))
        out = self.ok("verdict", d["r"], d["h"], "supported", "--basis", "m 0.9 > 0.5")
        self.assertIn("frozen -> done", out)
        self.assertEqual(self.show(d["h"])["status"], "supported")
        self.assertIn("--replace", self.fails("verdict", d["r"], d["h"], "refuted", "--basis", "b"))
        self.assertIn("--reason", self.fails("verdict", d["r"], d["h"], "refuted", "--basis", "b", "--replace"))
        self.fails("verdict", d["r"], d["h"], "refuted", "--basis", "b", "--reason", "x")
        self.fails("verdict", d["r"], d["h"], "refuted", "--replace", "--reason", "x")  # --basis required
        self.ok("verdict", d["r"], d["h"], "refuted", "--basis", "m 0.4 < 0.5 after the unit fix",
                "--replace", "--reason", "metric was read in the wrong units")
        v = self.show(d["e"])["verdicts"]
        self.assertEqual(len(v), 2)
        self.assertEqual((v[1]["replaces"], v[1]["reason"]), (True, "metric was read in the wrong units"))
        self.assertEqual(self.show(d["h"])["status"], "refuted")
        self.assertIn("replaced", self.ok("show", d["e"]))
        self.assertEqual(self.lint_msgs()[0], 0)

    def test_second_result_same_hypothesis_is_a_replacement(self):
        d = self.d
        h2 = self.second_hyp()
        e2 = self.add("experiment", "E2", "--spec", "S", "--exec", "command")
        self.predict(e2, d["h"])
        self.predict(e2, h2)
        self.ok("freeze", e2)
        r1 = self.ok("result", e2, "first", "--verdict", d["h"], "supported", "b1")
        self.assertEqual(self.show(e2)["status"], "frozen")  # h2 still has no verdict
        self.assertIn("replacement", self.fails("result", e2, "second", "--verdict", d["h"], "refuted", "b2"))
        r2 = self.ok("result", e2, "second", "--verdict", h2, "inconclusive", "b3")
        self.assertEqual(self.show(e2)["status"], "done")
        self.assertIn("--replace", self.fails("verdict", r2, d["h"], "refuted", "--basis", "b"))
        # a replacement may be judged on another result of the same experiment
        self.ok("verdict", r1, h2, "refuted", "--basis", "b", "--replace", "--reason", "x")
        self.assertEqual(self.show(h2)["status"], "refuted")

    def test_verdicts_only_on_valid_final_experiment_results(self):
        d = self.d
        ri = self.ok("result", d["e"], "partial", "--interim")
        self.assertIn("interim", self.fails("verdict", ri, d["h"], "supported", "--basis", "b"))
        self.ok("invalidate", d["r"], "--reason", "bug")
        self.fails("verdict", d["r"], d["h"], "supported", "--basis", "b")
        x = self.add("exploration", "X", "--spec", "look", "--exec", "analysis", "--link", "investigates:" + d["q"])
        self.ok("freeze", x)
        rx = self.ok("result", x, "seen")
        self.assertIn("exploration", self.fails("verdict", rx, d["h"], "supported", "--basis", "b"))

    def test_most_recent_event_wins_and_inconclusive_reopens(self):
        d = self.d
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "b")
        e2, _ = self.new_exp(d["h"], result=False)
        self.ok("result", e2, "r2", "--verdict", d["h"], "refuted", "b2", today="2026-10-29")
        self.assertEqual(self.show(d["h"])["status"], "refuted")
        self.assertLint("warn", d["h"], "conflicting current verdicts", today="2026-10-29")
        e3, _ = self.new_exp(d["h"], result=False, title="E3")
        self.ok("result", e3, "r3", "--verdict", d["h"], "inconclusive", "b3", today="2026-10-30")
        h = self.show(d["h"])
        self.assertEqual(h["status"], "open")
        self.assertEqual((h["log"][-1]["event"], h["log"][-1]["from"], h["log"][-1]["to"]), ("verdict", "refuted", "open"))

    def test_invalidation_withdraws_and_recomputes(self):
        d = self.d
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "b")
        e2, _ = self.new_exp(d["h"], result=False)
        r2 = self.ok("result", e2, "r2", "--verdict", d["h"], "refuted", "b2", today="2026-10-29")
        self.assertEqual((self.show(d["h"])["status"], self.show(e2)["status"]), ("refuted", "done"))
        out = self.ok("invalidate", r2, "--reason", "wrong checkpoint", today="2026-10-30")
        self.assertIn("%s refuted -> supported" % d["h"], out)
        self.assertIn("%s done -> frozen" % e2, out)
        self.assertEqual((self.show(d["h"])["status"], self.show(e2)["status"]), ("supported", "frozen"))
        self.assertEqual(self.show(e2)["log"][-1]["event"], "invalidate")
        self.ok("invalidate", d["r"], "--reason", "bug")
        self.assertEqual((self.show(d["h"])["status"], self.show(d["e"])["status"]), ("open", "frozen"))
        self.assertIn("withdrawn", self.ok("show", d["e"]))
        r3 = self.ok("result", e2, "rerun", "--verdict", d["h"], "refuted", "b3")  # not a replacement now
        self.assertEqual((self.show(d["h"])["status"], self.show(e2)["status"]), ("refuted", "done"))
        self.assertTrue(r3)

    def test_superseded_hypothesis_ignores_verdicts(self):
        d = self.d
        self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"], "--link", "supersedes:" + d["h"])
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "b")
        self.assertEqual(self.show(d["h"])["status"], "superseded")
        self.assertEqual(self.show(d["e"])["status"], "done")

    def test_confirm_also_is_a_status_event(self):
        d = self.d
        c = self.concl(d["r"], "--link", "supports:" + d["h"], "--link", "answers:" + d["q"], author="claude")
        fo = {f["id"]: f["to"] for f in self.show(c)["follow_ons"]}
        self.assertEqual(fo, {d["h"]: "supported", d["q"]: "answered"})
        self.assertIn("follow-ons", self.ok("show", c))
        self.audit(c)
        self.assertIn("not a follow-on", self.fails("confirm", c, "--also", d["g"]))
        self.assertEqual(self.show(c)["status"], "pending")
        out = self.ok("confirm", c, "--also", d["h"], "--also", d["q"])
        self.assertIn("%s open -> supported" % d["h"], out)
        self.assertEqual((self.show(d["h"])["status"], self.show(d["q"])["status"]), ("supported", "answered"))
        ev = self.show(d["h"])["log"][-1]
        self.assertEqual((ev["event"], ev["to"], ev["reason"]), ("confirm-also", "supported", "by " + c))
        e2, _ = self.new_exp(d["h"], result=False)
        r2 = self.ok("result", e2, "r2", "--verdict", d["h"], "refuted", "b", today="2026-10-29")
        self.assertEqual(self.show(d["h"])["status"], "refuted")
        self.ok("invalidate", r2, "--reason", "bug", today="2026-10-29")
        self.assertEqual(self.show(d["h"])["status"], "supported")  # the confirm --also event remains

    def test_retro_verdict_marked(self):
        d = self.d
        e, r = self.new_exp(d["h"], retro=True)
        self.ok("verdict", r, d["h"], "refuted", "--basis", "b")
        self.assertIn("[retro]", [l for l in self.ok("show", e).splitlines() if "refuted on" in l][0])
        self.assertIn("[retro]", self.ok("brief", r).splitlines()[2])


class TestReview(SnapCase):
    def test_confirm_writes_reviews_reject_does_not(self):
        d = self.d
        r2 = self.ok("result", d["e"], "second")
        c = self.concl(d["r"], "--from", r2, author="claude")
        self.assertEqual(self.show(d["r"])["review"], "pending: " + c)
        self.assertNotIn("reviews", self.show(d["r"]))
        self.confirm(c)
        for r in (d["r"], r2):
            rv = self.show(r)["reviews"]
            self.assertEqual(rv, [{"date": TODAY, "author": "user", "kind": "confirmed", "by": c}])
            self.assertEqual(self.show(r)["review"], "reviewed: " + c)
        r3 = self.ok("result", d["e"], "third")
        c2 = self.concl(r3, author="claude", title="C2")
        self.ok("reject", c2, "--reason", "no")
        self.assertNotIn("reviews", self.show(r3))

    def test_user_authored_add_reviews_at_once(self):
        d = self.d
        r2 = self.ok("result", d["e"], "second")
        c = self.concl(d["r"])
        lead = self.add("lead", "L", "--rationale", "r", "--from", r2)
        self.assertEqual(self.show(d["r"])["reviews"][0]["by"], c)
        self.assertEqual(self.show(r2)["reviews"][0]["by"], lead)

    def test_nothing_yet(self):
        d = self.d
        r2 = self.ok("result", d["e"], "second")
        out = self.ok("nothing-yet", d["r"], r2, "--note", "want the villin run first")
        self.assertIn("reviewed %s: nothing yet" % d["r"], out)
        rv = self.show(r2)["reviews"]
        self.assertEqual(rv, [{"date": TODAY, "author": "user", "kind": "nothing-yet", "note": "want the villin run first"}])
        self.assertEqual(self.show(d["r"])["review"], "reviewed: nothing yet")
        ri = self.ok("result", d["e"], "partial", "--interim")
        self.assertIn("interim", self.fails("nothing-yet", ri))
        self.ok("invalidate", r2, "--reason", "bug")
        self.fails("nothing-yet", r2)
        self.concl(d["r"])  # a result marked nothing yet can still back a conclusion
        self.assertEqual(self.show(d["r"])["reviews"][-1]["kind"], "confirmed")

    def test_review_durable_after_supersession_and_refutation(self):
        d = self.d
        r2 = self.ok("result", d["e"], "second")
        c1 = self.concl(d["r"])
        self.concl(r2, "--link", "supersedes:" + c1, title="Newer")
        self.assertEqual(self.show(c1)["status"], "superseded")
        self.assertEqual(self.show(d["r"])["review"], "reviewed: " + c1)
        lead = self.add("lead", "L", "--rationale", "r", "--from", r2)
        self.ok("status", lead, "dropped", "--reason", "no")
        self.assertTrue(self.show(r2)["reviews"])
        self.assertNotIn(d["r"], [b["id"] for b in json.loads(self.ok("gate", "--json"))["blockers"]])

    def test_reviews_and_interim_fixed(self):
        d = self.d
        for f in ("reviews", "interim"):
            self.fails("set", d["r"], f, "x")


class TestOriginAndAudit(SnapCase):
    def test_origin_required_for_claude_drafts(self):
        d = self.d
        base = ["--rationale", "why", "--scope", "here", "--alternatives", "none", "--from", d["r"]]
        self.assertIn("--origin", self.fails("add", "conclusion", "C", *base, author="claude"))
        self.assertIn("--user-words", self.fails("add", "conclusion", "C", *base, "--origin", "user", author="claude"))
        self.assertIn("--origin", self.fails("add", "lead", "L", "--rationale", "r", "--from", d["r"], author="claude"))
        self.fails("add", "conclusion", "C", *base, "--origin", "maybe", author="claude")
        c = self.add("conclusion", "C", *base, "--origin", "user", "--user-words", "-", author="claude",
                     input="run 19 looks no better than run 18 to me\n")
        n = self.show(c)
        self.assertEqual((n["origin"], n["user_words"]), ("user", "run 19 looks no better than run 18 to me"))
        self.assertIn("the user's read", self.ok("show", c))
        for f in ("origin", "user_words"):
            self.fails("set", c, f, "claude")
        self.assertNotIn("origin", self.show(self.concl(d["r"], title="User's own")))  # user-authored: neither needed
        self.fails("add", "goal", "G", "--origin", "user")  # not a conclusion or lead

    def test_older_nodes_without_origin_stay_valid(self):
        d = self.d
        c = self.concl(d["r"], author="claude")
        self.edit_ref(lambda n, m: n[c].pop("origin"))
        self.assertEqual(self.lint_msgs()[0], 0)

    def test_audit_before_confirm(self):
        d = self.d
        c = self.concl(d["r"], author="claude")
        self.assertIn("no audit", self.fails("confirm", c))
        a1 = self.audit(c, "concerns", "scope too broad")
        self.ok("set", c, "scope", "chignolin only")
        err = self.fails("confirm", c)
        self.assertIn("not current", err)
        self.assertIn("scope", err)
        self.assertIn("(stale)", self.ok("pending"))
        a2 = self.audit(c)
        self.ok("set", c, "tags", "t", "--append")  # tags, refs and log do not make an audit stale
        self.ok("set", c, "refs", "foam-1")
        self.assertEqual(self.show(c)["latest_audit"]["id"], a2)
        self.ok("confirm", c)
        self.assertTrue(a1)

    def test_latest_audit_only_and_leads(self):
        d = self.d
        lead = self.add("lead", "L", "--rationale", "r", "--from", d["r"], author="claude")
        self.fails("confirm", lead)
        self.audit(lead, "unsound", "bad")
        self.assertLint("warn", lead, "unsound")
        self.audit(lead, "sound", "fine")
        self.assertNoLint(lead, "unsound")
        self.ok("confirm", lead)
        self.assertEqual(self.show(d["r"])["reviews"][0]["by"], lead)
        self.fails("add", "audit", "A", "--of", d["h"], "--verdict", "sound", "--findings", "x")

    def test_switch_off_and_other_types(self):
        d = self.d
        g2 = self.add("goal", "G2", author="claude")
        self.ok("confirm", g2)  # only conclusions and leads need an audit
        c = self.concl(d["r"], author="claude")
        self.ok("config", "set", "audit_before_confirm", "false")
        self.ok("confirm", c)


class TestFreezeGate(SnapCase):
    def draft(self, title="Next"):
        e = self.add("experiment", title, "--spec", "S", "--exec", "command")
        self.predict(e, self.d["h"])
        return e

    def blockers(self):
        return {b["id"]: b["why"] for b in json.loads(self.ok("gate", "--json"))["blockers"]}

    def test_off_by_default_but_reported(self):
        d = self.d
        g = json.loads(self.ok("gate", "--json"))
        self.assertEqual((g["freeze_gate"], g["blocked"]), (False, False))
        self.assertEqual(set(self.blockers()), {d["e"], d["r"]})
        self.assertIn("freeze_gate is off", self.ok("gate"))
        self.ok("freeze", self.draft())

    def test_gate_conditions(self):
        d = self.d
        self.ok("config", "set", "freeze_gate", "true")
        e2 = self.draft()
        err = self.fails("freeze", e2)
        self.assertIn("freeze gate", err)
        self.assertIn(d["r"] + " ", err)
        self.assertIn("summary of facts", err)  # listed with title
        self.assertIn(d["e"] + " ", err)
        self.assertIn("no verdict for " + d["h"], err)
        self.assertTrue(json.loads(self.ok("gate", "--json"))["blocked"])
        self.assertIn("blocked", self.ok("gate"))
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "b")  # verdict: experiment closes
        self.assertEqual(set(self.blockers()), {d["r"]})
        self.ok("nothing-yet", d["r"])  # review: result closes
        self.assertEqual(self.blockers(), {})
        self.assertIn("clear", self.ok("gate"))
        self.ok("freeze", e2)

    def test_parallel_and_interim_do_not_block(self):
        d = self.d
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "b")
        self.ok("nothing-yet", d["r"])
        self.ok("config", "set", "freeze_gate", "true")
        e2 = self.draft("Parallel")
        self.ok("freeze", e2)  # frozen, no results yet: running in parallel
        ri = self.ok("result", e2, "first batch", "--interim")
        self.ok("freeze", self.draft("Third"))
        self.assertEqual(self.blockers(), {})
        self.assertNoLint(e2, "interim", today="2026-11-04")
        self.assertLint("warn", e2, "only interim results", today="2026-11-05")
        closing = sections(self.ok("prime", today="2026-11-05")).get("Needs closing", [])
        self.assertIn(e2, "\n".join(closing))
        self.assertTrue(ri)

    def test_abandoned_experiment_result_still_needs_review(self):
        d = self.d
        self.ok("status", d["e"], "abandoned", "--reason", "dead end")
        self.ok("config", "set", "freeze_gate", "true")
        self.assertEqual(set(self.blockers()), {d["r"]})  # no verdict needed, a review is
        self.fails("freeze", self.draft())

    def test_freeze_prints_id_and_title(self):
        e2 = self.draft("Run 19")
        out, err = nb_full(self, "freeze", e2)
        self.assertEqual(out, e2)
        self.assertIn("frozen %s: Run 19" % e2, err)
        out, err = nb_full(self, "add", "goal", "Another goal")
        self.assertRegex(out, ID_RE % "goal")
        self.assertEqual(err.strip(), "added goal %s: Another goal" % out)


class TestBrief(SnapCase):
    def build(self):
        d = self.d
        b = {}
        self.ok("set", d["r"], "tags", "villin", "--append")
        b["e2"] = self.add("experiment", "Run 2", "--spec", "S", "--exec", "command", "--link", "variant-of:" + d["e"])
        self.predict(b["e2"], d["h"])
        self.ok("freeze", b["e2"])
        b["r2"] = self.ok("result", b["e2"], "Run 2 result", "--verdict", d["h"], "supported", "m 0.9 > 0.5",
                          today="2026-10-29")
        b["e3"] = self.add("experiment", "Run 3", "--spec", "S", "--exec", "command", "--link", "variant-of:" + b["e2"])
        self.predict(b["e3"], d["h"])
        self.ok("freeze", b["e3"])
        b["r3"] = self.ok("result", b["e3"], "Run 3 result", today="2026-10-30")
        b["q2"] = self.add("question", "Other question?", "--link", "refines:" + d["g"])
        b["x"] = self.add("exploration", "Look at run 1", "--spec", "S", "--exec", "analysis",
                          "--link", "investigates:" + b["q2"], "--link", "uses:" + d["r"])
        self.ok("freeze", b["x"])
        b["rx"] = self.ok("result", b["x"], "Exploration finding", today="2026-10-29")
        b["h2"] = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"])
        b["e4"] = self.add("experiment", "Sibling", "--spec", "S", "--exec", "command")
        self.predict(b["e4"], b["h2"])
        self.ok("freeze", b["e4"])
        b["r4"] = self.ok("result", b["e4"], "Sibling result")
        b["r7"] = self.ok("result", b["e4"], "Bad sibling result")
        self.ok("invalidate", b["r7"], "--reason", "bug")
        b["r8"] = self.ok("result", b["e4"], "Partial sibling", "--interim", today="2026-10-29")
        b["h3"] = self.add("hypothesis", "H3", "--prediction", "p", "--link", "addresses:" + b["q2"])
        b["e5"] = self.add("experiment", "Far away", "--spec", "S", "--exec", "command")
        self.predict(b["e5"], b["h3"])
        self.ok("freeze", b["e5"])
        b["r5"] = self.ok("result", b["e5"], "Unrelated words entirely", "--tag", "villin")
        b["r6"] = self.ok("result", b["e5"], "Another summary of facts")
        b["r9"] = self.ok("result", b["e5"], "Nothing in common")
        return b

    def test_tiers(self):
        d = self.d
        b = self.build()
        c = self.concl(b["r2"], author="claude")
        self.ok("nothing-yet", b["r4"])
        data = json.loads(self.ok("brief", d["r"], "--json"))
        tiers = [[it["id"] for it in t["items"]] for t in data["tiers"]]
        self.assertEqual(tiers[0], [b["r2"], b["r3"], b["rx"]])  # chain order first, then uses
        self.assertEqual(tiers[1], [b["r8"], b["r4"]])  # same question; invalidated r7 left out
        self.assertEqual(tiers[2], [b["r6"], b["r5"]])  # two shared tokens rank above one shared tag
        self.assertNotIn(b["r9"], json.dumps(data))
        self.assertEqual([x["id"] for x in data["claims"]], [c])
        self.assertEqual([x["id"] for x in data["open_questions"]], [d["q"]])
        text = self.ok("brief", d["r"])
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("# Brief: %s  summary of facts" % d["r"]))
        line = lambda k: [l for l in lines if l.startswith(k)][0]
        self.assertIn("%s supported: m 0.9 > 0.5" % d["h"], line(b["r2"]))
        self.assertIn("pending: " + c, line(b["r2"]))
        self.assertIn("unreviewed", line(b["r3"]))
        self.assertIn("reviewed: nothing yet", line(b["r4"]))
        self.assertIn("interim", line(b["r8"]))
        self.assertIn("shares: villin", line(b["r5"]))
        self.assertIn("shares: facts, summary", line(b["r6"]))
        for h in ("## Directly linked", "## Same question (%s: Question?)" % d["q"], "## Possibly related, not linked",
                  "## Conclusions and leads on these results", "## Open questions"):
            self.assertIn(h, lines)

    def test_caps_and_all_and_determinism(self):
        d = self.d
        b = self.build()
        self.ok("config", "set", "brief_tier_limit", "1")
        self.ok("config", "set", "brief_related_limit", "1")
        text = self.ok("brief", d["r"])
        self.assertEqual(text, self.ok("brief", d["r"]))
        self.assertEqual(text.count("(+2 more: nb brief %s --all)" % d["r"]), 1)  # tier 2: r2 shown, r3 and rx not
        self.assertIn("(+1 more: nb brief %s --all)" % d["r"], text)
        everything = self.ok("brief", d["r"], "--all")
        self.assertNotIn("more:", everything)
        for k in ("r2", "r3", "rx", "r4", "r8", "r5", "r6"):
            self.assertIn(b[k], everything)

    def test_interim_and_invalidated_say_so(self):
        b = self.build()
        self.assertIn("interim", self.ok("brief", b["r8"]).splitlines()[0])
        self.assertIn("invalidated", self.ok("brief", b["r7"]).splitlines()[0])
        self.assertIn("verdict %s supported" % self.d["h"], self.ok("brief", b["r2"]))


class TestAuditBundle(SnapCase):
    def test_bundle_contents(self):
        d = self.d
        r2 = self.ok("result", d["e"], "uncited result")
        self.ok("deviate", d["e"], "ran 3 seeds not 5")
        h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + d["q"])
        c = self.concl(d["r"], "--link", "answers:" + d["q"], "--origin", "user", "--user-words", "it fails on villin",
                       author="claude", today="2026-10-29")
        other = self.concl(d["r"], title="Other reading")
        e2, _ = self.new_exp(h2, result=False)
        late = self.ok("result", e2, "later result under the same question", today="2026-10-30")
        old = self.ok("result", e2, "old", today="2026-10-01")
        b = json.loads(self.ok("audit", c, "--json"))
        self.assertEqual((b["node"]["id"], b["node"]["origin"], b["node"]["user_words"]), (c, "user", "it fails on villin"))
        self.assertEqual([r["id"] for r in b["cited_results"]], [d["r"]])
        self.assertEqual(b["cited_results"][0]["summary"], "summary of facts")
        self.assertIn("provenance", b["cited_results"][0])
        ex = b["experiments"][0]
        self.assertEqual(ex["id"], d["e"])
        self.assertEqual(ex["predictions"][0]["decision_rule"], "r")
        self.assertEqual(ex["deviations"][0]["text"], "ran 3 seeds not 5")
        self.assertEqual([r["id"] for r in b["uncited_results"]], [r2])
        self.assertEqual([r["id"] for r in b["results_since"]], [late])
        self.assertNotIn(old, json.dumps(b["results_since"]))
        self.assertIn(other, [x["id"] for x in b["other_claims"]])
        self.assertIn(d["r"], b["possibly_related"])
        text = self.ok("audit", c)
        self.assertTrue(text.startswith("# Audit bundle: " + c))
        self.assertIn("## Results it rests on", text)
        self.assertIn("frozen spec", text)
        lead = self.add("lead", "L", "--rationale", "r", "--from", d["r"])
        self.assertEqual(json.loads(self.ok("audit", lead, "--json"))["node"]["id"], lead)
        self.fails("audit", d["h"])


class TestClosingLint(SnapCase):
    def test_verdict_on_interim_or_foreign_result_is_error(self):
        d = self.d
        ri = self.ok("result", d["e"], "partial", "--interim")
        v = {"hypothesis": d["h"], "verdict": "supported", "result": ri, "basis": "b", "date": TODAY, "author": "user"}
        self.edit_ref(lambda n, m: n[d["e"]].setdefault("verdicts", []).append(v))
        self.assertEqual(self.assertLint("error", d["e"], "interim result"), 1)
        self.reset()
        e2, r2 = self.new_exp(d["h"])
        v = dict(v, result=r2)
        self.edit_ref(lambda n, m: n[d["e"]].setdefault("verdicts", []).append(v))
        self.assertLint("error", d["e"], "did not produce")

    def test_done_without_verdict_warns(self):
        d = self.d
        self.edit_ref(lambda n, m: n[d["e"]].update(status="done"))
        self.assertEqual(self.assertLint("warn", d["e"], "no current verdict"), 0)
        self.ok("verdict", d["r"], d["h"], "supported", "--basis", "b")  # backfill
        self.assertNoLint(d["e"], "no current verdict")

    def test_unreviewed_age(self):
        d = self.d
        self.assertNoLint(d["r"], "unreviewed", today="2026-11-04")
        self.assertLint("warn", d["r"], "unreviewed for 8 days", today="2026-11-05")
        self.ok("nothing-yet", d["r"])
        self.assertNoLint(d["r"], "unreviewed", today="2026-11-05")


class TestClosingPrime(SnapCase):
    def test_awaiting_shows_origin_and_audit(self):
        d = self.d
        c = self.concl(d["r"], "--origin", "user", "--user-words", "w", author="claude")
        self.audit(c)
        c2 = self.concl(d["r"], author="claude", title="Mine")
        s = sections(self.ok("prime"))
        aw = "\n".join(s["Awaiting the user (pending, not established)"])
        line = lambda k: [l for l in aw.splitlines() if l.startswith(k)][0]
        self.assertIn("from your read, audit sound", line(c))
        self.assertIn("Claude's read, not audited", line(c2))
        self.assertIn(d["r"], "\n".join(s["Needs closing"]))
        self.assertIn("pending: ", self.ok("show", d["r"]))

    def test_concerns_on_supported_conclusion_shown(self):
        d = self.d
        c = self.concl(d["r"], "--confidence", "low")
        self.audit(c, "concerns", "overclaims")
        self.assertIn("audit concerns", "\n".join(sections(self.ok("prime"))["Recent conclusions"]))

    def test_needs_closing_oldest_first(self):
        d = self.d
        r2 = self.ok("result", d["e"], "later", today="2026-10-30")
        lines = sections(self.ok("prime", today="2026-10-30"))["Needs closing"]
        ids = [l.split()[0] for l in lines]
        self.assertEqual(ids, [d["e"], d["r"], r2])
        self.assertIn("verdict missing", lines[0])


class TestClosingSync(NbCase):
    two_clones = TestSync.two_clones  # borrowed, not inherited, so TestSync's tests do not run twice

    def shared_experiment(self):
        """Both clones hold an experiment predicting h1 and h2, with result r."""
        B = self.two_clones()
        self.h1 = self.add("hypothesis", "H1", "--prediction", "p", "--link", "addresses:" + self.q)
        self.h2 = self.add("hypothesis", "H2", "--prediction", "p", "--link", "addresses:" + self.q)
        self.e = self.add("experiment", "E", "--spec", "S", "--exec", "command")
        self.predict(self.e, self.h1)
        self.predict(self.e, self.h2)
        self.ok("freeze", self.e)
        self.r = self.ok("result", self.e, "res")
        self.ok("sync")
        self.ok_in(B, "sync")
        return B

    def test_verdicts_and_reviews_merge(self):
        B = self.shared_experiment()
        self.ok("verdict", self.r, self.h1, "supported", "--basis", "a")
        self.ok("nothing-yet", self.r, "--note", "A")
        self.ok_in(B, "verdict", self.r, self.h2, "refuted", "--basis", "b")
        self.ok_in(B, "nothing-yet", self.r, "--note", "B")
        self.ok("sync")
        self.ok_in(B, "sync")
        self.ok("sync")
        for repo in (self.repo, B):
            e = json.loads(self.ok_in(repo, "show", self.e, "--json"))
            self.assertEqual(sorted(v["hypothesis"] for v in e["verdicts"]), sorted([self.h1, self.h2]))
            self.assertEqual(e["status"], "done")  # neither side was done; recomputed from the merged graph
            notes = [x["note"] for x in json.loads(self.ok_in(repo, "show", self.r, "--json"))["reviews"]]
            self.assertEqual(sorted(notes), ["A", "B"])
            self.assertEqual(json.loads(self.ok_in(repo, "show", self.h2, "--json"))["status"], "refuted")
        self.assertEqual([i for i in json.loads(self.ok_in(B, "lint", "--json")) if i["level"] == "error"], [])

    def test_same_hypothesis_verdict_conflict(self):
        B = self.shared_experiment()
        self.ok("verdict", self.r, self.h1, "supported", "--basis", "a")
        self.ok_in(B, "verdict", self.r, self.h1, "refuted", "--basis", "b")
        self.ok("sync")
        before = self.head(repo=B)
        rc, out, err = self.nb_in(B, "sync")
        self.assertEqual(rc, 1)
        self.assertIn("both sides added a verdict for " + self.h1, err)
        self.assertEqual(self.head(repo=B), before)

    def test_hypothesis_status_recomputed_not_conflicting(self):
        B = self.two_clones()
        h = self.add("hypothesis", "H", "--prediction", "p", "--link", "addresses:" + self.q)
        ea = self.add("experiment", "EA", "--spec", "S", "--exec", "command")
        eb = self.add("experiment", "EB", "--spec", "S", "--exec", "command")
        for e in (ea, eb):
            self.predict(e, h)
            self.ok("freeze", e)
        self.ok("sync")
        self.ok_in(B, "sync")
        self.ok("result", ea, "a", "--verdict", h, "supported", "a", today="2026-10-28")
        self.ok_in(B, "result", eb, "b", "--verdict", h, "refuted", "b", today="2026-10-29")
        self.ok("sync")
        self.ok_in(B, "sync", today="2026-10-29")
        self.ok("sync")
        for repo in (self.repo, B):
            self.assertEqual(json.loads(self.ok_in(repo, "show", h, "--json"))["status"], "refuted")

    def test_fixed_fields_cannot_differ(self):
        B = self.shared_experiment()
        self.edit_ref(lambda n, m: n[self.r].update(interim=True))
        self.edit_ref(lambda n, m: n[self.e].update(title=n[self.e]["title"]), repo=B)  # B moves on too
        self.edit_ref(lambda n, m: n[self.q].update(body="b side"), repo=B)
        self.edit_ref(lambda n, m: n[self.r].update(tags=["b"]), repo=B)
        self.ok("sync")
        rc, out, err = self.nb_in(B, "sync")
        self.assertEqual(rc, 1, out)
        self.assertIn("interim is fixed at creation", err)


GATE = HERE.parent / "hooks" / "gate.py"


class TestGate(NbCase):
    """hooks/gate.py: asks before gated nb verbs and CLAUDECODE overrides, silent otherwise."""

    def gate(self, command, tool="Bash"):
        payload = json.dumps({"tool_name": tool, "cwd": str(self.repo), "tool_input": {"command": command}})
        res = subprocess.run([sys.executable, "-I", str(GATE)], input=payload, env=self.env,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        if not res.stdout.strip():
            return None
        out = json.loads(res.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertEqual(out["permissionDecision"], "ask")
        return out["permissionDecisionReason"]

    def test_gated_verbs_ask(self):
        for cmd in ["nb freeze exp-abcd", "nb confirm con-abcd", "nb invalidate res-abcd --reason r",
                    "nb config set drift_leads 3", "cd sub && nb confirm con-abcd",
                    "nb retract res-abcd supports hyp-abcd --reason r",
                    "ls; nb freeze exp-abcd", "/opt/x/bin/nb freeze exp-abcd",
                    "python3 plugins/lab-notebook/bin/nb confirm con-abcd", "echo y | nb freeze exp-abcd"]:
            self.assertIsNotNone(self.gate(cmd), cmd)

    def test_other_commands_pass(self):
        for cmd in ["nb add goal x", "nb config get", "nb show exp-abcd", "nb status exp-abcd done",
                    "git status", "jupyter nbconvert x.ipynb", "ls nbfreeze"]:
            self.assertIsNone(self.gate(cmd), cmd)
        self.assertIsNone(self.gate("nb freeze exp-abcd", tool="Edit"))

    def test_claudecode_override_asks(self):
        for cmd in ["env -u CLAUDECODE nb add goal x", "CLAUDECODE= nb add goal x", "unset CLAUDECODE; nb add goal x",
                    "env -i PATH=/usr/bin nb add goal x"]:
            self.assertIn("CLAUDECODE", self.gate(cmd) or "", cmd)

    def test_reason_describes_the_node(self):
        self.init()
        g = self.add("goal", "G")
        q = self.add("question", "Q", "--link", "refines:" + g)
        h = self.add("hypothesis", "H", "--prediction", "p", "--link", "addresses:" + q)
        e = self.add("experiment", "Steering baseline", "--spec", "s", "--exec", "command", "--retro")
        self.ok("predict", e, h, "--prediction", "enrichment > 5", "--metric", "m", "--rule", "supported if > 5")
        reason = self.gate("nb freeze %s" % e[:6])
        self.assertIn("Steering baseline", reason)
        self.assertIn("supported if > 5", reason)
        self.assertIn("retrospective", reason)
        self.assertIn("nb freeze", self.gate("nb freeze exp-zzzz"))  # unknown id: still asks, no description


def main():
    """Run the TestCase classes in parallel threads (the tests are subprocess-bound); classes are independent."""
    import io
    from concurrent.futures import ThreadPoolExecutor
    loader = unittest.defaultTestLoader
    classes = [c for c in globals().values() if isinstance(c, type) and issubclass(c, unittest.TestCase)
               and c not in (NbCase, SnapCase)]
    classes.sort(key=lambda c: c is not TestFixture)  # slowest first

    def run(cls):
        stream = io.StringIO()
        res = unittest.TextTestRunner(stream=stream, verbosity=0).run(loader.loadTestsFromTestCase(cls))
        return res, stream.getvalue()

    total = failed = 0
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
        for res, text in ex.map(run, classes):
            total += res.testsRun
            if not res.wasSuccessful():
                failed += len(res.failures) + len(res.errors)
                print(text)
    print("Ran %d tests, %d failed" % (total, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        unittest.main(verbosity=1)  # e.g. test_nb.py TestLint.test_cycles: sequential, normal unittest CLI
    else:
        main()
