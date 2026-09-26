#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
List available models from the OpenAI-compatible endpoint.
"""

import json
import os
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import httpx
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Configuration
BASE_URL = os.getenv("AWS_OUTPOST_LLM_BASE_URL", "http://zld02251.vci.att.com:8000")
API_TOKEN = os.getenv("AWS_OUTPOST_LLM_API_TOKEN", "")

# Remove /v1 if present
BASE_URL = BASE_URL.rstrip("/").rstrip("/v1")

print("=" * 80)
print("🔍 Discovering Available Models")
print("=" * 80)
print(f"Endpoint: {BASE_URL}")
print(f"Token: {'*' * 20 if API_TOKEN else '(not set)'}")
print("=" * 80)

if not API_TOKEN or API_TOKEN == "your-api-token-here":
    print("\n❌ Error: API token not set!")
    print("Edit .env and set AWS_OUTPOST_LLM_API_TOKEN")
    sys.exit(1)

# Try /v1/models endpoint
models_endpoint = f"{BASE_URL}/v1/models"
print(f"\n📡 Querying: {models_endpoint}")

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Accept": "application/json",
}

try:
    response = httpx.get(models_endpoint, headers=headers, timeout=30.0)
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        
        if "data" in data:
            models = data["data"]
            print(f"\n✅ Found {len(models)} available model(s):\n")
            print("=" * 80)
            
            for i, model in enumerate(models, 1):
                model_id = model.get("id", "unknown")
                owned_by = model.get("owned_by", "unknown")
                created = model.get("created", "unknown")
                
                print(f"{i}. {model_id}")
                print(f"   Owner: {owned_by}")
                print(f"   Created: {created}")
                print("-" * 80)
            
            print("\n💡 Update your .env with one of these models:")
            print("   AWS_OUTPOST_LLM_MODEL=<model-id-from-above>")
        else:
            print("\n⚠️  Response doesn't contain 'data' field")
            print(json.dumps(data, indent=2))
    
    elif response.status_code == 404:
        print("\n❌ /v1/models endpoint not found")
        print("This endpoint may not support model listing")
        print("\nTrying to get error details from a test request...")
        
        # Try a test request to see what models are mentioned
        test_endpoint = f"{BASE_URL}/v1/chat/completions"
        test_payload = {
            "model": "test-model-discovery",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 1,
        }
        
        test_headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        }
        
        test_response = httpx.post(test_endpoint, headers=test_headers, json=test_payload, timeout=10.0)
        print(f"\nTest request status: {test_response.status_code}")
        print(test_response.text[:1000])
    
    else:
        print(f"\n❌ Error: HTTP {response.status_code}")
        print(response.text[:1000])

except httpx.ConnectError as e:
    print(f"\n❌ Connection Error: {e}")
    print("Check that the endpoint is reachable")

except Exception as e:
    print(f"\n❌ Error: {type(e).__name__}: {e}")

print("\n" + "=" * 80)
print("💡 Common model names to try:")
print("=" * 80)
print("  - gpt-4")
print("  - gpt-4-turbo")
print("  - gpt-3.5-turbo")
print("  - claude-3-opus")
print("  - claude-3-sonnet")
print("  - copilot (if this is GitHub Copilot)")
print("=" * 80)
