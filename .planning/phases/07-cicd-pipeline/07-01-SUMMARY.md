---
phase: 07-cicd-pipeline
plan: "01"
subsystem: cicd
tags: [github-actions, docker, ecr, terraform, ruff, pytest, oidc, lambda, smoke-test]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: ECR repository, Lambda function, API Gateway, Terraform outputs (api_gateway_url, lambda_function_name)
  - phase: 04-lambda-serving-and-api
    provides: FastAPI Lambda serving GET /health and GET /predict endpoints
provides:
  - CI workflow (.github/workflows/ci.yml) triggering ruff lint + pytest on every PR to main
  - CD workflow (.github/workflows/cd.yml) triggering Docker build → ECR push → Terraform apply → Lambda smoke test on merge to main
  - requirements-dev.txt with dev-only dependencies (ruff, pytest, pytest-cov)
affects: [all future development — PRs blocked by lint/test failures, merges auto-deploy to Lambda]

# Tech tracking
tech-stack:
  added: [github-actions, ruff, pytest-cov, docker/build-push-action@v5, aws-actions/configure-aws-credentials@v4, aws-actions/amazon-ecr-login@v2, hashicorp/setup-terraform@v3]
  patterns: [OIDC role assumption for AWS auth (no long-lived credentials), provenance:false for Lambda-compatible ECR images, commit-SHA image tagging forces Terraform state change per deploy]

key-files:
  created:
    - .github/workflows/ci.yml
    - .github/workflows/cd.yml
    - requirements-dev.txt
  modified: []

key-decisions:
  - "provenance: false + sbom: false on docker/build-push-action@v5 — Lambda only accepts Docker Image Manifest V2 Schema 2; OCI attestation manifests cause InvalidParameterValueException"
  - "image_tag=${{ github.sha }} not :latest — SHA tag ensures Terraform sees new image_uri per merge, forcing Lambda update; :latest would produce no state diff"
  - "terraform_wrapper: false — disables HashiCorp output wrapper so terraform output -raw parses cleanly in shell"
  - "aws lambda wait function-updated before smoke test — prevents race condition where smoke test hits old function during Lambda image propagation"
  - "Job named lint-and-test — must match GitHub branch protection required status check name exactly"

patterns-established:
  - "OIDC pattern: permissions id-token:write + aws-actions/configure-aws-credentials@v4 — no AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY secrets needed"
  - "Smoke test pattern: curl -fsS -o /dev/null -w %{http_code} — -f fails on 4xx/5xx, silent output, shows HTTP code for diagnostics"

requirements-completed: [CICD-01, CICD-02, CICD-03]

# Metrics
duration: 6min
completed: 2026-03-13
---

# Phase 7 Plan 01: CI/CD Pipeline Summary

**GitHub Actions CI (ruff + pytest on PRs) and CD (Docker build → ECR push with provenance:false → Terraform apply → Lambda smoke test on merge) workflows with OIDC AWS authentication**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-13T19:03:18Z
- **Completed:** 2026-03-13T19:09:32Z
- **Tasks:** 2 of 3 automated (Task 3 is checkpoint:human-verify)
- **Files modified:** 3 created

## Accomplishments

- Created `.github/workflows/ci.yml`: PR quality gate with ruff lint, ruff format check, and pytest on Python 3.11
- Created `.github/workflows/cd.yml`: Full deploy pipeline — OIDC AWS auth, ECR image push with Lambda-compatible flags, Terraform apply with SHA-tagged image, Lambda propagation wait, dual endpoint smoke test
- Created `requirements-dev.txt`: dev-only dependencies isolated from production requirements.txt
- Confirmed `infra/outputs.tf` already has both `lambda_function_name` and `api_gateway_url` outputs — no changes needed

## Task Commits

Each task was committed atomically:

1. **Task 1: Create requirements-dev.txt and CI workflow** - `6b0757c` (feat)
2. **Task 2: Create CD workflow (build → ECR → Terraform → smoke test)** - `ee24e3b` (feat)
3. **Task 3: Configure GitHub secrets and branch protection** - CHECKPOINT (human-verify required)

**Plan metadata:** (pending after checkpoint)

## Files Created/Modified

- `.github/workflows/ci.yml` - PR lint+test workflow; job lint-and-test on pull_request to main
- `.github/workflows/cd.yml` - Merge-to-main build/deploy/smoke workflow; OIDC, ECR, Terraform, Lambda wait, curl smoke test
- `requirements-dev.txt` - ruff, pytest, pytest-cov for CI dev dependencies

## Decisions Made

- `provenance: false` + `sbom: false` required on `docker/build-push-action@v5`: without these, build produces OCI attestation manifests that Lambda rejects with `InvalidParameterValueException`
- `image_tag=${{ github.sha }}`: commit SHA as image tag ensures each merge creates unique `image_uri` in Terraform state, forcing Lambda function update; `:latest` would produce no state diff
- `terraform_wrapper: false`: disables HashiCorp wrapper to allow clean `terraform output -raw` parsing in shell steps
- `aws lambda wait function-updated`: added between Terraform apply and smoke test to prevent race condition during Lambda image propagation (up to 5 minutes)
- Job name `lint-and-test`: must exactly match the string used in GitHub branch protection required status checks

## Deviations from Plan

None - plan executed exactly as written. Both `lambda_function_name` and `api_gateway_url` outputs already existed in `infra/outputs.tf` from Phase 1, so no modifications were needed.

## User Setup Required

Task 3 (checkpoint:human-verify) requires manual GitHub configuration:

**Step 1: Add GitHub Actions Secrets**

Navigate to: GitHub repo → Settings → Secrets and variables → Actions → Repository secrets

| Secret Name | Value Source |
|---|---|
| `AWS_ROLE_ARN` | IAM Console → Roles → OIDC role created in Phase 1 → ARN |
| `AWS_REGION` | AWS region used for all infrastructure (e.g., `us-east-1`) |
| `ECR_REPOSITORY` | ECR Console → Repositories → repo name created in Phase 1 |

**Step 2: Enable branch protection on main**

Navigate to: GitHub repo → Settings → Branches → Add branch protection rule

- Branch name pattern: `main`
- Check: "Require status checks to pass before merging"
- Search for and select: `lint-and-test`
- Optionally check: "Require branches to be up to date before merging"
- Click "Save changes"

Note: `lint-and-test` only appears in the status check search after the first CI run on a PR. Push a test branch to trigger a CI run first, then return to configure branch protection.

## Next Phase Readiness

- CI/CD infrastructure complete — all workflow files committed and YAML-validated
- Awaiting GitHub secrets + branch protection configuration (Task 3)
- Once secrets are set and a PR is opened, the full CI pipeline will run automatically
- Once merged to main, the CD pipeline will build, deploy, and smoke-test against the live Lambda API

---
*Phase: 07-cicd-pipeline*
*Completed: 2026-03-13*
