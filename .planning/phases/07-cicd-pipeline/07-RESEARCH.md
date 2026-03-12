# Phase 7: CI/CD Pipeline - Research

**Researched:** 2026-03-12
**Domain:** GitHub Actions CI/CD — lint, test, Docker/ECR, Terraform, Lambda deploy, smoke test
**Confidence:** HIGH (official docs + verified community sources)

## Summary

Phase 7 adds GitHub Actions automation on top of a fully operational stack. Two workflows are needed: a CI workflow triggered on every PR that runs ruff lint and pytest to block merge on failure, and a CD workflow triggered on merge to main that builds a Docker image, pushes to ECR with `provenance: false` (required for Lambda Docker v2 manifest compatibility), applies Terraform to update the Lambda function, and ends with a smoke test hitting `/health` and `/predict`.

The critical known pitfall is the `provenance: false` + `sbom: false` requirement on `docker/build-push-action`. GitHub Actions (v4+) defaults to OCI image format with provenance attestations and SBOM metadata, but AWS Lambda only supports Docker v2 image manifests (`application/vnd.docker.distribution.manifest.v2+json`). Omitting these flags causes `InvalidParameterValueException` when Lambda tries to pull the image. This is well-documented and verified.

AWS credentials should be managed via OIDC (not static `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` secrets). OIDC eliminates long-lived credentials by having GitHub Actions assume an IAM role directly. The workflow needs `permissions: id-token: write` for OIDC token issuance. This is the current AWS-recommended approach as of 2025.

**Primary recommendation:** One plan, one YAML file per workflow (`.github/workflows/ci.yml` and `.github/workflows/cd.yml`), with OIDC-based AWS auth, `provenance: false` + `sbom: false` on docker build-push, terraform apply in the CD job, and a final curl-based smoke test step.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CICD-01 | GitHub Actions CI: lint (ruff) + pytest + smoke train on PR | PR trigger with `on: pull_request`, `ruff check`, `pytest` steps; branch protection via required status checks |
| CICD-02 | GitHub Actions CD: Docker build → push to ECR (provenance: false) → terraform apply on merge | `on: push: branches: [main]`, `docker/build-push-action@v5` with `provenance: false` + `sbom: false`, `aws-actions/amazon-ecr-login@v2`, `hashicorp/setup-terraform@v3` + `terraform apply -auto-approve` |
| CICD-03 | Post-deploy smoke test: GET /health and GET /predict, fail workflow if non-200 | `curl -f` on API Gateway URL from terraform output; `-f` flag makes curl return non-zero on HTTP errors |
</phase_requirements>

## Standard Stack

### Core

| Tool/Action | Version | Purpose | Why Standard |
|-------------|---------|---------|--------------|
| `actions/checkout` | v4 | Checkout repo in workflow | Official GitHub action, current major version |
| `actions/setup-python` | v5 | Install Python + pip cache | Official, supports `cache: 'pip'` |
| `aws-actions/configure-aws-credentials` | v4 | OIDC-based AWS auth | Official AWS action; v4 required for OIDC |
| `aws-actions/amazon-ecr-login` | v2 | ECR Docker registry login | Official AWS action |
| `docker/build-push-action` | v5 | Build + push Docker image | Standard Docker action, v5 current |
| `docker/setup-buildx-action` | v3 | Enable Docker BuildKit | Required by build-push-action v5 |
| `hashicorp/setup-terraform` | v3 | Install Terraform CLI | Official HashiCorp action |
| `ruff` | latest | Python linting + formatting check | Project stack; `ruff check` + `ruff format --check` |
| `pytest` | latest | Test runner | Project stack |

### Supporting

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| `actions/cache` | v4 | Cache pip packages across runs | Speeds up CI; `setup-python` with `cache: pip` handles this automatically |
| `curl -f` | system | Smoke test HTTP endpoints | Final CD step; `-f` returns exit code 22 on non-200 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| OIDC (`role-to-assume`) | Static `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` secrets | OIDC preferred: no long-lived credentials; static secrets require manual rotation and are a security risk |
| `terraform apply` in CD | `aws lambda update-function-code` | terraform apply is preferred because it's the project's IaC approach (Phase 1 used Terraform); `update-function-code` would bypass Terraform state |
| Two separate workflow files | Single workflow with conditional jobs | Two files is cleaner; CI for PR, CD for main push — separate concerns |

## Architecture Patterns

### Recommended Project Structure

```
.github/
└── workflows/
    ├── ci.yml       # PR: lint + test
    └── cd.yml       # merge to main: build → ECR → deploy → smoke
```

### Pattern 1: CI Workflow (PR lint + test)

**What:** Triggered on `pull_request` to `main`, runs ruff and pytest. GitHub reports status check on the PR, which can be set as required to block merge.

**Example:**
```yaml
name: CI
on:
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Lint with ruff
        run: ruff check .

      - name: Check formatting
        run: ruff format --check .

      - name: Run tests
        run: pytest tests/ -x -q
```

**Source:** GitHub Docs — Building and testing Python; Ruff integrations docs

### Pattern 2: CD Workflow (merge to main → ECR → Lambda → smoke)

**What:** Triggered on push to `main`. Builds Docker image with `provenance: false` + `sbom: false`, pushes to ECR, runs `terraform apply`, then hits smoke test endpoints.

**Key sub-patterns:**
- OIDC auth requires `permissions: id-token: write` at job level
- ECR registry URL: `${{ steps.login-ecr.outputs.registry }}`
- Image tag: ECR registry + repo name + commit SHA for traceability
- Terraform: `terraform init` → `terraform apply -auto-approve -var="image_tag=$IMAGE_TAG"`
- Smoke test: extract API URL from `terraform output`, then `curl -f`

**Example (CD skeleton):**
```yaml
name: CD
on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ secrets.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - uses: docker/setup-buildx-action@v3

      - name: Build and push to ECR
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.login-ecr.outputs.registry }}/crypto-volatility:${{ github.sha }}
          provenance: false
          sbom: false

      - uses: hashicorp/setup-terraform@v3

      - name: Terraform init + apply
        working-directory: ./infra
        run: |
          terraform init
          terraform apply -auto-approve -var="image_tag=${{ github.sha }}"

      - name: Smoke test
        run: |
          API_URL=$(cd infra && terraform output -raw api_gateway_url)
          curl -f "${API_URL}/health"
          curl -f "${API_URL}/predict"
```

**Sources:** AWS Lambda deploying with GitHub Actions docs; DEV Community fix for InvalidParameterValueException; docker/build-push-action issue #773

### Anti-Patterns to Avoid

- **Hardcoding ECR registry URL:** Use `steps.login-ecr.outputs.registry` from the ECR login step.
- **`provenance: true` (default) for Lambda:** Causes `InvalidParameterValueException` — Lambda cannot pull OCI format images. Always set `provenance: false` + `sbom: false`.
- **Static AWS credentials in secrets:** Use OIDC role assumption. `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` require manual rotation and are a security liability.
- **Tagging with `latest` only:** Always include commit SHA tag alongside `latest` for traceability and rollback capability.
- **Running `terraform apply` without `-auto-approve` in CI:** Will hang waiting for interactive confirmation.
- **Smoke test without `-f` flag:** `curl` exits 0 even on 404/500 unless `-f` is passed. Use `curl -f` to propagate HTTP errors as exit codes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| AWS auth | Manual STS calls or scripted credential rotation | `aws-actions/configure-aws-credentials@v4` with OIDC | Official action handles STS assume role, credential env var injection, expiry management |
| ECR Docker login | `aws ecr get-login-password \| docker login` in script | `aws-actions/amazon-ecr-login@v2` | Official action; handles multi-region, outputs `registry` URL needed by build-push |
| Docker multi-platform build | Manual buildx commands | `docker/setup-buildx-action@v3` + `docker/build-push-action@v5` | Standard; build-push-action requires buildx setup |
| Terraform version pinning | Download and install script | `hashicorp/setup-terraform@v3` | Official; handles PATH, caching, version locking |

**Key insight:** Every step in this workflow has a corresponding official GitHub Action. Custom shell scripts should only be used for glue (extracting terraform outputs, constructing image tags), not for the main operations.

## Common Pitfalls

### Pitfall 1: Lambda rejects ECR image — InvalidParameterValueException

**What goes wrong:** Lambda fails to update function code with "The image manifest or layer media type for the source image does not match Docker Image Manifest V2 Schema 2"
**Why it happens:** `docker/build-push-action@v4+` defaults to OCI image format with provenance attestation. Lambda only supports Docker v2 schema.
**How to avoid:** Always set `provenance: false` and `sbom: false` on the build-push-action step.
**Warning signs:** CD succeeds for image push but `terraform apply` / `update-function-code` step fails with `InvalidParameterValueException`.

### Pitfall 2: OIDC fails — permission denied

**What goes wrong:** `configure-aws-credentials` fails with "Not authorized to perform sts:AssumeRoleWithWebIdentity"
**Why it happens:** Missing `permissions: id-token: write` in the workflow job, or IAM trust policy doesn't include correct GitHub subject claim.
**How to avoid:** Add `permissions: id-token: write` to the job block. Ensure the IAM role trust policy includes the correct `sub` claim filter (e.g., `repo:org/repo:ref:refs/heads/main`).
**Warning signs:** OIDC step fails immediately with authorization error, not a credential error.

### Pitfall 3: Terraform state mismatch after image push

**What goes wrong:** `terraform apply` sees no changes because the Lambda resource hasn't changed (same Terraform config) even though the ECR image changed.
**Why it happens:** Terraform tracks the `image_uri` in state. If you use a static tag like `latest`, Terraform sees the same URI and does nothing. Lambda continues running the old image.
**How to avoid:** Pass the commit SHA as the image tag via a Terraform variable (`-var="image_tag=${{ github.sha }}"`). Each merge produces a new image URI, forcing a Lambda update.
**Warning signs:** `terraform apply` reports "0 resources changed" but smoke test hits old behavior.

### Pitfall 4: Smoke test hits stale Lambda (cold start / propagation lag)

**What goes wrong:** Smoke test immediately after `terraform apply` returns 502 or timeout because Lambda hasn't fully propagated the new image.
**Why it happens:** Lambda container image deployments can take 10-30 seconds to become live after `update-function-code` completes.
**How to avoid:** Add a `aws lambda wait function-updated --function-name <name>` step between `terraform apply` and the smoke test, or poll with retry logic.
**Warning signs:** Smoke test flaky — passes sometimes, fails on first invocation.

### Pitfall 5: ruff not in requirements.txt / tests not found

**What goes wrong:** CI step `ruff check .` fails with "command not found", or `pytest tests/` fails with "no tests found"
**Why it happens:** `ruff` and `pytest` may not be in the main `requirements.txt` (they're dev dependencies).
**How to avoid:** Use a `requirements-dev.txt` that includes `ruff`, `pytest`, and install it in CI. Or use a `pyproject.toml` with `[project.optional-dependencies] dev = [...]`.
**Warning signs:** `pip install -r requirements.txt` succeeds but subsequent ruff/pytest commands not found.

## Code Examples

### Verified pattern: ECR image tag with SHA

```yaml
# Source: AWS prescriptive guidance + community patterns
env:
  ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
  IMAGE_TAG: ${{ github.sha }}

- name: Build and push
  uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: ${{ env.ECR_REGISTRY }}/crypto-volatility:${{ env.IMAGE_TAG }}
    provenance: false
    sbom: false
```

### Verified pattern: Lambda update wait before smoke test

```bash
# Source: AWS CLI docs — lambda wait
aws lambda wait function-updated \
  --function-name crypto-volatility-predictor \
  --region $AWS_REGION
```

### Verified pattern: curl smoke test with failure on non-200

```bash
# -f = fail on HTTP error (exits non-zero for 4xx/5xx)
# -s = silent (suppress progress meter)
# -o /dev/null = discard response body
curl -fsS -o /dev/null "${API_URL}/health" || (echo "Health check failed" && exit 1)
curl -fsS -o /dev/null "${API_URL}/predict" || (echo "Predict check failed" && exit 1)
```

### Verified pattern: OIDC permissions block

```yaml
# Source: GitHub Docs — Configuring OpenID Connect in Amazon Web Services
permissions:
  id-token: write   # Required for OIDC token
  contents: read    # Required for actions/checkout
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `AWS_ACCESS_KEY_ID` secrets | OIDC `role-to-assume` | 2021 (OIDC GA) | Eliminates long-lived credentials |
| `docker/build-push-action@v3` | `@v5` (current) | 2023-2024 | v4+ changed provenance default to true — breaking for Lambda |
| `actions/checkout@v2` | `@v4` | 2023 | Performance, Node 20 runtime |
| `hashicorp/setup-terraform@v2` | `@v3` | 2023 | Node 20, improved caching |

**Deprecated/outdated:**
- `docker/build-push-action@v3`: Still works but misses v4+ provenance issue — upgrade and explicitly set `provenance: false`
- `aws-actions/configure-aws-credentials@v1/v2`: Use v4; earlier versions use deprecated Node runtime
- `actions/checkout@v2`: Use v4 (Node 20); v2/v3 run on deprecated Node 16

## Open Questions

1. **IAM Role ARN storage**
   - What we know: The CD workflow needs an IAM role ARN to assume via OIDC
   - What's unclear: This project hasn't reached Phase 7 execution yet — the role and its ARN will be created during Phase 1 Terraform
   - Recommendation: Store as `AWS_ROLE_ARN` GitHub Actions secret; reference as `${{ secrets.AWS_ROLE_ARN }}` in workflow. Document in Phase 1 plan to output the OIDC role ARN.

2. **Terraform backend for CI**
   - What we know: `terraform apply` in CI requires access to the S3 backend and DynamoDB lock table
   - What's unclear: Whether the OIDC role has S3/DynamoDB permissions already set up in Phase 1
   - Recommendation: Phase 1 plan should provision the OIDC IAM role with permissions covering ECR push, Lambda update, S3 state, DynamoDB lock, and API Gateway read.

3. **`api_gateway_url` terraform output**
   - What we know: Smoke test needs the API Gateway URL
   - What's unclear: Whether `terraform output -raw api_gateway_url` will work from the `./infra` directory in the CD job
   - Recommendation: Add `api_gateway_url` as a named output in `infra/outputs.tf` (should already exist from Phase 4). Verify during plan.

## Validation Architecture

> Skipped — `workflow.nyquist_validation` not set in `.planning/config.json`

## Sources

### Primary (HIGH confidence)
- GitHub Docs (docs.github.com/en/actions) — Python CI, OIDC/OpenID Connect with AWS, workflow syntax
- AWS Lambda Docs (docs.aws.amazon.com/lambda/latest/dg/deploying-github-actions.html) — Official Lambda + GitHub Actions guidance
- DEV Community (dev.to/aws-builders) — Fix for InvalidParameterValueException; provenance: false requirement verified against docker/build-push-action issue #773
- AWS Prescriptive Guidance (docs.aws.amazon.com/prescriptive-guidance) — ECR + GitHub Actions + Terraform pattern

### Secondary (MEDIUM confidence)
- docker/build-push-action GitHub issue #773 — Confirms provenance default change in v3.3.0 as breaking for Lambda
- Community CI/CD guides (greeeg.com, medium.com) — Workflow structure patterns; cross-verified with official docs

### Tertiary (LOW confidence)
- None — all critical claims verified with official sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all actions are official or have official AWS equivalents; versions verified
- Architecture: HIGH — two-file CI/CD split is standard; patterns from official AWS guidance
- Pitfalls: HIGH — provenance issue verified with official GitHub issue + DEV Community; OIDC from official AWS docs

**Research date:** 2026-03-12
**Valid until:** 2026-06-12 (stable domain; GitHub Actions action versions rarely break)
