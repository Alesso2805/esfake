# ADR-0007: CI on every push, and continuous deployment to the VM over a restricted SSH key

- Status: Accepted (2026-10-11)
- Date: 2026-10-11
- Deciders: Alessandro David
- Related: `CLAUDE.md` (Definición de hecho), `docs/SPEC.md` (Arquitectura, Costos), ADR-0003 §5, EF-02, EF-18, EF-25

## Context

The owner asked for integration on every pushed commit and pull request, and deployment on every merge to `main`.

Five constraints shape how to do it:

- **Free plan, private repository.** GitHub Free gives a private repository 2,000 Actions minutes a month. Before this ADR, CI used about 3 minutes per run.
- **Branch protection.** Protected branches, rulesets and deployment environments (required reviewers, environment secrets) are not available to private repositories on GitHub Free. CI can report a failure but cannot block a merge.
- **Image registry.** Private GitHub Packages storage is 500 MB, shared with Actions artifacts. The backend image ships its models (ADR-0003 §1) and weighs about 2 GB, so publishing it there is not free.
- **Production hardware.** Production is one ARM VM (ADR-0003 §5). Since January 2026, GitHub-hosted arm64 runners are available to private repositories and draw on the same minutes.
- **Nothing to deploy to yet.** The VM does not exist yet (EF-18), and production must not open before the Ley 29733 checklist (EF-25).

## Decision

### 1. CI (`.github/workflows/ci.yml`)

| Event | Jobs | Purpose |
| --- | --- | --- |
| Push to any branch | Backend (Ruff, Mypy, Pytest with real Postgres, `esfake eval`, `esfake redteam`) and Web (ESLint, Next.js build) | Fast feedback on every commit |
| Pull request into `main` | Compose smoke test on `ubuntu-24.04-arm` | The merge result builds and starts on the production architecture |
| Push to `main` | All three | The commit that CD will deploy passed everything |

**Avoiding duplicate runs.** A pull request shows the checks of its head commit, so the fast checks run once per push, not again for the pull request event.

**What the smoke test does.**

- It runs `docker compose up --build --wait`, which only returns once every health check passes: Postgres, migrations, `/readyz` with the model loaded, and the web.
- It then runs `deploy/smoke.sh` from the host. The script also proves that the internal listener is not published (`CLAUDE.md` rule 9).

**Cost.**

- Each push spends about 3 minutes.
- Each pull request into `main` spends about 2 more: the first smoke test on arm64 took 1 min 42 s.
- At the current pace this stays well under 2,000 minutes a month.
- If usage nears the limit, the first lever is restricting the smoke test to pull requests, then path filters.

### 2. CD (`.github/workflows/cd.yml` and `deploy/deploy.sh`)

**Trigger.** CD starts on `workflow_run` once CI completes successfully for a push to `main`. Because CI on `main` includes the smoke test, a red `main` never deploys. CD can also be started by hand on `main` (`workflow_dispatch`).

**Concurrency.** Only one deploy runs at a time, and a running deploy is never cancelled.

**Mechanism.**

1. The runner opens SSH to the VM with a key that, in `authorized_keys`, may only run `deploy/deploy.sh` (`command=…,restrict`). It sends `deploy <sha>`.
2. The script refuses anything but a full commit sha that is on `origin/main`.
3. It checks out the commit and builds the images on the VM: native arm64, no registry, nothing paid.
4. If the build fails, production keeps running untouched.
5. It runs `docker compose up --wait`. The `migrate` service applies migrations before the API starts.
6. It runs `deploy/smoke.sh`.
7. If `up` or the smoke checks fail, it checks out the previous commit, starts it again and exits with an error, so the workflow fails.
8. Finally the runner checks `PUBLIC_URL/readyz` when that variable is set (EF-18 adds HTTPS and the domain).

**Secrets.**

- Production secrets live only in the `.env` next to `docker-compose.yml` on the VM. They never reach GitHub.
- GitHub holds only the deploy key, the host, the user and the host key, as repository secrets, which GitHub Free allows in private repositories.
- The workflow deletes the key from the runner at the end.

**Gate.** The deploy job runs only when the repository variable `DEPLOY_ENABLED` is `true`. It stays off until EF-18 has the VM ready and EF-25 has cleared the Ley 29733 checklist. Until then the job shows as skipped and spends no minutes.

### 3. Migrations must survive a rollback

A rollback returns the code, not the database. Every migration must therefore keep the previous release working ("expand, then contract"):

- add nullable columns or columns with defaults;
- backfill in a later step;
- drop or rename only in a release after no code uses the old shape.

A migration that cannot follow this is deployed by hand, with a backup taken just before (EF-18 runs daily backups).

### 4. Merges without branch protection

GitHub Free cannot require green checks on a private repository, so the rule is a working agreement:

- Nothing is merged with red CI.
- CD only deploys a `main` whose CI, smoke test included, passed.

Making the repository public would add branch protection, environments with required reviewers, free public images and unmetered minutes. That is the owner's decision. This design does not depend on it.

## Setup for EF-18 (owner tasks)

1. **On the VM:**
   - Create a `deploy` user in the `docker` group, which is root-equivalent: the forced command is what limits the key.
   - Clone the repository into `/opt/esfake/app` with a read-only deploy key (GitHub: Settings → Deploy keys, without write access).
   - Create `/opt/esfake/app/.env` from `.env.example`, with `ESFAKE_ENV=production`.
2. **The CD key:**
   - Generate it with `ssh-keygen -t ed25519 -C esfake-cd`.
   - Put the public half in `~deploy/.ssh/authorized_keys` as `command="/opt/esfake/app/deploy/deploy.sh",restrict ssh-ed25519 AAAA… esfake-cd`.
   - Store the private half as the `DEPLOY_SSH_KEY` secret, and never anywhere else.
3. **Repository secrets:**
   - `DEPLOY_HOST`
   - `DEPLOY_USER`
   - `DEPLOY_KNOWN_HOSTS`, from `ssh-keyscan <host>`, checked against the VM's own host key.
4. **First deploy and rollback test:** run `deploy/deploy.sh <sha>` by hand once, then force a failed deploy to watch the rollback.
5. **Switch on:** after EF-25, set the `DEPLOY_ENABLED=true` variable and, once HTTPS is ready, `PUBLIC_URL`.

## Alternatives considered

- **Publishing images to GitHub Container Registry.** Private storage beyond 500 MB is billed, and pulls from the VM count as data transfer. Rejected while the repository is private.
- **Multi-architecture images built with QEMU in Actions.** Slow and minute-hungry, and still needs a registry.
- **Oracle Cloud Infrastructure Registry.** Free within the Object Storage allowance that the backups also use. It adds an auth token in CI for no gain over building on the VM. Worth revisiting if builds on the VM become too slow.
- **A self-hosted runner on the production VM.** Any workflow could then run code on the production host. Rejected for security.
- **Preview deployments per pull request.** There is one free VM and no second environment. The smoke test plays that role.

## Consequences

- Every commit is checked. Every pull request into `main` proves that the stack starts on arm64. Every green merge deploys itself once the gate is on.
- Deploys take as long as a build on the VM, a few minutes, while the previous release keeps serving until `up` swaps the containers.
- Rollback is automatic for failures detected by the health checks and the smoke checks. Data problems still need a restore from backup.
- Merge discipline cannot be enforced while the repository is private on GitHub Free.
- Two quick merges deploy one after the other. A CI run on `main` cancelled by a newer push leaves its commit to the next deploy.

## References

- GitHub Actions billing and included minutes: https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions
- arm64 standard runners in private repositories (2026-01-29): https://github.blog/changelog/2026-01-29-arm64-standard-runners-are-now-available-in-private-repositories/
- GitHub Packages billing: https://docs.github.com/en/billing/concepts/product-billing/github-packages
- Deployment environments: https://docs.github.com/actions/deployment/targeting-different-environments/using-environments-for-deployment
- Protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
