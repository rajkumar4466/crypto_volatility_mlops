# Phase 6: Monitoring and Drift Detection - Research

**Researched:** 2026-03-12
**Domain:** ML monitoring, statistical drift detection, CloudWatch metrics/alarms/dashboards, SNS alerting, Airflow REST API
**Confidence:** HIGH (all core APIs verified against official AWS/scipy/Airflow docs)

---

## Summary

Phase 6 closes the Continuous Training loop by wiring three monitoring signals into automated responses: (1) feature distribution drift detected via the KS test triggers an Airflow retrain DAG; (2) rolling accuracy computed from backfilled DynamoDB actuals provides a continuous model health metric; (3) all signals flow into CloudWatch custom metrics, SNS email alerts, and a CloudWatch dashboard. The technical surface for this phase is narrow but integration-dense — every component depends on data already flowing from Phases 2–5.

The standard stack is `scipy.stats.ks_2samp` for drift detection (already in the project's requirements.txt), `boto3` CloudWatch `put_metric_data` for custom metrics, `put_metric_alarm` with SNS ARN for threshold alerts, and a Terraform `aws_cloudwatch_dashboard` resource for the dashboard. The drift-to-retrain loop uses a `requests.post` call to Airflow's REST API at `/api/v2/dags/{dag_id}/dagRuns` — note Airflow 3.x moved from `/api/v1` to `/api/v2` and uses JWT bearer token authentication, not basic auth.

The dominant risk in this phase is KS-test alert fatigue. On volatile crypto data, a p-value threshold of 0.05 fires on nearly every DAG cycle. The project spec mandates p-value < 0.01 AND at least 2 features simultaneously drifted. This "2-of-N" gate must be implemented in code — not just the p-value check alone. CloudWatch free tier permits 10 custom metrics always-free; this phase requires exactly 5 (rolling_accuracy, drift_score, model_version, prediction_latency, retrain_count), which fits within budget.

**Primary recommendation:** Implement the monitor Airflow task as a single Python function in `src/monitoring/` with three clearly separated sub-functions — `compute_drift()`, `compute_rolling_accuracy()`, and `publish_metrics()` — then wire them together in the DAG task. Keep Airflow REST API calls idempotent by passing a unique `dag_run_id` based on the trigger timestamp to avoid duplicate retrain DAG runs.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MON-01 | Data drift detection via scipy KS-test on feature distributions (training vs recent, p-value < 0.01) | `scipy.stats.ks_2samp` verified in scipy 1.17.1 official docs; returns `statistic` and `pvalue`; "2+ features" gate must be coded explicitly |
| MON-02 | Model drift detection via rolling accuracy on backfilled actuals (alert if accuracy < 55%) | DynamoDB prediction log already includes `actual_label` backfill from SERV-05; query recent rows, compute accuracy, publish to CloudWatch |
| MON-03 | CloudWatch custom metrics: rolling_accuracy, drift_score, model_version, prediction_latency, retrain_count | `boto3` `put_metric_data` verified; all 5 metrics fit within 10-metric free tier; use Namespace `CryptoVolatility/Monitoring` |
| MON-04 | CloudWatch dashboard showing all metrics over time | Terraform `aws_cloudwatch_dashboard` resource with JSON `dashboard_body`; 5 line-graph widgets, one per metric |
| MON-05 | SNS topic with email subscription for drift/accuracy/latency alerts | `put_metric_alarm` with `AlarmActions=[sns_topic_arn]`; one alarm per metric threshold; SNS email subscription created in Terraform |
| MON-06 | Drift-triggered retraining: SNS → Airflow REST API to trigger retrain DAG | POST to `/api/v2/dags/{dag_id}/dagRuns` with JWT bearer token; triggered directly from monitor task (not via SNS Lambda); confirmed endpoint in Airflow 3.x |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy | 1.17.1 | `scipy.stats.ks_2samp` for KS drift test | Already in project; non-parametric, returns p-value directly; official docs verified |
| boto3 | latest | CloudWatch `put_metric_data`, `put_metric_alarm`; SNS `publish` | Standard AWS SDK; no alternatives |
| requests | latest | HTTP POST to Airflow REST API `/api/v2/dags/{dag_id}/dagRuns` | Already in project; simple JSON POST with Bearer auth |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas | 3.0.1 | DynamoDB result set → DataFrame for rolling accuracy computation | Already in project; used for backfilled actuals aggregation |
| Terraform aws_cloudwatch_dashboard | hashicorp/aws provider | Declare dashboard as code in `sns_cloudwatch.tf` | Avoids manual console dashboard creation; survives `terraform destroy/apply` cycles |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| scipy KS-test | Evidently AI drift library | Evidently adds a full monitoring server; unnecessary overhead for this project; KS-test is sufficient for 12 continuous features |
| CloudWatch alarms | Lambda → SNS publish from monitor task | Direct `put_metric_alarm` is simpler and doesn't require an additional Lambda; alarms are stateful and self-managing |
| Airflow REST API call from task | SNS → Lambda → Airflow API | Direct HTTP call from monitor task is simpler; SNS-to-Lambda chain adds latency and cost for no benefit |

**Installation:** All packages already in project requirements. No new installs needed for core logic.

---

## Architecture Patterns

### Recommended Project Structure
```
src/monitoring/
├── drift.py          # KS-test on recent vs reference feature distributions
├── accuracy.py       # Rolling accuracy computation from DynamoDB backfill
├── alerts.py         # SNS publish, CloudWatch put_metric_data/put_metric_alarm
└── retrain_trigger.py  # Airflow REST API call to trigger retrain DAG

terraform/
└── sns_cloudwatch.tf  # SNS topic, email sub, CloudWatch alarms, dashboard (already partial from Phase 1)
```

### Pattern 1: KS-test Drift Detection with 2-of-N Gate
**What:** Run `ks_2samp` on each of the 12 features comparing reference window (training data) vs recent window (last N DAG cycles). Count how many features drift (p < 0.01). Trigger alert only if 2 or more features drift simultaneously.
**When to use:** Every DAG monitor task invocation (every 30 minutes).
**Example:**
```python
# Source: scipy.stats.ks_2samp official docs (https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html)
from scipy.stats import ks_2samp
import numpy as np

def compute_drift(reference_df, recent_df, features: list[str], p_threshold=0.01, min_drifted=2):
    """
    Returns (drift_detected: bool, drift_score: float, drifted_features: list)
    drift_score = fraction of features with p < threshold
    """
    drifted = []
    for feat in features:
        stat, pvalue = ks_2samp(reference_df[feat].dropna(), recent_df[feat].dropna())
        if pvalue < p_threshold:
            drifted.append(feat)
    drift_score = len(drifted) / len(features)
    drift_detected = len(drifted) >= min_drifted
    return drift_detected, drift_score, drifted
```

### Pattern 2: Rolling Accuracy from DynamoDB Backfill
**What:** Query DynamoDB prediction log for rows where `actual_label` is not null (backfilled 30 min after prediction). Compare `prediction` vs `actual_label` over a rolling window.
**When to use:** Every DAG monitor task invocation.
**Example:**
```python
# boto3 DynamoDB scan with FilterExpression for rows with actual_label present
import boto3
from datetime import datetime, timedelta

def compute_rolling_accuracy(table_name: str, window_minutes: int = 60) -> float:
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    cutoff = (datetime.utcnow() - timedelta(minutes=window_minutes)).isoformat()
    response = table.scan(
        FilterExpression="#ts >= :cutoff AND attribute_exists(actual_label)",
        ExpressionAttributeNames={"#ts": "timestamp"},
        ExpressionAttributeValues={":cutoff": cutoff}
    )
    items = response["Items"]
    if not items:
        return None  # Not enough data yet
    correct = sum(1 for item in items if item["prediction"] == item["actual_label"])
    return correct / len(items)
```

### Pattern 3: CloudWatch Custom Metrics via put_metric_data
**What:** Publish all 5 monitoring metrics to a single CloudWatch namespace after each DAG cycle.
**When to use:** End of every monitor task invocation.
**Example:**
```python
# Source: boto3 put_metric_data official docs (https://docs.aws.amazon.com/boto3/latest/reference/services/cloudwatch/client/put_metric_data.html)
from datetime import datetime
import boto3

def publish_metrics(rolling_accuracy, drift_score, model_version, prediction_latency, retrain_count):
    cw = boto3.client('cloudwatch')
    now = datetime.utcnow()
    metrics = [
        {"MetricName": "rolling_accuracy", "Value": rolling_accuracy, "Unit": "None"},
        {"MetricName": "drift_score",      "Value": drift_score,      "Unit": "None"},
        {"MetricName": "model_version",    "Value": model_version,    "Unit": "Count"},
        {"MetricName": "prediction_latency","Value": prediction_latency,"Unit": "Milliseconds"},
        {"MetricName": "retrain_count",    "Value": retrain_count,    "Unit": "Count"},
    ]
    for m in metrics:
        m["Timestamp"] = now
    cw.put_metric_data(
        Namespace="CryptoVolatility/Monitoring",
        MetricData=metrics
    )
```

### Pattern 4: CloudWatch Alarm + SNS for Threshold Alerts
**What:** Create CloudWatch metric alarms that trigger SNS email when thresholds are breached. Use `put_metric_alarm` in Terraform (preferred) or boto3.
**When to use:** Defined once in Terraform; alarms are stateful and auto-trigger/clear.
**Example (Terraform in `sns_cloudwatch.tf`):**
```hcl
resource "aws_cloudwatch_metric_alarm" "accuracy_low" {
  alarm_name          = "crypto-rolling-accuracy-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "rolling_accuracy"
  namespace           = "CryptoVolatility/Monitoring"
  period              = 300   # 5 minutes
  statistic           = "Average"
  threshold           = 0.55
  alarm_description   = "Rolling accuracy dropped below 55%"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "drift_detected" {
  alarm_name          = "crypto-drift-detected"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "drift_score"
  namespace           = "CryptoVolatility/Monitoring"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0.15  # >15% of features drifted = 2 of 12
  alarm_description   = "Feature drift detected"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}
```

### Pattern 5: Airflow REST API DAG Trigger (Airflow 3.x)
**What:** POST to `/api/v2/dags/{dag_id}/dagRuns` with a Bearer token to trigger immediate retraining when drift is detected.
**Critical:** Airflow 3.x uses `/api/v2` (NOT `/api/v1`). Authentication uses JWT Bearer token, not basic auth. The `logical_date` field defaults to `None` in Airflow 3.x if omitted.
**When to use:** At the end of `compute_drift()` if `drift_detected=True`.
**Example:**
```python
# Source: Airflow 3.x upgrade notes + REST API docs
import requests
import os
from datetime import datetime

def trigger_retrain_dag(dag_id: str, airflow_host: str, airflow_token: str):
    """Trigger retrain DAG via Airflow 3.x REST API."""
    dag_run_id = f"drift_triggered_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"
    url = f"{airflow_host}/api/v2/dags/{dag_id}/dagRuns"
    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {airflow_token}",
        },
        json={
            "dag_run_id": dag_run_id,
            "conf": {"trigger_reason": "drift_detected"},
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
```

### Pattern 6: CloudWatch Dashboard via Terraform
**What:** Declare a `aws_cloudwatch_dashboard` resource in Terraform with a JSON `dashboard_body` containing 5 line-graph widgets (one per metric). Dashboard survives `terraform destroy/apply` cycles.
**When to use:** Defined once in `terraform/sns_cloudwatch.tf`.
**Example:**
```hcl
resource "aws_cloudwatch_dashboard" "mlops_monitoring" {
  dashboard_name = "CryptoVolatilityMLOps"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          metrics = [["CryptoVolatility/Monitoring", "rolling_accuracy"]],
          period  = 300, stat = "Average", region = var.aws_region,
          title   = "Rolling Model Accuracy"
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          metrics = [["CryptoVolatility/Monitoring", "drift_score"]],
          period  = 300, stat = "Maximum", region = var.aws_region,
          title   = "Feature Drift Score"
        }
      },
      # ... model_version, prediction_latency, retrain_count widgets
    ]
  })
}
```

### Anti-Patterns to Avoid
- **KS-test with p < 0.05 only:** On volatile crypto data this fires on nearly every cycle. ALWAYS combine with the 2-of-N gate.
- **Triggering retrain without idempotent `dag_run_id`:** Repeated calls without unique IDs can create duplicate DAG runs. Always set `dag_run_id` to a timestamp-based unique string.
- **Publishing metrics with `None` values:** If `compute_rolling_accuracy()` returns `None` (not enough data), skip `put_metric_data` for that metric rather than publishing `None` (which raises `InvalidParameterValueException`).
- **Creating CloudWatch alarms in Python at runtime:** Alarms should be Terraform resources, not created by the monitor task. Runtime alarm creation wastes API calls and is not idempotent.
- **Using Airflow 2.x `/api/v1` endpoint:** Airflow 3.x returns 404 on `/api/v1`. Use `/api/v2` exclusively.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Distribution comparison | Custom cumulative histogram diff | `scipy.stats.ks_2samp` | Non-parametric, handles different sample sizes, returns calibrated p-value |
| Threshold alerting | SNS publish inside monitor task on threshold check | CloudWatch metric alarm + SNS action | Alarms are stateful (only fire on state change), prevent duplicate alerts, self-manage |
| Dashboard persistence | boto3 `put_dashboard` call from Python | Terraform `aws_cloudwatch_dashboard` | Dashboard survives `terraform apply` re-runs, is version-controlled |

**Key insight:** The monitor task's only job is `put_metric_data`. Alerting logic lives in CloudWatch alarms (Terraform), not in Python code. This prevents alert flooding from transient metric spikes.

---

## Common Pitfalls

### Pitfall 1: KS-test Alert Fatigue on Crypto Data
**What goes wrong:** p < 0.05 fires on nearly every DAG run for crypto features due to regime volatility. Constant drift alerts → constant retraining → oscillating model quality → alert fatigue.
**Why it happens:** Crypto feature distributions shift continuously, not just during regime changes. 0.05 is calibrated for stable domains.
**How to avoid:** Use p < 0.01 AND require 2+ simultaneous feature drifts before setting drift_score above alert threshold. Confirmed project decision per STATE.md.
**Warning signs:** drift_score metric is consistently above threshold; retrain_count in CloudWatch grows > 2 per hour.

### Pitfall 2: DynamoDB Scan Performance for Rolling Accuracy
**What goes wrong:** DynamoDB `scan` with `FilterExpression` reads the full table and then filters — slow and expensive at scale. At 30-min intervals with 288 items/day, this is acceptable, but careless scan growth can create latency issues.
**Why it happens:** DynamoDB scan is O(table size), not O(result set). Without a GSI on timestamp, every scan reads all records.
**How to avoid:** Limit scan to a time window (e.g., last 2 hours). Add `Limit=100` to cap scan cost. At this project's data volume, a full scan on a small table is fine.
**Warning signs:** Monitor task duration exceeds 60 seconds; DynamoDB consumed read capacity exceeds free tier.

### Pitfall 3: Missing Data in CloudWatch Before Alarm Triggers
**What goes wrong:** CloudWatch alarms with `treat_missing_data=missing` (default) go into ALARM state when no data is published — e.g., on the first DAG run before DynamoDB has any backfilled actuals.
**Why it happens:** The monitor task may skip `put_metric_data` for `rolling_accuracy` until enough backfilled rows exist. Missing data is treated as ALARM by default.
**How to avoid:** Set `treat_missing_data = "notBreaching"` on all alarms. This treats gaps as OK rather than triggering false alerts during initial setup.
**Warning signs:** SNS emails received within minutes of deploying, before any predictions have been made.

### Pitfall 4: Airflow JWT Token Management
**What goes wrong:** The Airflow REST API in 3.x requires a JWT Bearer token, not basic auth. Hardcoding the token in DAG code leaks credentials. Token expiry causes `trigger_retrain_dag()` to fail silently.
**Why it happens:** Airflow 3.x API-first architecture requires token-based auth. The token is obtained from `/auth/token` endpoint.
**How to avoid:** Store the Airflow API token in AWS SSM Parameter Store or Airflow Variables. Fetch at task runtime. Add HTTP 401 error handling in `trigger_retrain_dag()` to log clearly when token expires.
**Warning signs:** 401 responses from Airflow REST API in monitor task logs.

### Pitfall 5: CloudWatch Free Tier Metric Limit
**What goes wrong:** Publishing more than 10 custom metrics crosses out of the always-free CloudWatch tier and incurs $0.30/metric/month charges.
**Why it happens:** Developers add per-feature drift metrics (12 features × 1 metric each = 12 metrics) in addition to the 5 aggregate metrics.
**How to avoid:** Publish only the 5 aggregate metrics specified in MON-03: `rolling_accuracy`, `drift_score`, `model_version`, `prediction_latency`, `retrain_count`. Individual feature p-values should be logged to CloudWatch Logs (free), not custom metrics.
**Warning signs:** AWS Cost Explorer shows CloudWatch charges; `ListMetrics` returns more than 10 metrics in `CryptoVolatility/Monitoring` namespace.

---

## Code Examples

Verified patterns from official sources:

### scipy.stats.ks_2samp Return Values
```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html
from scipy.stats import ks_2samp
result = ks_2samp(data1, data2)
# result.statistic  — KS statistic (max distance between ECDFs)
# result.pvalue     — two-sided p-value; reject null (same distribution) if pvalue < threshold
# result.statistic_location — observation where max distance occurs
# result.statistic_sign     — which CDF is larger (+1 or -1)
stat, pvalue = ks_2samp(reference_samples, recent_samples)
if pvalue < 0.01:
    print(f"Drift detected: KS={stat:.4f}, p={pvalue:.4f}")
```

### boto3 put_metric_data (verified API)
```python
# Source: https://docs.aws.amazon.com/boto3/latest/reference/services/cloudwatch/client/put_metric_data.html
import boto3
from datetime import datetime

cw = boto3.client('cloudwatch')
cw.put_metric_data(
    Namespace='CryptoVolatility/Monitoring',
    MetricData=[
        {
            'MetricName': 'rolling_accuracy',
            'Value': 0.62,
            'Unit': 'None',
            'Timestamp': datetime.utcnow(),
        }
    ]
)
# Notes:
# - Do NOT use namespaces starting with 'AWS/'
# - Max 1000 metrics per request (well within our 5-metric batch)
# - Metrics appear in CloudWatch within 15 minutes of first publish
# - Timestamp must be within 2 weeks past to 2 hours future
```

### boto3 put_metric_alarm with SNS action (verified API)
```python
# Source: https://docs.aws.amazon.com/boto3/latest/guide/cw-example-creating-alarms.html
cw.put_metric_alarm(
    AlarmName='crypto-rolling-accuracy-low',
    ComparisonOperator='LessThanThreshold',
    EvaluationPeriods=2,
    MetricName='rolling_accuracy',
    Namespace='CryptoVolatility/Monitoring',
    Period=300,
    Statistic='Average',
    Threshold=0.55,
    ActionsEnabled=True,
    AlarmDescription='Rolling accuracy below 55%',
    AlarmActions=['arn:aws:sns:REGION:ACCOUNT:crypto-volatility-alerts'],
    TreatMissingData='notBreaching',
)
# Better: define this in Terraform (aws_cloudwatch_metric_alarm) rather than boto3 at runtime
```

### Airflow 3.x REST API dag trigger (verified endpoint)
```python
# Source: Airflow 3.x upgrade notes — /api/v1 removed, /api/v2 required
# https://airflow.apache.org/docs/apache-airflow/stable/installation/upgrading_to_airflow3.html
import requests
from datetime import datetime

def trigger_retrain(airflow_base_url: str, dag_id: str, jwt_token: str):
    url = f"{airflow_base_url}/api/v2/dags/{dag_id}/dagRuns"
    run_id = f"drift_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"},
        json={"dag_run_id": run_id, "conf": {"trigger_reason": "drift"}},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Airflow REST API `/api/v1` | `/api/v2` with JWT Bearer auth | Airflow 3.0 (2025) | All programmatic trigger code must use `/api/v2`; basic auth deprecated |
| CloudWatch `execution_date` in dagRuns body | `logical_date` (defaults to None in Airflow 3.x if omitted) | Airflow 2.2+ | Omitting `logical_date` is fine; Airflow auto-assigns |
| Lambda INIT billing | Lambda INIT phase now billed (August 2025) | August 2025 | Monitor task's HTTP call to Lambda keeps it warm; cold start cost now non-zero |

**Deprecated/outdated:**
- `/api/v1` Airflow endpoint: removed entirely in Airflow 3.0. Any code or documentation referencing `/api/v1/dags/.../dagRuns` must be updated to `/api/v2`.
- Airflow basic auth for REST API: replaced by JWT Bearer tokens in Airflow 3.x API-first architecture.

---

## Open Questions

1. **Airflow JWT token acquisition**
   - What we know: Airflow 3.x REST API requires JWT Bearer token; token obtained from `/auth/token` endpoint
   - What's unclear: Does Airflow on EC2 (self-managed, not MWAA/Astro) expose `/auth/token` with simple username/password, or does it require an external identity provider? The upgrade docs focus on MWAA/Astronomer flows.
   - Recommendation: During Phase 6 implementation, test `POST /auth/token` with Airflow admin credentials on the EC2 instance. Fallback: use Airflow's `SimpleAuthManager` API token generation for self-managed deployments.

2. **Reference window for KS-test**
   - What we know: KS-test requires a reference distribution. The project uses "training data" as reference.
   - What's unclear: Training data is recomputed every DAG cycle. Should reference be pinned to the last successful promotion's training distribution (stored in S3) or the most recent training data?
   - Recommendation: Store reference feature statistics (mean, std, raw sample) to S3 at each model promotion event. KS-test in monitor task compares recent 30-minute window vs the pinned reference from last promotion. This makes drift relative to the currently-deployed model's training distribution.

3. **model_version metric encoding**
   - What we know: CloudWatch metrics are numeric. `model_version` is stored as a string in S3 (e.g., `v12`).
   - What's unclear: How to encode a version string as a numeric CloudWatch metric.
   - Recommendation: Extract the integer from `v{n}` (e.g., `v12` → `12`) and publish as Count. This lets the dashboard show version progression over time.

---

## Validation Architecture

No `config.json` found in `.planning/`. Skipping Validation Architecture section (nyquist_validation not configured).

---

## Sources

### Primary (HIGH confidence)
- [scipy.stats.ks_2samp — SciPy v1.17.0 Manual](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html) — function signature, parameters, return values, interpretation
- [boto3 put_metric_data official docs](https://docs.aws.amazon.com/boto3/latest/reference/services/cloudwatch/client/put_metric_data.html) — full API signature, MetricData structure, limits (1000/request, 1MB, 15-min appearance delay)
- [boto3 CloudWatch creating alarms guide](https://docs.aws.amazon.com/boto3/latest/guide/cw-example-creating-alarms.html) — put_metric_alarm with AlarmActions SNS
- [Airflow 3.x upgrade notes](https://airflow.apache.org/docs/apache-airflow/stable/installation/upgrading_to_airflow3.html) — `/api/v1` removed, `/api/v2` required, JWT Bearer auth
- [Terraform aws_cloudwatch_dashboard registry](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_dashboard) — dashboard_body JSON structure
- [boto3 SNS official docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sns.html) — publish() method
- [AWS SNS + CloudWatch alarm integration (2026)](https://oneuptime.com/blog/post/2026-02-12-sns-notifications-cloudwatch-alarms/view) — alarm → SNS → email pattern

### Secondary (MEDIUM confidence)
- [Airflow REST API trigger DAG (Astronomer docs)](https://www.astronomer.io/docs/astro/airflow-api) — POST dagRuns body schema
- [dzone.com: ML Model Accuracy Automated Drift Detection](https://dzone.com/articles/ml-model-accuracy-automated-drift-detection) — KS-test MLOps integration pattern
- [CloudWatch dashboard via Terraform (2026)](https://oneuptime.com/blog/post/2026-02-12-cloudwatch-dashboards-terraform/view) — Terraform JSON widget examples
- [How to Build Data Drift Detection Details (2026)](https://oneuptime.com/blog/post/2026-01-30-data-drift-detection/view) — current drift patterns

### Tertiary (LOW confidence)
- STATE.md project decision: KS p-value < 0.01 and "2+ features" rule — community-calibrated, not formally validated against BTC historical data

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — scipy, boto3, requests all verified against official docs; no version ambiguity
- Architecture: HIGH — CloudWatch/SNS patterns are stable AWS APIs; Airflow v2/v3 endpoint change verified
- Pitfalls: MEDIUM — alert fatigue threshold calibrated from community experience; DynamoDB scan behavior is documented but scale-specific

**Research date:** 2026-03-12
**Valid until:** 2026-06-12 (stable AWS/scipy APIs; re-verify Airflow 3.x JWT auth for self-managed instances at implementation time)
