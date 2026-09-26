#!/usr/bin/env python3
"""
Interactive LLM endpoint test script.

Tests live connection to OpenAI-compatible endpoint and allows interactive Q&A.
"""

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def load_config():
    """Load configuration from .env file."""
    env_file = project_root / ".env"
    if not env_file.exists():
        print(f"❌ Error: .env file not found at {env_file}")
        print("Please create .env file with LLM configuration.")
        sys.exit(1)
    
    load_dotenv(env_file)
    
    # Get configuration with fallbacks
    config = {
        "base_url": os.getenv("AWS_OUTPOST_LLM_BASE_URL", "").rstrip("/"),
        "model": os.getenv("AWS_OUTPOST_LLM_MODEL", "gpt-4o-mini"),
        "api_token": os.getenv("AWS_OUTPOST_LLM_API_TOKEN", ""),
        "enabled": os.getenv("AWS_OUTPOST_LLM_ENABLED", "false").lower() == "true",
        "outbound_enabled": os.getenv("AWS_OUTPOST_LLM_OUTBOUND_ENABLED", "false").lower() == "true",
        "provider": os.getenv("AWS_OUTPOST_LLM_PROVIDER", ""),
    }
    
    return config


def validate_config(config):
    """Validate configuration before making requests."""
    issues = []
    
    if not config["base_url"]:
        issues.append("AWS_OUTPOST_LLM_BASE_URL is not set")
    elif not config["base_url"].startswith("https://"):
        issues.append("AWS_OUTPOST_LLM_BASE_URL must use HTTPS")

    if not config["enabled"]:
        issues.append("AWS_OUTPOST_LLM_ENABLED must be true")

    if not config["outbound_enabled"]:
        issues.append("AWS_OUTPOST_LLM_OUTBOUND_ENABLED must be true")

    if config["provider"] != "openai_compatible":
        issues.append("AWS_OUTPOST_LLM_PROVIDER must be openai_compatible")
    
    if not config["api_token"] or config["api_token"] == "replace-with-secret-manager-reference":
        issues.append("AWS_OUTPOST_LLM_API_TOKEN is not set or is placeholder")
    
    if not config["model"] or config["model"] == "approved-model-id":
        issues.append("AWS_OUTPOST_LLM_MODEL is not set or is placeholder")
    
    # Check if base_url ends with /v1 (common mistake)
    if config["base_url"].endswith("/v1"):
        issues.append(
            "⚠️  WARNING: BASE_URL ends with /v1 - this will be appended automatically!\n"
            f"   Current: {config['base_url']}\n"
            f"   Should be: {config['base_url'].rstrip('/v1')}"
        )
    
    return issues


def make_chat_request(config, user_message, system_message=None):
    """Make a chat completion request to the endpoint."""
    # Build endpoint URL (append /v1/chat/completions)
    endpoint = f"{config['base_url']}/v1/chat/completions"
    
    # Build messages
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": user_message})
    
    # Build request payload
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 500,
    }
    
    # Build headers
    headers = {
        "Authorization": f"Bearer {config['api_token']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    print(f"\n🔄 Sending request to: {endpoint}")
    print(f"📦 Model: {config['model']}")
    print(f"💬 Question: {user_message}")
    print("-" * 80)
    
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            response = client.post(endpoint, headers=headers, json=payload)
        
        print(f"✅ Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract answer
            if "choices" in data and len(data["choices"]) > 0:
                answer = data["choices"][0]["message"]["content"]
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                
                print(f"\n🤖 Answer:")
                print("-" * 80)
                print(answer)
                print("-" * 80)
                print(f"✓ Finish reason: {finish_reason}")
                
                # Show token usage if available
                if "usage" in data:
                    usage = data["usage"]
                    print(f"📊 Tokens: {usage.get('prompt_tokens', 0)} prompt + "
                          f"{usage.get('completion_tokens', 0)} completion = "
                          f"{usage.get('total_tokens', 0)} total")
                
                return answer
            else:
                print("❌ No choices in response")
                print(json.dumps(data, indent=2))
                return None
        
        elif response.status_code in (301, 302, 303, 307, 308):
            print(f"❌ Redirect detected: {response.headers.get('Location', 'unknown')}")
            print("The endpoint is trying to redirect. Check your BASE_URL configuration.")
            return None
        
        elif response.status_code == 401:
            print("❌ Authentication failed (401)")
            print("Check your AWS_OUTPOST_LLM_API_TOKEN")
            return None
        
        elif response.status_code == 404:
            print("❌ Not Found (404)")
            print("Check your BASE_URL - it may include /v1 when it shouldn't")
            print(f"Current endpoint: {endpoint}")
            return None
        
        else:
            print(f"❌ Error: HTTP {response.status_code}")
            try:
                error_data = response.json()
                print(json.dumps(error_data, indent=2))
            except Exception:
                print(response.text[:500])
            return None
    
    except httpx.ConnectError as e:
        print(f"❌ Connection Error: {e}")
        print("Check that the endpoint is reachable and the URL is correct")
        return None
    
    except httpx.TimeoutException:
        print("❌ Request timed out")
        print("The endpoint took too long to respond")
        return None
    
    except Exception as e:
        print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        return None


def interactive_mode(config):
    """Run interactive Q&A mode."""
    print("\n" + "=" * 80)
    print("🤖 Interactive LLM Test Mode")
    print("=" * 80)
    print("\nCommands:")
    print("  - Type your question and press Enter")
    print("  - Type 'quit' or 'exit' to stop")
    print("  - Type 'config' to show current configuration")
    print("=" * 80)
    
    while True:
        try:
            user_input = input("\n💬 Your question: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ("quit", "exit", "q"):
                print("\n👋 Goodbye!")
                break
            
            if user_input.lower() == "config":
                print("\n📋 Current Configuration:")
                print(f"  Base URL: {config['base_url']}")
                print(f"  Model: {config['model']}")
                print(f"  Token: {'*' * 20 if config['api_token'] else '(not set)'}")
                print(f"  Endpoint: {config['base_url']}/v1/chat/completions")
                continue
            
            # Make request
            make_chat_request(config, user_input)
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            print("\n\n👋 Goodbye!")
            break


def run_predefined_tests(config):
    """Run a set of predefined test questions."""
    print("\n" + "=" * 80)
    print("🧪 Running Predefined Tests")
    print("=" * 80)
    
    test_questions = [
        "What is the capital of France?",
        "Explain what Python is in one sentence.",
        "What is 15 + 27?",
        "Name three programming languages.",
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n\n{'=' * 80}")
        print(f"Test {i}/{len(test_questions)}")
        print('=' * 80)
        
        answer = make_chat_request(config, question)
        
        if not answer:
            print(f"\n⚠️  Test {i} failed")
            response = input("\nContinue with remaining tests? (y/n): ").strip().lower()
            if response != 'y':
                break
    
    print("\n" + "=" * 80)
    print("✅ Predefined tests complete")
    print("=" * 80)


def main():
    """Main entry point."""
    print("=" * 80)
    print("🚀 LLM Live Endpoint Test")
    print("=" * 80)
    
    # Load configuration
    print("\n📁 Loading configuration from .env...")
    config = load_config()
    
    # Validate configuration
    print("🔍 Validating configuration...")
    issues = validate_config(config)
    
    if issues:
        print("\n❌ Configuration Issues Found:")
        for issue in issues:
            print(f"  • {issue}")
        print("\nPlease fix these issues in your .env file before continuing.")
        sys.exit(1)
    
    print("✅ Configuration valid")
    print(f"\n📋 Configuration:")
    print(f"  Base URL: {config['base_url']}")
    print(f"  Model: {config['model']}")
    print(f"  Endpoint: {config['base_url']}/v1/chat/completions")
    
    # Choose mode
    print("\n" + "=" * 80)
    print("Select mode:")
    print("  1. Interactive mode (ask your own questions)")
    print("  2. Run predefined tests")
    print("  3. Both")
    print("=" * 80)
    
    choice = input("\nYour choice (1/2/3): ").strip()
    
    if choice == "1":
        interactive_mode(config)
    elif choice == "2":
        run_predefined_tests(config)
    elif choice == "3":
        run_predefined_tests(config)
        print("\n\nSwitching to interactive mode...\n")
        interactive_mode(config)
    else:
        print("Invalid choice. Defaulting to interactive mode.")
        interactive_mode(config)


if __name__ == "__main__":
    main()
