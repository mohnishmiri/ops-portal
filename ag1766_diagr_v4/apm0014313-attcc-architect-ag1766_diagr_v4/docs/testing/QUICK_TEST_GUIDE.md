# LLM Provider Contract Test Guide

This guide is for synthetic provider connectivity certification only. Do not
send client evidence, credentials, or production prompts to an unapproved
endpoint. The application requires HTTPS and does not support a runtime HTTP
bypass.

## Step 1: Configure an Approved HTTPS Profile

Use an untracked local `.env` only with a synthetic test token issued for the
approved environment. Never commit the file or paste a token into source code:

```bash
AWS_OUTPOST_LLM_ENABLED=true
AWS_OUTPOST_LLM_OUTBOUND_ENABLED=true
AWS_OUTPOST_LLM_PROVIDER=openai_compatible
AWS_OUTPOST_LLM_BASE_URL=https://approved-llm-gateway.example.internal
AWS_OUTPOST_LLM_MODEL=approved-model-id
AWS_OUTPOST_LLM_API_TOKEN=<synthetic-test-token>
```

## Step 2: Run the Test Script

```bash
python scripts/test_llm_live.py
```

## Step 3: Choose Mode

When prompted, choose:
- **Option 1:** Interactive mode (ask your own questions)
- **Option 2:** Run predefined tests (capital of France, etc.)
- **Option 3:** Both

## Example Session

```
🚀 LLM Live Endpoint Test
================================================================================

📁 Loading configuration from .env...
🔍 Validating configuration...
✅ Configuration valid

📋 Configuration:
  Base URL: https://approved-llm-gateway.example.internal
  Model: approved-model-id
  Endpoint: https://approved-llm-gateway.example.internal/v1/chat/completions

================================================================================
Select mode:
  1. Interactive mode (ask your own questions)
  2. Run predefined tests
  3. Both
================================================================================

Your choice (1/2/3): 1

================================================================================
🤖 Interactive LLM Test Mode
================================================================================

Commands:
  - Type your question and press Enter
  - Type 'quit' or 'exit' to stop
  - Type 'config' to show current configuration
================================================================================

💬 Your question: What is the capital of France?

🔄 Sending request to: https://approved-llm-gateway.example.internal/v1/chat/completions
📦 Model: gpt-4o-mini
💬 Question: What is the capital of France?
--------------------------------------------------------------------------------
✅ Status: 200

🤖 Answer:
--------------------------------------------------------------------------------
The capital of France is Paris.
--------------------------------------------------------------------------------
✓ Finish reason: stop
📊 Tokens: 15 prompt + 8 completion = 23 total

💬 Your question: quit

👋 Goodbye!
```

## Troubleshooting

### Error: "HTTPS is required for provider base URL"
The configured endpoint is not approved for outbound use. Obtain an HTTPS
gateway URL and complete the provider, security, and data-governance gates.
Do not modify application code to bypass this policy.

### Error: "404 Not Found"
**Cause:** The provider base path is incompatible with the adapter contract.

**Solution:** Remove `/v1` from BASE_URL:
```bash
# Configure the approved HTTPS origin/base path. The adapter owns the
# `/v1/chat/completions` operation path.
AWS_OUTPOST_LLM_BASE_URL=https://approved-llm-gateway.example.internal
```

### Error: "Authentication failed (401)"
**Cause:** Invalid or missing API token.

**Solution:** Check your token in `.env`:
```bash
AWS_OUTPOST_LLM_API_TOKEN=sk-your-actual-token-here
```

## Questions to Try

- What is the capital of France?
- Explain Python in one sentence
- What is 25 + 17?
- Name three programming languages
- What is the meaning of life?
- Write a haiku about coding
- Translate "Hello World" to Spanish
- What is the largest planet?

Enjoy testing! 🚀
