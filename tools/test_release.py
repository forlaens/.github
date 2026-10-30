import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import json
import os
import tempfile

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


class ReleaseFlowTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.event = Path(self.directory.name) / 'event.json'
        self.sha = 'a' * 40
        self.run = {'id': 1, 'event': 'pull_request', 'conclusion': 'success',
                    'head_repository': {'full_name': 'forlaens/example'},
                    'head_sha': 'head', 'pull_requests': [{'number': 2}]}
        self.pr = {'number': 2, 'state': 'open', 'draft': False, 'merged': True,
                   'head': {'sha': 'head', 'repo': {'full_name': 'forlaens/example'}},
                   'base': {'ref': 'main'}, 'merge_commit_sha': self.sha}
        self.env = {'RELEASE_MODE': 'orchestrate', 'GITHUB_REPOSITORY': 'forlaens/example',
                    'VALIDATION_WORKFLOW': 'ci.yml', 'REQUIRED_JOBS': '["Browser tests"]',
                    'GITHUB_EVENT_PATH': str(self.event), 'DEPLOY_SHA': self.sha,
                    'VALIDATION_RUN_ID': '1', 'GITHUB_REF': 'refs/heads/main'}

    def flow(self, tree='tree', deployed=False):
        self.event.write_text(json.dumps({'workflow_run': self.run}))
        with patch.dict(os.environ, self.env), patch.object(release, 'api', return_value=self.pr) as api, \
             patch.object(release, 'command', return_value=self.sha), \
             patch.object(release, 'current_main', return_value={'sha': self.sha, 'tree': {'sha': 'tree'}}), \
             patch.object(release, 'already_deployed', return_value=deployed), \
             patch.object(release, 'checked_tree', side_effect=tree if isinstance(tree, Exception) else None, return_value=tree), \
             patch.object(release, 'output') as output:
            release.main()
            return [c for c in api.call_args_list if len(c.args) > 1 and c.args[1] == 'POST'], output.call_args_list

    def test_identical_tree_dispatches_one_release(self):
        calls, _ = self.flow()
        self.assertEqual(len(calls), 1)
        self.assertIn('/deploy.yml/dispatches', calls[0].args[0])
        self.assertEqual(calls[0].args[2]['inputs'], {'sha': self.sha, 'validation_run_id': '1'})

    def test_changed_or_missing_evidence_dispatches_full_main_only(self):
        for tree in ['different', ValueError('missing evidence')]:
            calls, _ = self.flow(tree)
            self.assertEqual(len(calls), 1)
            self.assertIn('/ci.yml/dispatches', calls[0].args[0])

    def test_obsolete_pr_does_not_dispatch(self):
        self.pr['head']['sha'] = 'new-head'
        with self.assertRaises(ValueError):
            self.flow()

    def test_missing_run_pull_requests_uses_commit_association(self):
        self.run['pull_requests'] = []
        with patch.object(release, 'paginated', return_value=[{'number': 2}]) as lookup:
            calls, _ = self.flow()
        self.assertEqual(len(calls), 1)
        self.assertIn('/deploy.yml/dispatches', calls[0].args[0])
        lookup.assert_called_once_with('repos/forlaens/example/commits/head/pulls', None)

    def test_missing_or_ambiguous_association_cannot_release(self):
        self.run['pull_requests'] = []
        for candidates in [[], [{'number': 2}, {'number': 3}]]:
            with self.subTest(candidates=candidates), patch.object(release, 'paginated', return_value=candidates):
                with self.assertRaises(ValueError):
                    self.flow()

    def test_duplicate_success_does_not_dispatch_or_deploy(self):
        self.assertEqual(self.flow(deployed=True)[0], [])
        self.env['RELEASE_MODE'] = 'verify'
        self.assertEqual(self.flow(deployed=True)[1][0].args, ('deploy', 'false'))

    def test_manual_dispatch_cannot_bypass_tree_check(self):
        self.env['RELEASE_MODE'] = 'verify'
        with self.assertRaises(ValueError):
            self.flow('changed')

    def test_old_main_validation_cannot_authorize_new_commit(self):
        with patch.object(release, 'api', return_value={'event': 'push', 'head_sha': 'old'}), \
             patch.object(release, 'read_evidence', return_value={}):
            with self.assertRaisesRegex(ValueError, 'another main revision'):
                release.checked_tree('repos/forlaens/example', 1, 'ci.yml', [], self.sha)

    def test_recorded_pr_survives_empty_github_association_index(self):
        self.run['pull_requests'] = []
        with patch.object(release, 'api', return_value=self.pr), \
             patch.object(release, 'paginated', side_effect=AssertionError('Must not use the delayed search index')):
            self.assertEqual(release.validation_pull_request('repos/forlaens/example', self.run, 2), self.pr)

    def test_recorded_pr_still_requires_exact_revision_repository_and_target(self):
        for field, value in [('sha', 'another-head'), ('repo', {'full_name': 'someone/fork'})]:
            wrong = copy.deepcopy(self.pr)
            wrong['head'][field] = value
            with self.subTest(field=field), patch.object(release, 'api', return_value=wrong):
                with self.assertRaises(ValueError):
                    release.validation_pull_request('repos/forlaens/example', self.run, 2)
        wrong = copy.deepcopy(self.pr)
        wrong['base']['ref'] = 'other-branch'
        with patch.object(release, 'api', return_value=wrong), self.assertRaises(ValueError):
            release.validation_pull_request('repos/forlaens/example', self.run, 2)
        for number in [True, '2', 0, -1]:
            with self.subTest(number=number), self.assertRaises(ValueError):
                release.validation_pull_request('repos/forlaens/example', self.run, number)

    def test_record_saves_the_event_pull_request_number(self):
        self.env.update(RELEASE_MODE='record', GITHUB_RUN_ID='1', GITHUB_RUN_ATTEMPT='1',
                        GITHUB_EVENT_NAME='pull_request', RUNNER_TEMP=self.directory.name)
        self.event.write_text(json.dumps({'pull_request': {'number': 2}}))
        with patch.dict(os.environ, self.env), patch.object(release, 'command', return_value=self.sha), \
             patch.object(release, 'output'):
            release.main()
        evidence = json.loads((Path(self.directory.name) / 'validation.json').read_text())
        self.assertEqual(evidence['pull_request_number'], 2)


if __name__ == "__main__":
    unittest.main()
