#!/usr/bin/env python3
"""License-free checks shared by local development and GitHub Actions."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import urllib.request

CACHE = Path(os.environ.get("FORLAENS_TOOLS_CACHE", str(Path.home() / ".cache/forlaens-security")))
BINARIES = {
    "gitleaks": ("gitleaks/gitleaks", "8.30.1", {
        "Darwin-arm64": ("darwin_arm64", "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5"),
        "Linux-x86_64": ("linux_x64", "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"),
        "Linux-aarch64": ("linux_arm64", "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080"),
    }),
    "actionlint": ("rhysd/actionlint", "1.7.12", {
        "Darwin-arm64": ("darwin_arm64", "aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f"),
        "Linux-x86_64": ("linux_amd64", "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"),
        "Linux-aarch64": ("linux_arm64", "325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6"),
    }),
}


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def git(*args):
    return run(["git", *args], capture_output=True, text=True).stdout.strip()


def binary(name):
    repo, version, platforms = BINARIES[name]
    target = CACHE / f"{name}-{version}" / name
    if not target.exists():
        suffix, checksum = platforms[f"{platform.system()}-{platform.machine()}"]
        url = f"https://github.com/{repo}/releases/download/v{version}/{name}_{version}_{suffix}.tar.gz"
        data = urllib.request.urlopen(url, timeout=60).read()
        if hashlib.sha256(data).hexdigest() != checksum:
            raise RuntimeError(f"Invalid checksum for {name}")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            member = next(m for m in archive.getmembers() if m.name.removeprefix("./") == name and m.isfile())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
        target.chmod(0o755)
    return target


def python_tools():
    target = CACHE / "python-semgrep-1.176.1-zizmor-1.31.1"
    marker = target / ".complete"
    if not marker.exists():
        run([sys.executable, "-m", "venv", target])
        run([target / "bin/python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "semgrep==1.176.1", "zizmor==1.31.1"])
        marker.touch()
    return target / "bin"


def scan_secrets(revision=None):
    args = [binary("gitleaks"), "git", "--redact=100", "--no-banner"]
    # Ignore project allow-comments; reviewed false positives belong in a narrow config.
    args.append("--ignore-gitleaks-allow")
    if revision:
        args += ["--log-opts", revision]
    run(args)


def pre_push(data):
    for line in data.splitlines():
        _, local_sha, _, remote_sha = line.split()
        if set(local_sha) == {"0"}:
            continue
        if set(remote_sha) != {"0"} and subprocess.run(
            ["git", "cat-file", "-e", remote_sha], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0:
            scan_secrets(f"{remote_sha}..{local_sha}")
        else:
            # New branch or unknown remote history: inspect all outgoing history.
            scan_secrets(local_sha)


def install_hook():
    # Keep an existing hook and its stdin contract intact. The cached checker also
    # works in older worktrees which do not yet contain the repository launcher.
    configured = subprocess.run(["git", "config", "--get", "core.hooksPath"], capture_output=True, text=True).stdout.strip()
    hook_dir = Path(configured) if configured else Path(git("rev-parse", "--git-common-dir")) / "hooks"
    hook_dir = hook_dir.resolve()
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook = hook_dir / "pre-push"
    previous = hook_dir / "pre-push.before-forlaens-security"
    marker = "# Forlaens license-free security hook"
    if hook.exists() and marker not in hook.read_text():
        if previous.exists():
            raise RuntimeError("An existing hook backup needs review; no hook was replaced")
        hook.rename(previous)
    checker = Path(__file__).resolve()
    hook.write_text("#!/usr/bin/env python3\n" + marker + "\n" +
        "import subprocess, sys\nfrom pathlib import Path\n" +
        f"previous = Path({str(previous)!r})\ndata = sys.stdin.buffer.read()\n" +
        "if previous.exists():\n subprocess.run([str(previous), *sys.argv[1:]], input=data, check=True)\n" +
        f"subprocess.run([sys.executable, {str(checker)!r}, '--mode', 'pre-push'], input=data, check=True)\n")
    hook.chmod(0o755)
    binary("gitleaks")
    print("Installed pre-push secret check; existing hook preserved")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "secrets", "history", "pre-push", "install-hook"], default="full")
    parser.add_argument("--base")
    args = parser.parse_args()
    if args.mode == "install-hook":
        install_hook()
        return
    if args.mode == "pre-push":
        pre_push(sys.stdin.read())
        return
    scan_secrets(f"{args.base}..HEAD" if args.base else ("--all" if args.mode == "history" else "HEAD"))
    if args.mode != "full":
        return
    bins = python_tools()
    env = {k: v for k, v in os.environ.items() if not k.startswith("SEMGREP_")}
    env.update(SEMGREP_SEND_METRICS="off", SEMGREP_ENABLE_VERSION_CHECK="0")
    scan = subprocess.run([str(bins / "semgrep"), "scan", "--config", "p/default", "--config", str(Path(__file__).with_name("security-rules.yml")), "--metrics=off", "--disable-version-check", "--severity", "ERROR", "--error", "--json"], env=env, capture_output=True, text=True)
    result = json.loads(scan.stdout)
    for finding in result.get("results", []):
        # Deliberately exclude matched source and metavariables from all logs.
        print(f"{finding['path']}:{finding['start']['line']}: {finding['check_id']}")
    if scan.returncode:
        raise RuntimeError(f"Static analysis failed (exit {scan.returncode}); {len(result.get('errors', []))} scanner errors")
    print("Static analysis passed")
    workflows = sorted(Path(".github/workflows").glob("*.y*ml"))
    if workflows:
        run([binary("actionlint"), "-shellcheck=", *workflows])
        run([bins / "zizmor", "--offline", "--min-severity", "high", "--min-confidence", "high", *workflows])


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
