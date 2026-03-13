#!/usr/bin/env bash
# airflow_setup.sh — Idempotent Airflow 2.10.x install on EC2 with RDS PostgreSQL backend
#
# Usage:
#   export DB_PASS="<rds-password>"
#   export RDS_ENDPOINT="<rds-endpoint>"
#   export AIRFLOW_ADMIN_PASSWORD="<admin-password>"
#   bash scripts/airflow_setup.sh
#
# Or with positional args:
#   bash scripts/airflow_setup.sh <DB_PASS> <RDS_ENDPOINT> <AIRFLOW_ADMIN_PASSWORD>
#
# Requirements:
#   - INFRA-02 (swap) must be configured before running this script
#   - Python 3.11 must be installed
#   - psql client must be available

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse args / env
# ---------------------------------------------------------------------------
DB_PASS="${1:-${DB_PASS:?'DB_PASS env var or first positional arg required'}}"
RDS_ENDPOINT="${2:-${RDS_ENDPOINT:?'RDS_ENDPOINT env var or second positional arg required'}}"
AIRFLOW_ADMIN_PASSWORD="${3:-${AIRFLOW_ADMIN_PASSWORD:?'AIRFLOW_ADMIN_PASSWORD env var or third positional arg required'}}"

AIRFLOW_HOME="${AIRFLOW_HOME:-/opt/airflow}"
AIRFLOW_VERSION="2.10.4"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

echo "=== Airflow Setup: ${AIRFLOW_VERSION} ==="
echo "AIRFLOW_HOME: ${AIRFLOW_HOME}"
echo "RDS_ENDPOINT: ${RDS_ENDPOINT}"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
echo ""
echo "--- Pre-flight checks ---"

# Check swap is active (INFRA-02 must be done first)
SWAP_TOTAL=$(free -m | awk '/^Swap:/{print $2}')
if [ "${SWAP_TOTAL}" -eq 0 ]; then
    echo "ERROR: No swap configured. Run INFRA-02 (swap setup) before installing Airflow." >&2
    echo "       Airflow requires swap on t3.micro to avoid OOM during db migrate." >&2
    exit 1
fi
echo "PASS: Swap is active (${SWAP_TOTAL}MB)"

# Check Python 3.11
if ! python3.11 --version &>/dev/null; then
    echo "ERROR: Python 3.11 not found. Install with: sudo apt install python3.11" >&2
    exit 1
fi
PYTHON_VERSION=$(python3.11 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "PASS: Python ${PYTHON_VERSION} found"

# Check psql client
if ! command -v psql &>/dev/null; then
    echo "ERROR: psql client not found. Install with: sudo apt install postgresql-client" >&2
    exit 1
fi
echo "PASS: psql client found"

# ---------------------------------------------------------------------------
# Install Airflow with constraints (prevents dependency hell)
# ---------------------------------------------------------------------------
echo ""
echo "--- Installing Airflow ${AIRFLOW_VERSION} ---"

CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
echo "Constraint URL: ${CONSTRAINT_URL}"

# Upgrade pip first
python3.11 -m pip install --upgrade pip --quiet

# Install Airflow with postgres extra and constraint file
python3.11 -m pip install "apache-airflow[postgres]==${AIRFLOW_VERSION}" \
    --constraint "${CONSTRAINT_URL}" \
    --quiet

echo "PASS: Airflow ${AIRFLOW_VERSION} installed"

# ---------------------------------------------------------------------------
# Configure Airflow environment
# ---------------------------------------------------------------------------
echo ""
echo "--- Configuring Airflow ---"

# Create AIRFLOW_HOME directory
sudo mkdir -p "${AIRFLOW_HOME}/dags"
sudo mkdir -p "${AIRFLOW_HOME}/logs"
sudo mkdir -p "${AIRFLOW_HOME}/plugins"

# Create airflow system user if not exists
if ! id -u airflow &>/dev/null; then
    sudo useradd --system --home "${AIRFLOW_HOME}" --shell /bin/bash airflow
    echo "Created airflow system user"
fi

# Write env file (used by systemd EnvironmentFile)
sudo tee "${AIRFLOW_HOME}/airflow.env" > /dev/null <<EOF
AIRFLOW_HOME=${AIRFLOW_HOME}
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__CORE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:${DB_PASS}@${RDS_ENDPOINT}:5432/airflow
AIRFLOW__CORE__DAGS_FOLDER=${AIRFLOW_HOME}/dags
AIRFLOW__CORE__LOAD_EXAMPLES=False
AIRFLOW__WEBSERVER__WEB_SERVER_PORT=8080
AIRFLOW__SCHEDULER__CATCHUP_BY_DEFAULT=False
PROJECT_ROOT=${PROJECT_ROOT}
EOF

# Restrict permissions on env file (contains DB password)
sudo chmod 600 "${AIRFLOW_HOME}/airflow.env"
sudo chown airflow:airflow "${AIRFLOW_HOME}/airflow.env"
echo "PASS: Airflow environment file written to ${AIRFLOW_HOME}/airflow.env"

# ---------------------------------------------------------------------------
# Initialize RDS database
# ---------------------------------------------------------------------------
echo ""
echo "--- Initializing RDS database ---"

# Verify RDS connectivity
echo "Checking RDS connectivity at ${RDS_ENDPOINT}:5432..."
if ! PGPASSWORD="${DB_PASS}" psql -h "${RDS_ENDPOINT}" -U airflow -d postgres -c "\q" &>/dev/null; then
    echo "ERROR: Cannot connect to RDS at ${RDS_ENDPOINT}:5432" >&2
    echo "       Check RDS instance status, security group rules, and credentials." >&2
    exit 1
fi
echo "PASS: RDS connectivity confirmed"

# Create airflow database (idempotent)
PGPASSWORD="${DB_PASS}" createdb -h "${RDS_ENDPOINT}" -U airflow airflow 2>/dev/null \
    || echo "INFO: 'airflow' database already exists (skipping createdb)"

# Run Airflow DB migration (idempotent)
echo "Running airflow db migrate..."
export AIRFLOW_HOME
export AIRFLOW__CORE__SQL_ALCHEMY_CONN="postgresql+psycopg2://airflow:${DB_PASS}@${RDS_ENDPOINT}:5432/airflow"
export AIRFLOW__CORE__EXECUTOR=LocalExecutor
export AIRFLOW__CORE__LOAD_EXAMPLES=False
airflow db migrate
echo "PASS: Airflow DB migration complete"

# Create admin user (idempotent — skip if already exists)
airflow users create \
    --username admin \
    --password "${AIRFLOW_ADMIN_PASSWORD}" \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@example.com 2>/dev/null || true
echo "PASS: Admin user ensured"

# ---------------------------------------------------------------------------
# Deploy DAG
# ---------------------------------------------------------------------------
echo ""
echo "--- Deploying DAG ---"

mkdir -p "${AIRFLOW_HOME}/dags"
sudo cp "${PROJECT_ROOT}/dags/crypto_volatility_dag.py" "${AIRFLOW_HOME}/dags/"
sudo chown airflow:airflow "${AIRFLOW_HOME}/dags/crypto_volatility_dag.py"
echo "PASS: crypto_volatility_dag.py deployed to ${AIRFLOW_HOME}/dags/"

# ---------------------------------------------------------------------------
# Register systemd services
# ---------------------------------------------------------------------------
echo ""
echo "--- Registering systemd services ---"

INFRA_DIR="${PROJECT_ROOT}/infra/airflow"

sudo cp "${INFRA_DIR}/airflow-webserver.service" /etc/systemd/system/
sudo cp "${INFRA_DIR}/airflow-scheduler.service" /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable airflow-webserver airflow-scheduler
sudo systemctl start airflow-webserver airflow-scheduler

echo "PASS: Systemd services enabled and started"

# Give services a moment to start
sleep 3

# Report service status
echo ""
echo "--- Service Status ---"
systemctl status airflow-webserver --no-pager --lines=5 || true
echo ""
systemctl status airflow-scheduler --no-pager --lines=5 || true

echo ""
echo "=== Airflow setup complete ==="
echo "Web UI available at: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<EC2-public-IP>'):8080"
echo "Log in with username: admin"
