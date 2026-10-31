# Forlæns shared repository instructions

This repository maintains shared contribution guidance, repository templates and pinned security/release tooling for the `forlaens` organization.

- Develop and investigate failures locally. Batch related fixes before publishing a ready PR; use a draft only for work that is deliberately unfinished. Keep the final independent cloud check.
- For documentation-only changes, review accuracy, links, scope and consistency and run `git diff --check` and a secret scan. Tooling changes additionally require `python3 -m unittest discover -s tools -p 'test_*.py'` and `python3 tools/security.py` before pushing.
- Preserve fail-closed release verification, secret redaction, fixed tool revisions, existing public/free security and all required checks. Do not change consumer pins as part of a documentation update.
- Never automatically enable paid security, AI features or trials, or raise the organization's USD 50 Actions hard-stop budget or zero paid-overage budgets.
- When creating or configuring another Forlæns repository, copy `templates/AGENTS.md` into its root, reconcile existing instructions and add real project setup and validation commands. Files here are not automatically loaded as instructions in other repositories.
- Keep the template and `CONTRIBUTING.md` consistent. The template must remain useful without access to this Mac and must not contain invented commands, credentials or private machine paths.

Source: approved cost-control plan, 2026-10-30, and Tobias' explicit AGENTS.md request, 2026-10-31. Scope: this shared repository and its Forlæns templates. Refresh when the approved policy, tool interfaces or instruction discovery changes.
