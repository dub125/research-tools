#!/usr/bin/env python3
"""Test suite for the `kt` CLI. Run: python3 plugins/knowledge-track/tests/test_kt.py"""

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
TODAY = "2026-10-26"

SEED = [
    {"id": "graph-basics", "name": "Graph basics", "summary": "s-graph-basics", "level": 3, "note": "uses networkx daily", "updated": "2026-01-01"},
    {"id": "message-passing", "name": "Message passing", "summary": "s-message-passing", "level": 2, "aliases": ["MPNN"], "tags": ["gnn"],
     "requires": ["graph-basics"], "note": "explained the update rule", "updated": "2026-01-01"},
    {"id": "over-smoothing", "name": "Over-smoothing", "summary": "s-over-smoothing", "level": 0, "tags": ["gnn"],
     "requires": ["message-passing", "spectral-graph-theory"], "updated": "2026-01-01"},
    {"id": "spectral-graph-theory", "name": "Spectral graph theory", "summary": "s-spectral-graph-theory", "level": 1,
     "requires": ["graph-basics"], "note": "heard of it in a talk", "updated": "2026-01-01"},
]


class KtCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="kt-test-")
        self.addCleanup(self._td.cleanup)
        self.kb = Path(self._td.name) / "kb"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update({"HOME": self._td.name, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                         "KNOWLEDGE_TRACK_DIR": str(self.kb), "KNOWLEDGE_TRACK_TODAY": TODAY})

    def kt(self, *args):
        res = subprocess.run([sys.executable, str(KT)] + list(args), env=self.env, capture_output=True, text=True)
        return res.returncode, res.stdout, res.stderr

    def ok(self, *args):
        rc, out, err = self.kt(*args)
        self.assertEqual(rc, 0, "kt %s failed\nstdout: %s\nstderr: %s" % (" ".join(args), out, err))
        return out

    def fails(self, *args):
        rc, out, err = self.kt(*args)
        self.assertNotEqual(rc, 0, "kt %s should fail\nstdout: %s" % (" ".join(args), out))
        return err

    def seed(self, records=SEED):
        self.ok("init")
        self.write(records)

    def write(self, records):
        (self.kb / "concepts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    def records(self):
        return [json.loads(l) for l in (self.kb / "concepts.jsonl").read_text().splitlines()]

    def commits(self):
        out = subprocess.run(["git", "-C", str(self.kb), "log", "--format=%s"], env=self.env,
                             capture_output=True, text=True).stdout
        return out.splitlines()


class TestInit(KtCase):
    def test_init_creates_repo_and_is_idempotent(self):
        self.ok("init")
        self.assertTrue((self.kb / "concepts.jsonl").exists())
        self.assertTrue((self.kb / ".git").exists())
        self.assertEqual(self.commits(), ["kt: init"])
        self.ok("init")
        self.assertEqual(self.commits(), ["kt: init"])

    def test_commands_without_init_fail_cleanly(self):
        self.assertIn("kt init", self.fails("list"))


class TestSet(KtCase):
    def setUp(self):
        super().setUp()
        self.ok("init")

    def test_create_writes_sorted_compact_line_and_commits(self):
        self.ok("set", "zeta", "--summary", "s", "--level", "0")
        self.ok("set", "alpha-beta", "--summary", "s", "--level", "1", "--note", "saw it", "--tag", "x,y")
        recs = self.records()
        self.assertEqual([r["id"] for r in recs], ["alpha-beta", "zeta"])
        self.assertEqual(recs[0], {"id": "alpha-beta", "name": "alpha beta", "summary": "s", "level": 1, "tags": ["x", "y"],
                                   "note": "saw it", "updated": TODAY})
        self.assertNotIn("aliases", recs[1])
        self.assertEqual(self.commits()[0], "kt: add alpha-beta")

    def test_new_concept_needs_summary(self):
        self.assertIn("--summary", self.fails("set", "x", "--level", "0"))
        self.assertIn("--summary", self.fails("set", "x", "--level", "0", "--summary", "  "))
        self.assertFalse(self.records())

    def test_summary_sets_and_updates(self):
        self.ok("set", "a", "--summary", "first", "--level", "0")
        self.assertEqual(self.records()[0]["summary"], "first")
        self.assertEqual(list(self.records()[0])[:3], ["id", "name", "summary"])
        self.ok("set", "a", "--summary", "second")
        self.assertEqual(self.records()[0]["summary"], "second")

    def test_new_concept_needs_level(self):
        self.assertIn("--level", self.fails("set", "x"))

    def test_level_above_zero_needs_note(self):
        self.assertIn("note", self.fails("set", "x", "--summary", "s", "--level", "2"))
        self.assertFalse(self.records())

    def test_level_out_of_range_rejected(self):
        self.fails("set", "x", "--summary", "s", "--level", "4", "--note", "n")

    def test_bad_id_rejected(self):
        self.fails("set", "Bad_Id", "--summary", "s", "--level", "0")

    def test_update_appends_lists_and_clear_replaces(self):
        self.ok("set", "a", "--summary", "s", "--level", "0", "--tag", "x")
        self.ok("set", "a", "--tag", "y", "--tag", "x")
        self.assertEqual(self.records()[0]["tags"], ["x", "y"])
        self.ok("set", "a", "--clear", "tags", "--tag", "z")
        self.assertEqual(self.records()[0]["tags"], ["z"])
        self.assertEqual(self.commits()[0], "kt: set a")

    def test_requires_must_resolve_and_be_acyclic(self):
        self.ok("set", "a", "--summary", "s", "--level", "0")
        self.assertIn("unknown id", self.fails("set", "a", "--requires", "nope"))
        self.ok("set", "b", "--summary", "s", "--level", "0", "--requires", "a")
        self.assertIn("cycle", self.fails("set", "a", "--requires", "b"))
        self.assertIn("itself", self.fails("set", "a", "--requires", "a"))

    def test_part_of_validation(self):
        self.ok("set", "a", "--summary", "s", "--level", "0")
        self.ok("set", "b", "--summary", "s", "--level", "0")
        self.assertIn("unknown id", self.fails("set", "a", "--part-of", "nope"))
        self.assertIn("itself", self.fails("set", "a", "--part-of", "a"))
        self.ok("set", "a", "--part-of", "b")
        self.assertEqual(self.records()[0]["part-of"], ["b"])
        self.assertIn("part-of cycle", self.fails("set", "b", "--part-of", "a"))
        self.assertIn("both requires and part-of", self.fails("set", "a", "--requires", "b"))

    def test_clear_part_of(self):
        self.ok("set", "a", "--summary", "s", "--level", "0")
        self.ok("set", "b", "--summary", "s", "--level", "0", "--part-of", "a")
        self.assertEqual(self.records()[1]["part-of"], ["a"])
        self.ok("set", "b", "--clear", "part-of")
        self.assertNotIn("part-of", self.records()[1])

    def test_similar_concept_blocks_create_unless_new(self):
        self.ok("set", "message-passing", "--summary", "s", "--level", "0", "--alias", "MPNN")
        err = self.fails("set", "message-passing-layer", "--summary", "s", "--level", "0")
        self.assertIn("message-passing", err)
        self.assertIn("--alias", err)
        self.fails("set", "mpnn", "--summary", "s", "--level", "0")
        self.ok("set", "message-passing-layer", "--summary", "s", "--level", "0", "--new")

    def test_alias_collision_is_an_error(self):
        self.ok("set", "a", "--summary", "s", "--level", "0", "--alias", "foo")
        self.ok("set", "bbb", "--summary", "s", "--level", "0", "--new")
        self.assertIn("already belongs", self.fails("set", "bbb", "--alias", "Foo"))


class TestRead(KtCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_check_exact_alias_and_candidates(self):
        out = json.loads(self.ok("check", "message-passing", "mpnn", "Spectral Graph Theory", "oversmoothing",
                                 "quantum chromodynamics", "--json"))
        self.assertEqual([r["matched_by"] for r in out[:3]], ["id", "alias", "id"])
        self.assertEqual(out[1]["id"], "message-passing")
        self.ok("set", "gcn", "--summary", "s", "--name", "Graph convolutional network", "--level", "0")
        self.assertEqual(json.loads(self.ok("check", "graph convolutional network", "--json"))[0]["matched_by"], "name")
        self.assertIsNone(out[3]["id"])
        self.assertEqual(out[3]["candidates"][0]["id"], "over-smoothing")
        self.assertEqual(out[4], {"term": "quantum chromodynamics", "id": None, "level": 0, "candidates": []})

    def test_check_text_is_one_line_per_term(self):
        out = self.ok("check", "mpnn", "nothing-like-it")
        self.assertEqual(len(out.splitlines()), 2)
        self.assertIn("-> message-passing (alias)", out)

    def test_get_includes_dependents_and_gaps(self):
        out = json.loads(self.ok("get", "over-smoothing", "--json"))
        self.assertEqual(out["gaps"], ["spectral-graph-theory"])
        self.assertEqual(json.loads(self.ok("get", "graph-basics", "--json"))["required_by"],
                         ["message-passing", "spectral-graph-theory"])

    def test_get_shows_parts(self):
        self.ok("set", "readout", "--summary", "s", "--level", "0", "--part-of", "graph-basics")
        out = json.loads(self.ok("get", "graph-basics", "--json"))
        self.assertEqual(out["parts"], ["readout"])
        self.assertIn("parts", self.ok("get", "graph-basics"))
        self.assertEqual(json.loads(self.ok("get", "readout", "--json"))["part-of"], ["graph-basics"])

    def test_gaps_ignores_part_of(self):
        self.ok("set", "readout", "--summary", "s", "--level", "0", "--part-of", "over-smoothing")
        self.assertEqual(json.loads(self.ok("gaps", "readout", "--json")), [])
        self.assertEqual(json.loads(self.ok("get", "readout", "--json"))["gaps"], [])

    def test_gaps_threshold(self):
        self.assertEqual([r["id"] for r in json.loads(self.ok("gaps", "over-smoothing", "--threshold", "3", "--json"))],
                         ["message-passing", "spectral-graph-theory"])

    def test_list_filters_and_limit(self):
        ids = [r["id"] for r in json.loads(self.ok("list", "--level", "<2", "--json"))]
        self.assertEqual(ids, ["over-smoothing", "spectral-graph-theory"])
        ids = [r["id"] for r in json.loads(self.ok("list", "--tag", "gnn", "--level", ">=1", "--json"))]
        self.assertEqual(ids, ["message-passing"])
        self.write([{"id": "c%03d" % i, "name": "concept %d" % i, "summary": "s", "level": 0, "updated": TODAY} for i in range(60)])
        out = self.ok("list")
        self.assertIn("10 more", out)
        self.assertEqual(len(json.loads(self.ok("list", "--all", "--json"))), 60)

    def test_dupes(self):
        self.ok("set", "message-passing-layers", "--summary", "s", "--level", "0", "--new")
        out = json.loads(self.ok("dupes", "--json"))
        self.assertEqual((out[0]["a"], out[0]["b"]), ("message-passing", "message-passing-layers"))


class TestMergeRm(KtCase):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_merge_folds_names_and_rewrites_links(self):
        self.ok("set", "neighbourhood-aggregation", "--summary", "s", "--level", "3", "--note", "built one", "--tag", "ml",
                "--requires", "graph-basics")
        self.ok("set", "readout", "--summary", "s", "--level", "0", "--requires", "neighbourhood-aggregation")
        self.ok("merge", "neighbourhood-aggregation", "message-passing")
        recs = {r["id"]: r for r in self.records()}
        self.assertNotIn("neighbourhood-aggregation", recs)
        mp = recs["message-passing"]
        self.assertEqual(mp["aliases"], ["MPNN", "neighbourhood aggregation"])
        self.assertEqual((mp["level"], mp["note"]), (3, "built one"))
        self.assertEqual(mp["tags"], ["gnn", "ml"])
        self.assertEqual(mp["requires"], ["graph-basics"])
        self.assertEqual(recs["readout"]["requires"], ["message-passing"])
        self.assertEqual(self.ok("check", "neighbourhood aggregation", "--json").count('"alias"'), 1)

    def test_merge_rewrites_part_of(self):
        self.ok("set", "aggregation", "--summary", "s", "--level", "0", "--part-of", "over-smoothing")
        self.ok("set", "sum-op", "--summary", "s", "--level", "0", "--part-of", "aggregation")
        self.ok("merge", "aggregation", "message-passing")
        recs = {r["id"]: r for r in self.records()}
        self.assertEqual(recs["message-passing"]["part-of"], ["over-smoothing"])
        self.assertEqual(recs["sum-op"]["part-of"], ["message-passing"])

    def test_rm_with_part_of_dependents_matches_requires(self):
        self.ok("set", "readout", "--summary", "s", "--level", "0", "--part-of", "message-passing")
        self.assertIn("a part of readout", self.fails("rm", "message-passing"))
        self.ok("rm", "message-passing", "--force")
        recs = {r["id"]: r for r in self.records()}
        self.assertNotIn("part-of", recs["readout"])
        self.assertEqual(recs["readout"]["updated"], TODAY)

    def test_merge_refuses_cycle(self):
        self.assertIn("cycle", self.fails("merge", "graph-basics", "over-smoothing"))

    def test_rm_refuses_when_required_unless_force(self):
        self.assertIn("required by", self.fails("rm", "graph-basics"))
        self.ok("rm", "spectral-graph-theory", "--force")
        recs = {r["id"]: r for r in self.records()}
        self.assertEqual(recs["over-smoothing"]["requires"], ["message-passing"])


class TestValidate(KtCase):
    def setUp(self):
        super().setUp()
        self.ok("init")

    def bad(self, records, needle):
        self.write(records)
        rc, out, _ = self.kt("validate")
        self.assertEqual(rc, 1)
        self.assertIn(needle, out)

    def test_valid_seed(self):
        self.write(SEED)
        self.assertEqual(self.ok("validate").strip(), "ok")

    def test_unknown_field(self):
        self.bad([dict(SEED[0], kind="concept")], "unknown field")

    def test_wrong_types(self):
        self.bad([dict(SEED[0], level="3")], "level must be int")
        self.bad([dict(SEED[0], level=True)], "level must be int")
        self.bad([dict(SEED[0], tags="ml")], "tags must be list")

    def test_missing_or_empty_summary(self):
        self.bad([{k: v for k, v in SEED[0].items() if k != "summary"}], "missing summary")
        self.bad([dict(SEED[0], summary="")], "missing summary")

    def test_bad_date(self):
        self.bad([dict(SEED[0], updated="yesterday")], "YYYY-MM-DD")

    def test_conflict_markers_and_bad_json_block_reads(self):
        (self.kb / "concepts.jsonl").write_text("<<<<<<< HEAD\n")
        self.assertIn("conflict", self.fails("list"))
        (self.kb / "concepts.jsonl").write_text("{not json\n")
        self.assertIn("invalid JSON", self.fails("list"))

    def test_writes_refuse_when_file_is_invalid(self):
        self.write([dict(SEED[0], kind="concept")])
        self.assertIn("unknown field", self.fails("set", "graph-basics", "--level", "2"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
