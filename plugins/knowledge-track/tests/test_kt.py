#!/usr/bin/env python3
"""Test suite for the `kt` CLI. Run: python3 plugins/knowledge-track/tests/test_kt.py"""

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
KT = HERE.parent / "bin" / "kt"
FIXTURES = HERE / "fixtures"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"
TODAY = "2026-10-26"

_NS = {"__name__": "kt_under_test"}
exec(compile(KT.read_text(), str(KT), "exec"), _NS)
parse_frontmatter = _NS["parse_frontmatter"]
serialize_frontmatter = _NS["serialize_frontmatter"]

_HOME = tempfile.mkdtemp(prefix="kt-home-")
atexit.register(shutil.rmtree, _HOME, True)


def run_kt(*args, cwd=None, env_extra=None, stdin=None):
    """Run kt; env_extra must carry KNOWLEDGE_TRACK_DIR. Returns (rc, stdout, stderr)."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("GIT_") or k == "KNOWLEDGE_TRACK_DIR":
            del env[k]
    env.update({"HOME": _HOME, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "KNOWLEDGE_TRACK_TODAY": TODAY})
    env.update(env_extra or {})
    res = subprocess.run([sys.executable, str(KT)] + list(args), cwd=cwd, env=env,
                         input=stdin, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


class KtCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="kt-test-")
        self.addCleanup(self._td.cleanup)
        self.kb = Path(self._td.name) / "kb"

    # -- helpers
    def kt(self, *args, env_extra=None, **kw):
        extra = {"KNOWLEDGE_TRACK_DIR": str(self.kb)}
        extra.update(env_extra or {})
        return run_kt(*args, env_extra=extra, **kw)

    def ok(self, *args, **kw):
        rc, out, err = self.kt(*args, **kw)
        self.assertEqual(rc, 0, "kt %s failed\nstdout: %s\nstderr: %s" % (" ".join(args), out, err))
        return out

    def copy_valid(self, init=False):
        shutil.copytree(VALID, self.kb)
        if init:
            # fixture config has auto_commit false; enable it for tests that check commits
            (self.kb / "config.json").write_text('{"auto_commit": true, "auto_sync": false}\n')
            self.ok("init")
        return self.kb

    def git(self, *args):
        res = subprocess.run(["git", "-C", str(self.kb)] + list(args), capture_output=True, text=True,
                             env=dict(os.environ, HOME=_HOME, GIT_CONFIG_GLOBAL=os.devnull,
                                      GIT_CONFIG_NOSYSTEM="1"))
        return res

    def commits(self):
        res = self.git("log", "--format=%s")
        return res.stdout.split("\n")[:-1] if res.returncode == 0 else []

    def read(self, cid):
        return parse_frontmatter((self.kb / "concepts" / (cid + ".md")).read_text())

    def ids_json(self, *args):
        return [r["id"] for r in json.loads(self.ok(*args, "--json"))]


class ParserTests(unittest.TestCase):
    def test_round_trip_every_valid_fixture(self):
        files = sorted((VALID / "concepts").glob("*.md"))
        self.assertGreaterEqual(len(files), 8)
        for f in files:
            with self.subTest(f.name):
                raw = f.read_bytes().decode()
                fm, body = parse_frontmatter(raw)
                self.assertEqual(serialize_frontmatter(fm, body).encode(), f.read_bytes())

    def test_inline_comment_stripped_from_unquoted_scalar(self):
        fm, _ = parse_frontmatter("---\nid: foo # a comment\nkind: concept   # another\n---\n")
        self.assertEqual(fm["id"], "foo")
        self.assertEqual(fm["kind"], "concept")

    def test_quoted_scalar_with_colon_space(self):
        fm, _ = parse_frontmatter('---\ntitle: "A: B and C"\n---\n')
        self.assertEqual(fm["title"], "A: B and C")

    def test_flow_list_with_quoted_comma_item(self):
        fm, _ = parse_frontmatter('---\naliases: [a, "b, c", d]\n---\n')
        self.assertEqual(fm["aliases"], ["a", "b, c", "d"])

    def test_block_list(self):
        fm, _ = parse_frontmatter('---\nevidence:\n  - "x: y"\n  - plain\nid: z\n---\n')
        self.assertEqual(fm["evidence"], ["x: y", "plain"])
        self.assertEqual(fm["id"], "z")

    def test_empty_list_key_is_empty_list(self):
        fm, _ = parse_frontmatter("---\nrequires:\nid: z\n---\n")
        self.assertEqual(fm["requires"], [])
        fm, _ = parse_frontmatter("---\nid: z\ntags:\n---\n")
        self.assertEqual(fm["tags"], [])


def _make_invalid_test(case, needles):
    def test(self):
        shutil.copytree(INVALID / case, self.kb)
        rc, out, err = self.kt("lint")
        self.assertEqual(rc, 1, out + err)
        for n in needles:
            self.assertIn(n, out + err, "%s: expected %r in output:\n%s" % (case, n, out + err))
    return test


INVALID_EXPECT = {
    "cycle-requires": ["requires cycle"],
    "cycle-part-of": ["part-of cycle"],
    "dangling-ref": ["unknown id"],
    "bad-evidence-format": ["must match"],
    "old-evidence-kind": ["explained:", "must match"],
    "level-without-evidence": ["requires at least one evidence"],
    "id-mismatch": ["does not equal filename"],
    "unknown-key": ["unknown key"],
    "nested-yaml": ["nest"],
    "multiline-scalar": ["multi-line"],
    "conflict-markers": ["conflict marker"],
    "last-evidenced-wrong": ["must equal the newest"],
    "self-reference": ["must not reference itself"],
    "bad-kind": ["must be one of"],
    "bad-level": ["must be an integer"],
}


class InvalidFixtureTests(KtCase):
    def test_every_invalid_fixture_directory_is_covered(self):
        self.assertEqual(sorted(p.name for p in INVALID.iterdir() if p.is_dir()), sorted(INVALID_EXPECT))


for _case, _needles in INVALID_EXPECT.items():
    setattr(InvalidFixtureTests, "test_lint_rejects_" + _case.replace("-", "_"),
            _make_invalid_test(_case, _needles))


class ValidFixtureTests(KtCase):
    def test_lint_passes(self):
        shutil.copytree(VALID, self.kb)
        rc, out, err = self.kt("lint")
        self.assertEqual(rc, 0, out + err)

    def test_lint_json_zero_errors_and_two_deliberate_warnings(self):
        shutil.copytree(VALID, self.kb)
        rc, out, _ = self.kt("lint", "--json")
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["errors"], [])
        self.assertEqual({w["id"] for w in data["warnings"]}, {"rust-ownership", "burned-area-mapping"})


class InitTests(KtCase):
    def test_init_creates_layout_and_one_commit_and_rerun_is_noop(self):
        self.ok("init")
        for name in ("concepts", "config.json", "README.md", ".gitignore", ".git"):
            self.assertTrue((self.kb / name).exists(), name)
        self.assertEqual(self.commits(), ["kt: init"])
        self.assertEqual(self.git("log", "-1", "--format=%an").stdout.strip(), "kt")
        out = self.ok("init")
        self.assertIn("already initialised", out)
        self.assertEqual(self.commits(), ["kt: init"])


class AddTests(KtCase):
    def test_add_writes_commits_and_indexes(self):
        self.copy_valid(init=True)
        self.ok("add", "ownership-lifetimes", "--title", "Lifetimes", "--kind", "concept", "--level", "0",
                "--requires", "message-passing", "--part-of", "graph-neural-networks", "--body", "x")
        self.assertTrue((self.kb / "concepts" / "ownership-lifetimes.md").exists())
        self.assertEqual(self.commits()[0], "kt: add ownership-lifetimes")
        idx = {r["id"]: r for r in json.loads((self.kb / "index.json").read_text())}
        self.assertIn("ownership-lifetimes", idx)
        self.assertEqual(idx["graph-neural-networks"]["has_part"],
                         ["message-passing", "over-smoothing", "ownership-lifetimes"])
        self.assertTrue(idx["graph-neural-networks"]["is_group"])
        self.assertFalse(idx["graph-basics"]["is_group"])
        self.assertEqual(idx["graph-basics"]["required_by"],
                         ["graph-neural-networks", "label-propagation", "message-passing"])
        self.assertIn("ownership-lifetimes", idx["message-passing"]["required_by"])

    def test_add_with_dangling_requires_is_refused(self):
        self.copy_valid(init=True)
        before = self.commits()
        rc, out, err = self.kt("add", "newone", "--title", "N", "--kind", "concept", "--level", "0",
                               "--requires", "ghost")
        self.assertEqual(rc, 1)
        self.assertFalse((self.kb / "concepts" / "newone.md").exists())
        self.assertEqual(self.commits(), before)

    def test_add_mirrors_symmetric_relation(self):
        self.copy_valid(init=True)
        self.ok("add", "newone", "--title", "N", "--kind", "concept", "--level", "0",
                "--related", "rust-ownership")
        self.assertIn("newone", self.read("rust-ownership")[0]["related"])

    def test_add_needs_no_network_and_git_identity(self):
        self.copy_valid(init=True)
        env = {"GIT_PROXY_COMMAND": "false", "GIT_SSH_COMMAND": "false"}
        self.ok("add", "newone", "--title", "N", "--kind", "concept", "--level", "0", env_extra=env)
        self.assertEqual(self.commits()[0], "kt: add newone")

    def test_auto_commit_false_writes_file_without_commit(self):
        self.copy_valid()
        self.ok("init")  # fixture config.json has auto_commit false
        self.ok("add", "newone", "--title", "N", "--kind", "concept", "--level", "0")
        self.assertTrue((self.kb / "concepts" / "newone.md").exists())
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD").returncode, 0)


class EvidenceTests(KtCase):
    def test_explained_kind_rejected(self):
        self.copy_valid(init=True)
        rc, _, err = self.kt("add-evidence", "over-smoothing", "2026-10-01 explained: said it")
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.read("over-smoothing")[0]["evidence"]), 1)

    def test_exposed_and_explained_back_accepted_and_last_evidenced_is_max(self):
        self.copy_valid(init=True)
        # older than the existing 2026-09-20: last_evidenced must not move
        self.ok("add-evidence", "over-smoothing", "2026-01-05 exposed: lecture slide")
        fm, _ = self.read("over-smoothing")
        self.assertEqual(fm["last_evidenced"], "2026-09-20")
        self.assertEqual(fm["level"], 1)
        self.ok("add-evidence", "over-smoothing", "2026-10-01 explained-back: own words", "--level", "2")
        fm, _ = self.read("over-smoothing")
        self.assertEqual(fm["last_evidenced"], "2026-10-01")
        self.assertEqual(fm["level"], 2)
        self.assertEqual(len(fm["evidence"]), 3)
        self.assertEqual(self.commits()[0], "kt: add-evidence over-smoothing")


class LinkTests(KtCase):
    def test_link_related_both_sides_and_unlink(self):
        self.copy_valid(init=True)
        self.ok("link", "rust-ownership", "related", "burned-area-mapping")
        self.assertEqual(self.read("rust-ownership")[0]["related"], ["burned-area-mapping"])
        self.assertEqual(self.read("burned-area-mapping")[0]["related"], ["rust-ownership"])
        self.ok("unlink", "rust-ownership", "related", "burned-area-mapping")
        self.assertNotIn("related", self.read("rust-ownership")[0])
        self.assertNotIn("related", self.read("burned-area-mapping")[0])

    def test_link_contrasts_with_both_sides(self):
        self.copy_valid(init=True)
        self.ok("link", "rust-ownership", "contrasts-with", "burned-area-mapping")
        self.assertEqual(self.read("burned-area-mapping")[0]["contrasts-with"], ["rust-ownership"])

    def test_requires_cycle_refused(self):
        self.copy_valid(init=True)
        self.ok("link", "rust-ownership", "requires", "burned-area-mapping")
        before = self.commits()
        rc, out, err = self.kt("link", "burned-area-mapping", "requires", "rust-ownership")
        self.assertEqual(rc, 1)
        self.assertIn("cycle", err)
        self.assertNotIn("requires", self.read("burned-area-mapping")[0])
        self.assertEqual(self.commits(), before)


class RenameRmTests(KtCase):
    def test_rename_rewrites_all_reference_kinds(self):
        self.copy_valid(init=True)
        self.ok("rename", "message-passing", "neighbour-aggregation")
        self.assertFalse((self.kb / "concepts" / "message-passing.md").exists())
        self.assertEqual(self.read("neighbour-aggregation")[0]["id"], "neighbour-aggregation")
        self.assertEqual(self.read("over-smoothing")[0]["requires"], ["neighbour-aggregation"])
        self.assertEqual(self.read("attention-mechanism")[0]["related"], ["neighbour-aggregation"])
        self.assertEqual(self.read("label-propagation")[0]["contrasts-with"], ["neighbour-aggregation"])
        self.ok("rename", "graph-neural-networks", "gnn-theory")
        self.assertEqual(self.read("over-smoothing")[0]["part-of"], ["gnn-theory"])
        self.assertEqual(self.read("neighbour-aggregation")[0]["part-of"], ["gnn-theory"])
        self.ok("lint")
        text = "".join(p.read_text() for p in (self.kb / "concepts").glob("*.md"))
        self.assertNotIn("message-passing", text)
        self.assertNotIn("graph-neural-networks", text)

    def test_rm_refuses_when_referenced_then_force_removes(self):
        self.copy_valid(init=True)
        rc, _, err = self.kt("rm", "message-passing")
        self.assertEqual(rc, 1)
        self.assertIn("referenced", err)
        self.assertTrue((self.kb / "concepts" / "message-passing.md").exists())
        self.ok("rm", "message-passing", "--force")
        self.assertFalse((self.kb / "concepts" / "message-passing.md").exists())
        for p in (self.kb / "concepts").glob("*.md"):
            self.assertNotIn("message-passing", p.read_text())
        self.ok("lint")


class QueryTests(KtCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(VALID, self.kb)

    def test_gaps_transitive_below_threshold(self):
        self.assertEqual(self.ids_json("gaps", "over-smoothing", "--threshold", "4"),
                         ["message-passing", "graph-basics"])
        self.assertEqual(self.ids_json("gaps", "protein-structure-prediction"), ["attention-mechanism"])
        self.assertEqual(self.ids_json("gaps", "over-smoothing"), [])

    def test_fringe(self):
        self.assertEqual(self.ids_json("fringe"),
                         ["attention-mechanism", "burned-area-mapping", "graph-neural-networks",
                          "label-propagation", "over-smoothing"])

    def test_check_alias_case_insensitive(self):
        r = json.loads(self.ok("check", "Neighbourhood Aggregation", "mpnn", "--json"))
        for item in r:
            self.assertEqual(item["id"], "message-passing")
            self.assertEqual(item["matched_by"], "alias")
            self.assertTrue(item["known"])
            self.assertEqual(item["level"], 3)

    def test_check_unknown_term(self):
        r = json.loads(self.ok("check", "quantum gravity", "--json"))[0]
        self.assertFalse(r["known"])
        self.assertEqual(r["level"], 0)
        self.assertIsNone(r["id"])

    def test_check_resolve_fuzzy_misspelling(self):
        r = json.loads(self.ok("check", "Mesage pasing", "--resolve", "--json"))[0]
        self.assertEqual(r["id"], "message-passing")
        self.assertEqual(r["matched_by"], "fuzzy")
        r = json.loads(self.ok("check", "Mesage pasing", "--json"))[0]
        self.assertIsNone(r["id"])

    def test_query_filters(self):
        self.assertEqual(self.ids_json("query", "--level", "<3"),
                         ["attention-mechanism", "burned-area-mapping", "graph-neural-networks",
                          "label-propagation", "over-smoothing", "protein-structure-prediction"])
        self.assertEqual(self.ids_json("query", "--kind", "method"),
                         ["burned-area-mapping", "label-propagation", "protein-structure-prediction"])
        self.assertEqual(self.ids_json("query", "--tag", "gnn"),
                         ["graph-neural-networks", "message-passing", "over-smoothing"])
        self.assertEqual(self.ids_json("query", "--requires-of", "over-smoothing"), ["message-passing"])
        self.assertEqual(self.ids_json("query", "--required-by", "graph-basics"),
                         ["graph-neural-networks", "label-propagation", "message-passing"])
        self.assertEqual(self.ids_json("query", "--part-of", "graph-neural-networks"),
                         ["message-passing", "over-smoothing"])

    def test_query_unresolved(self):
        self.assertEqual(self.ids_json("query", "--unresolved"), [])
        p = self.kb / "concepts" / "label-propagation.md"
        p.write_text(p.read_text().replace("requires: [graph-basics]", "requires: [graph-basics, ghost]"))
        self.assertEqual(self.ids_json("query", "--unresolved"), ["label-propagation"])

    def test_graph_json_edges(self):
        g = json.loads(self.ok("graph", "--json"))
        got = {(e["from"], e["relation"], e["to"]) for e in g["edges"]}
        expect = {
            ("graph-basics", "requires", "linear-algebra-basics"),
            ("graph-neural-networks", "requires", "graph-basics"),
            ("message-passing", "requires", "graph-basics"),
            ("over-smoothing", "requires", "message-passing"),
            ("attention-mechanism", "requires", "linear-algebra-basics"),
            ("label-propagation", "requires", "graph-basics"),
            ("protein-structure-prediction", "requires", "attention-mechanism"),
            ("message-passing", "part-of", "graph-neural-networks"),
            ("over-smoothing", "part-of", "graph-neural-networks"),
        }
        self.assertEqual(got, expect)
        self.assertEqual(len(g["edges"]), len(expect))
        self.assertEqual(len(g["nodes"]), 10)

    def test_graph_mermaid_and_dot(self):
        self.assertTrue(self.ok("graph", "--mermaid").startswith("graph BT"))
        self.assertTrue(self.ok("graph", "--dot").startswith("digraph"))


class SetTests(KtCase):
    def test_set_list_body_and_refusals(self):
        self.copy_valid(init=True)
        self.ok("set", "rust-ownership", "tags=a,b", "body=New definition")
        fm, body = self.read("rust-ownership")
        self.assertEqual(fm["tags"], ["a", "b"])
        self.assertEqual(body.strip(), "New definition")
        self.assertIn("tags: [a, b]", (self.kb / "concepts" / "rust-ownership.md").read_text())
        for bad in ("id=other", "created=2026-01-01"):
            rc, _, err = self.kt("set", "rust-ownership", bad)
            self.assertEqual(rc, 1, bad)
            self.assertIn("maintained by kt", err)

    def test_set_evidence_replaces_whole_list(self):
        self.copy_valid(init=True)
        self.ok("set", "over-smoothing", "evidence=2026-10-02 quiz: a", "evidence=2026-10-03 taught: b")
        fm, _ = self.read("over-smoothing")
        self.assertEqual(fm["evidence"], ["2026-10-02 quiz: a", "2026-10-03 taught: b"])
        self.assertEqual(fm["last_evidenced"], "2026-10-03")


class StatusTests(KtCase):
    def test_status_json(self):
        self.copy_valid(init=True)
        s = json.loads(self.ok("status", "--json"))
        self.assertEqual(s["concepts"], 10)
        self.assertEqual(s["by_level"], {"0": 1, "1": 2, "2": 3, "3": 3, "4": 0, "5": 1})
        self.assertTrue(s["git"]["branch"])


class ConflictTests(KtCase):
    def test_conflict_markers_block_lint_and_writes(self):
        self.copy_valid()
        p = self.kb / "concepts" / "graph-basics.md"
        p.write_text(p.read_text() + "<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> origin/main\n")
        rc, out, err = self.kt("lint")
        self.assertEqual(rc, 1)
        self.assertIn("conflict marker", out)
        rc, out, err = self.kt("add", "newone", "--title", "N", "--kind", "concept", "--level", "0")
        self.assertEqual(rc, 1)
        self.assertIn("refused", err)
        self.assertFalse((self.kb / "concepts" / "newone.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
