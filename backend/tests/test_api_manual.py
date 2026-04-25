#!/usr/bin/env python
"""Quick manual test of the leadership dashboard API."""

import json

import requests

try:
    print("Testing leadership dashboard endpoint...")
    response = requests.get("http://localhost:8002/api/v1/dashboards/leadership", timeout=30)
    print(f"Status Code: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")

    if response.status_code == 200:
        data = response.json()
        print("\n✅ SUCCESS! Got data:")
        print(f"  - KPIs: {len(data.get('kpis', []))}")
        print(f"  - Cost trend points: {len(data.get('cost_trend', []))}")
        print(f"  - Top spenders: {len(data.get('top_spenders', []))}")
        print(f"  - Six month trend: {len(data.get('six_month_trend', []))}")
        print(f"  - Savings opportunities: ${data.get('savings_opportunities', 0)}")

        # Show first KPI as sample
        if data.get("kpis"):
            print("\nFirst KPI:")
            print(json.dumps(data["kpis"][0], indent=2))
    else:
        print(f"\n❌ ERROR: {response.text[:500]}")

except requests.exceptions.ConnectionError:
    print("❌ ERROR: Could not connect to backend on localhost:8002")
    print("   Make sure the backend is running (cd backend && bash start.sh)!")
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")
