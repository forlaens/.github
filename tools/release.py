#!/usr/bin/env python3
"""Validate immutable CI evidence before reusing it for a production release."""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def api(path, method="GET", body=None):
    args = ["gh", "api", path, "--method", method]
    if body is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def paginated(path, field):
    result = []
    for page in range(1, 101):
        data = api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        items = data[field] if field else data
        result.extend(items)
        if len(items) < 100:
            return result
    raise ValueError("Unexpected pagination limit")


def validate(run, evidence, jobs, commit, repository, workflow, required_jobs):
    """No execution of artifacts; only a small JSON document and GitHub API data."""
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("Validation has not completed successfully")
    if run.get("repository", {}).get("full_name") != repository or run.get("head_repository", {}).get("full_name") != repository:
        raise ValueError("Validation must belong to this repository, not a fork")
    if run.get("path", "").split("@")[0] != f".github/workflows/{workflow}":
        raise ValueError("Unexpected validation workflow")
    if run.get("event") not in ("pull_request", "push", "workflow_dispatch"):
        raise ValueError("Unexpected validation event")
    if evidence.get("run_id") != str(run["id"]) or evidence.get("run_attempt") != str(run["run_attempt"]):
        raise ValueError("Evidence belongs to a different run or attempt")
    if evidence.get("repository") != repository or evidence.get("event") != run["event"]:
        raise ValueError("Evidence identity mismatch")
    if evidence.get("tree") != commit["tree"]["sha"] or evidence.get("checkout_sha") != commit["sha"]:
        raise ValueError("Evidence does not describe the checked Git commit")
    successful = {j["name"] for j in jobs if j.get("conclusion") == "success"}
    if not set(required_jobs).issubset(successful):
        raise ValueError("A required test was skipped, failed, or absent")
    if run["event"] == "pull_request":
        parents = [p["sha"] for p in commit["parents"]]
        if len(parents) != 2 or parents[1] != run["head_sha"]:
            raise ValueError("PR evidence must describe the tested merge commit")
    elif run.get("head_branch") != "main" or commit["sha"] != run["head_sha"]:
        raise ValueError("Main validation revision mismatch")
    return evidence["tree"]


def read_evidence(root, run):
    name = f"release-validation-{run['id']}-{run['run_attempt']}"
    artifacts = paginated(f"{root}/actions/runs/{run['id']}/artifacts", "artifacts")
    matches = [a for a in artifacts if a["name"] == name and not a["expired"]]
    if len(matches) != 1:
        raise ValueError("Missing unique validation evidence")
    data = subprocess.check_output(["gh", "api", f"{root}/actions/artifacts/{matches[0]['id']}/zip"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist() != ["validation.json"] or archive.getinfo("validation.json").file_size > 16384:
            raise ValueError("Unexpected validation artifact contents")
        return json.loads(archive.read("validation.json"))


def checked_tree(root, run_id, workflow, required_jobs, deployment_sha=None):
    if not str(run_id).isdigit():
        raise ValueError("Invalid validation run ID")
    run = api(f"{root}/actions/runs/{run_id}")
    if deployment_sha:
        if run.get("event") == "pull_request":
            pulls = run.get("pull_requests", [])
            if len(pulls) != 1:
                raise ValueError("Missing deployment pull request")
            pr = api(f"{root}/pulls/{pulls[0]['number']}")
            if not pr.get("merged") or pr.get("merge_commit_sha") != deployment_sha or pr["head"]["sha"] != run["head_sha"]:
                raise ValueError("Validation belongs to another release")
        elif run.get("head_sha") != deployment_sha:
            raise ValueError("Validation belongs to another main revision")
    evidence = read_evidence(root, run)
    sha = evidence.get("checkout_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid tested commit SHA")
    commit = api(f"{root}/git/commits/{sha}")
    jobs = paginated(f"{root}/actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", "jobs")
    return validate(run, evidence, jobs, commit, os.environ["GITHUB_REPOSITORY"], workflow, required_jobs)


def output(name, value):
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"{name}={value}\n")


def already_deployed(root, sha):
    return any(s["context"] == "production/deployed" and s["state"] == "success"
               for s in paginated(f"{root}/commits/{sha}/statuses", None))


def current_main(root):
    sha = api(f"{root}/git/ref/heads/main")["object"]["sha"]
    return api(f"{root}/git/commits/{sha}")


def main():
    mode = os.environ["RELEASE_MODE"]
    repository = os.environ["GITHUB_REPOSITORY"]
    root = f"repos/{repository}"
    workflow = os.environ["VALIDATION_WORKFLOW"]
    required = json.loads(os.environ["REQUIRED_JOBS"])
    if mode == "record":
        evidence = {"repository": repository, "run_id": os.environ["GITHUB_RUN_ID"],
                    "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "event": os.environ["GITHUB_EVENT_NAME"],
                    "checkout_sha": command("git", "rev-parse", "HEAD"),
                    "tree": command("git", "rev-parse", "HEAD^{tree}")}
        path = Path(os.environ["RUNNER_TEMP"]) / "validation.json"
        path.write_text(json.dumps(evidence))
        output("evidence", path)
        return
    if mode == "orchestrate":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        run = event["workflow_run"]
        if run["conclusion"] != "success" or run.get("head_repository", {}).get("full_name") != repository:
            return
        if run["event"] == "pull_request":
            pulls = run.get("pull_requests", [])
            if len(pulls) != 1:
                raise ValueError("Expected one validated pull request")
            number = pulls[0]["number"]
            pr = api(f"{root}/pulls/{number}")
            if pr["state"] != "open" or pr["draft"] or pr["head"]["sha"] != run["head_sha"]:
                return
            if pr["head"]["repo"]["full_name"] != repository or pr["base"]["ref"] != "main":
                raise ValueError("Unexpected pull request source or target")
            command("gh", "pr", "merge", str(number), "--repo", repository, "--squash", "--delete-branch", "--match-head-commit", run["head_sha"])
            sha = api(f"{root}/pulls/{number}")["merge_commit_sha"]
        elif run["event"] in ("push", "workflow_dispatch") and run["head_branch"] == "main":
            sha = run["head_sha"]
        else:
            return
        main_commit = current_main(root)
        if main_commit["sha"] != sha or already_deployed(root, sha):
            return
        try:
            tree = checked_tree(root, run["id"], workflow, required, sha)
            if tree != main_commit["tree"]["sha"]:
                raise ValueError("Main changed after validation")
        except (ValueError, subprocess.CalledProcessError) as error:
            # A failed main validation cannot recursively dispatch itself.
            if run["event"] != "pull_request":
                raise
            print(f"Full main validation required: {error}")
            api(f"{root}/actions/workflows/{workflow}/dispatches", "POST", {"ref": "main"})
            return
        api(f"{root}/actions/workflows/deploy.yml/dispatches", "POST", {
            "ref": "main", "inputs": {"sha": sha, "validation_run_id": str(run["id"])}})
        return
    sha = os.environ.get("DEPLOY_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("A full deployment commit SHA is required")
    if mode == "verify":
        if os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise ValueError("Deployment workflow must run from main")
        main_commit = current_main(root)
        if main_commit["sha"] != sha or command("git", "rev-parse", "HEAD") != sha:
            raise ValueError("Deployment must be the current main revision")
        tree = checked_tree(root, os.environ["VALIDATION_RUN_ID"], workflow, required, sha)
        if tree != main_commit["tree"]["sha"]:
            raise ValueError("Deployment tree differs from validated tree")
        output("deploy", "false" if already_deployed(root, sha) else "true")
        return
    if mode == "mark":
        api(f"{root}/statuses/{sha}", "POST", {"state": "success", "context": "production/deployed",
            "description": "Validated revision deployed and verified",
            "target_url": f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"})
        return
    raise ValueError("Unknown release mode")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Release blocked: {error}", file=sys.stderr)
        sys.exit(1)
