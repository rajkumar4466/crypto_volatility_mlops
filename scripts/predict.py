"""Airflow wrapper: Trigger a prediction via the serving Lambda."""
import os
import sys
import requests

api_url = os.environ.get("API_GATEWAY_URL", "")
if not api_url:
    print("API_GATEWAY_URL not set — skipping predict task.")
    sys.exit(0)

url = f"{api_url.rstrip('/')}/predict"
print(f"Calling {url}...")
resp = requests.get(url, timeout=70)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")

if resp.status_code in (500, 503):
    print("Model or features not available yet — expected on first runs. Exiting gracefully.")
    sys.exit(0)

resp.raise_for_status()
