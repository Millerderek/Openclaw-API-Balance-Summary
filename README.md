# OpenClaw Skill: API Status & Balance Report

Checks all your AI provider API accounts for balances, rate limits, usage, and quota
status — then compiles a unified report in your OpenClaw chat.

---

## Quick Install

```bash
# 1. Copy the skill folder into OpenClaw's skills directory
cp -r api-status/ ~/openclaw/skills/

# 2. Install Python dependency (only httpx is required)
pip install httpx python-dotenv

# 3. Set your API keys (add to your .env or shell profile)
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GROQ_API_KEY="gsk_..."
export OPENROUTER_API_KEY="sk-or-..."
export DEEPSEEK_API_KEY="..."
export TOGETHER_API_KEY="..."
export MISTRAL_API_KEY="..."
export GEMINI_API_KEY="..."
# ... etc

# 4. Test the script directly
python ~/openclaw/skills/api-status/scripts/check_api_status.py

# 5. Use in OpenClaw chat:
# "Check all my API balances"
# "API status report"
# "Check my Anthropic and OpenAI limits"
```

---

## Trigger Phrases

Any of these will activate the skill in OpenClaw:

- "Check API status"
- "API balance report"
- "How much API credit do I have?"
- "Check my [provider] limits"
- "Provider usage report"
- "Token usage report"

---

## Supported Providers

| Provider | Balance | Rate Limits | Usage |
|----------|---------|-------------|-------|
| Anthropic | ❌ (console only) | ✅ (headers) | ❌ |
| OpenAI | ✅ | ✅ | ✅ |
| OpenRouter | ✅ | ✅ | ✅ |
| Deepseek | ✅ (CNY) | ❌ | ❌ |
| Moonshot/Kimi | ✅ (CNY) | ❌ | ❌ |
| Together AI | ✅ | ❌ | ❌ |
| Groq | ❌ (free tier) | ✅ | ❌ |
| Mistral | ❌ (console only) | ✅ | ❌ |
| Google Gemini | ❌ (console only) | ✅ | ❌ |
| Cohere | ❌ (console only) | ✅ | ❌ |
| Replicate | ❌ (console only) | ❌ | ❌ |
| Perplexity | ❌ (no API) | ✅ | ❌ |
| Hugging Face | ❌ (console only) | ❌ | ❌ |

---

## Script CLI Reference

```
python check_api_status.py [options]

Options:
  --json                  Output raw JSON instead of formatted report
  --providers p1 p2 ...   Only check specific providers
  --save                  Save report + JSON to ~/openclaw/reports/
  --threshold 10.0        Set low-balance warning threshold in USD (default: 5.00)

Examples:
  python check_api_status.py
  python check_api_status.py --providers openai groq anthropic
  python check_api_status.py --json
  python check_api_status.py --save --threshold 10.0
```

---

## Configuration

Copy `config.yaml.example` to `~/.openclaw/api-status.yaml` and edit as needed.
Key settings: `warn_below_usd`, `skip_providers`, `save_reports`, `cny_to_usd_rate`.

---

## Notes

- The skill is **read-only** — it never modifies anything
- Checks run **concurrently** for fast results
- Providers with no API key are listed as `UNCONFIGURED` and skipped gracefully
- Some providers (Anthropic, Google) don't expose billing via API — links to their
  consoles are provided instead
- CNY balances (Deepseek, Moonshot) are converted to approximate USD for display
