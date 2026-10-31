# Contributing

Thank you for considering a contribution to a Forlæns project.

## Before You Start

- Check the README and existing issues.
- Open an issue before starting a substantial change.
- Keep changes focused and avoid unrelated refactoring.

## Pull Requests

1. Create a branch from the default branch.
2. Follow the setup and test instructions in the repository README.
3. Add or update tests when behavior changes.
4. Describe the problem and the solution clearly.
5. Confirm that automated checks pass.

Accessibility is part of the acceptance criteria for user-facing changes.

## CI costs and security

Run focused checks locally while developing, then the repository's full local
checks before publishing a ready pull request. GitHub performs the final
independent validation. Reuse that validation for deployment only when the
tested Git tree and all required checks match the deployed revision.

Batch related corrections before pushing. Keep unfinished work local or use a
draft pull request when sharing it is useful. Publish a ready pull request after
the applicable local checks pass. Investigate failed CI locally before pushing
a tested correction; do not use repeated pushes or blind reruns for debugging.
Report local environment gaps without weakening the independent cloud gates.

New Forlæns repositories must include a tracked root `AGENTS.md`, using
[`templates/AGENTS.md`](templates/AGENTS.md) and their verified local setup and
validation commands. Preserve existing project instructions. Organization
community files do not automatically supply AGENTS.md instructions to other
repositories. Existing repositories should adopt the policy when changing CI
or repository setup. Documentation-only changes receive proportionate local
review and secret scanning; required cloud checks remain in place.

Private repositories use the pinned, license-free security action in this
repository. Install their local pre-push hook with
`python3 .github/security.py --mode install-hook`; run the same checks with
`python3 .github/security.py`. Never bypass a secret finding to make a push pass.

Do not enable paid security products, AI add-ons, or paid trials automatically.
Keep the organization's Actions stop budget at USD 50 per month; do not raise
it automatically. Other metered add-ons have a zero overage budget. Ordinary
dependency updates are grouped weekly; vulnerability fixes remain immediate.
Production checks use daily/post-release smoke tests and weekly full audits.

Source: Tobias' approved cost-control implementation plan, 2026-10-30, and
explicit AGENTS.md request for current and future repositories, 2026-10-31.
Scope: Forlaens-owned repositories. Revisit only after an explicit change to
the budget or policy, or a verified change in the provider's billing model.
