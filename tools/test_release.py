import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("release", Path(__file__).with_name("release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.run = {"id": 1, "run_attempt": 2, "status": "completed", "conclusion": "success",
                    "repository": {"full_name": "forlaens/example"}, "head_repository": {"full_name": "forlaens/example"},
                    "path": ".github/workflows/ci.yml", "event": "pull_request", "head_sha": "head"}
        self.evidence = {"run_id": "1", "run_attempt": "2", "repository": "forlaens/example",
                         "event": "pull_request", "checkout_sha": "merge", "tree": "tree"}
        self.commit = {"sha": "merge", "tree": {"sha": "tree"}, "parents": [{"sha": "base"}, {"sha": "head"}]}
        self.jobs = [{"name": "Browser tests", "conclusion": "success"}]

    def validate(self):
        return release.validate(self.run, self.evidence, self.jobs, self.commit, "forlaens/example", "ci.yml", ["Browser tests"])

    def test_successful_tested_merge_tree(self):
        self.assertEqual(self.validate(), "tree")

    def test_rejects_unsafe_or_incomplete_evidence(self):
        for field, value in [("conclusion", "failure"), ("status", "in_progress"),
                             ("head_sha", "newer-head"), ("path", ".github/workflows/other.yml"),
                             ("head_repository", {"full_name": "someone/fork"})]:
            with self.subTest(field=field):
                original = copy.deepcopy(self.run)
                self.run[field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.run = original

    def test_rejects_previous_attempt_or_different_tree(self):
        for field, value in [("run_attempt", "1"), ("tree", "changed"), ("run_id", "9"), ("checkout_sha", "other")]:
            with self.subTest(field=field):
                original = self.evidence.copy()
                self.evidence[field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.evidence = original

    def test_skipped_missing_or_failed_required_job_cannot_release(self):
        for jobs in [[], [{"name": "Browser tests", "conclusion": "skipped"}], [{"name": "Browser tests", "conclusion": "failure"}]]:
            self.jobs = jobs
            with self.assertRaises(ValueError):
                self.validate()

    def test_main_requires_matching_commit_and_branch(self):
        self.run.update(event="workflow_dispatch", head_branch="main", head_sha="merge")
        self.evidence["event"] = "workflow_dispatch"
        self.assertEqual(self.validate(), "tree")
        self.run["head_branch"] = "feature"
        with self.assertRaises(ValueError):
            self.validate()


if __name__ == "__main__":
    unittest.main()
