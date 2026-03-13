---
phase: 06-monitoring-and-drift-detection
plan: "02"
subsystem: infra
tags: [terraform, cloudwatch, sns, dashboard, monitoring, alarms]

# Dependency graph
requires:
  - phase: 06-monitoring-and-drift-detection
    provides: "Plan 06-01 publishes CryptoVolatility/Monitoring metrics that these alarms and dashboard consume"
  - phase: 01-infrastructure-foundation
    provides: "Terraform module structure, AWS provider config, alert_email variable already in root variables.tf"
provides:
  - "infra/modules/monitoring/: SNS ml-alerts topic, email subscription, accuracy_low alarm, drift_detected alarm, 5-widget CloudWatch dashboard"
  - "module.monitoring wired in infra/main.tf — active on next terraform apply"
affects:
  - "06-monitoring-and-drift-detection (Plan 06-01 SNS_TOPIC_ARN env var = monitoring.sns_topic_arn output)"
  - "spin_up.sh / operational runbooks referencing dashboard URL"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Terraform module pattern: monitoring module mirrors billing/serverless pattern (variables.tf + main.tf + outputs.tf)"
    - "jsonencode() for CloudWatch dashboard_body — avoids heredoc escaping issues with Terraform"
    - "treat_missing_data=notBreaching on ALL alarms — prevents false alerts before metrics flow from Plan 06-01"

key-files:
  created:
    - infra/modules/monitoring/main.tf
    - infra/modules/monitoring/variables.tf
    - infra/modules/monitoring/outputs.tf
  modified:
    - infra/main.tf

key-decisions:
  - "Separate SNS ml-alerts topic from serverless drift-alerts topic — different concerns: CloudWatch threshold alarms vs Python-level drift detection notifications"
  - "Dashboard uses project_name prefix for name (crypto-vol-monitoring) — consistent with all other resources in the project"
  - "alert_email variable reused from existing root variables.tf — already declared for billing alerts, serves dual purpose without duplication"
  - "5-widget layout: row 1 (y=0) rolling_accuracy + drift_score as primary operational signals; row 2 (y=6) model_version + prediction_latency + retrain_count as secondary"

patterns-established:
  - "CloudWatch namespace CryptoVolatility/Monitoring is the single source of truth for all monitoring metrics across Plan 06-01 (publish) and Plan 06-02 (alarm/dashboard)"

requirements-completed:
  - MON-04
  - MON-05

# Metrics
duration: 20min
completed: 2026-03-13
---

# Phase 6 Plan 02: Monitoring Terraform Module Summary

**CloudWatch dashboard (5-widget line graphs) and SNS-wired alarms for accuracy and drift, declared as Terraform module that activates once Plan 06-01 starts publishing to CryptoVolatility/Monitoring namespace**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-03-13T18:18:07Z
- **Completed:** 2026-03-13T18:39:02Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Monitoring Terraform module with SNS topic, email subscription, two CloudWatch alarms (accuracy_low + drift_detected), and a 5-widget dashboard covering all required metrics
- Both alarms have `treat_missing_data = "notBreaching"` — no false alerts before metrics flow
- Module wired into root `infra/main.tf`; `terraform validate` and `terraform plan` both pass showing 5 new monitoring resources

## Task Commits

1. **Task 1: Create monitoring Terraform module (SNS + alarms + dashboard)** - `111ff4c` (feat)
2. **Task 2: Wire monitoring module into root Terraform** - `3e0ccac` (feat)

**Plan metadata:** (pending final docs commit)

## Files Created/Modified

- `infra/modules/monitoring/variables.tf` - aws_region, project_name, alert_email, cloudwatch_namespace inputs
- `infra/modules/monitoring/main.tf` - SNS topic + subscription, accuracy_low alarm (LessThanThreshold 0.55, eval=2), drift_detected alarm (GreaterThanThreshold 0.15, eval=1), 5-widget dashboard via jsonencode
- `infra/modules/monitoring/outputs.tf` - sns_topic_arn, dashboard_url
- `infra/main.tf` - added module "monitoring" block (aws_region, project_name, alert_email)

## Decisions Made

- Separate SNS `ml-alerts` topic from the existing `drift-alerts` topic in the serverless module — the serverless topic handles Python-level drift detection events; this topic handles CloudWatch metric threshold crossings (different concern, different trigger path)
- Reused `alert_email` variable already present in `infra/variables.tf` (added in Phase 1 for billing alarms) — no duplication needed
- `treat_missing_data = "notBreaching"` on both alarms as specified in plan context — prevents alarm noise during the window between `terraform apply` and first metric publication by Plan 06-01

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — terraform validate and plan both passed on first attempt.

## User Setup Required

None — no external service configuration required for this infrastructure declaration. SNS email subscription confirmation will be required when `terraform apply` runs (AWS sends a confirmation email to `alert_email`).

## Next Phase Readiness

- Monitoring Terraform module is complete and ready for deployment
- Once `terraform apply` runs, AWS will send a subscription confirmation email to `alert_email` — user must click the confirm link before alarms can send notifications
- Dashboard URL will be available as `module.monitoring.dashboard_url` output after apply
- SNS topic ARN available as `module.monitoring.sns_topic_arn` — can be passed to Plan 06-01 Python code as `SNS_TOPIC_ARN` env var

---
*Phase: 06-monitoring-and-drift-detection*
*Completed: 2026-03-13*

## Self-Check: PASSED

- FOUND: infra/modules/monitoring/main.tf
- FOUND: infra/modules/monitoring/variables.tf
- FOUND: infra/modules/monitoring/outputs.tf
- FOUND: commit 111ff4c (feat: create monitoring Terraform module)
- FOUND: commit 3e0ccac (feat: wire monitoring module into root Terraform)
