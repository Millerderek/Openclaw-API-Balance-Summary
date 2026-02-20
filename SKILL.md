---
name: api-status
description: >
  Checks API balances, usage, rate limits, and quota status across all configured AI/service
  providers and compiles a unified report. Use when the user wants to audit API health,
  check spending, monitor token limits, or get a dashboard view of all provider accounts.
triggers:
  - "check api status"
  - "api balance report"
  - "check my api limits"
  - "provider usage report"
  - "how much api credit do i have"
  - "check anthropic/openai/google limits"
  - "api health check"
  - "token usage report"
---

# OpenClaw Skill: API Status & Balance Report

## Purpose

This skill queries all configured AI and service API providers, collects balance, usage,
rate limit, and quota data, then compiles a formatted status report for the user.

---

## Supported Providers

The skill checks the following providers when credentials are configured:

| Provider | Data Retrieved | Endpoint |
|----------|---------------|----------|
| **Anthropic** | Usage limits, rate limits (RPM/TPM), tier info | `https://api.anthropic.com/v1/` |
| **OpenAI** | Credit balance, usage, rate limits, subscription tier | `https://api.openai.com/v1/` |
| **Google Gemini** | Quota limits, RPM/TPD per model | `https://generativelanguage.googleapis.com/` |
| **Mistral AI** | Subscription, usage, token limits | `https://api.mistral.ai/v1/` |
| **Groq** | Rate limits, token limits per model | `https://api.groq.com/openai/v1/` |
| **Together AI** | Credit balance, rate limits | `https://api.together.xyz/v1/` |
| **Perplexity** | Credit balance, usage | `https://api.perplexity.ai/` |
| **Cohere** | Trial/production limits, API usage | `https://api.cohere.com/v1/` |
| **Replicate** | Billing, spending | `https://api.replicate.com/v1/` |
| **Moonshot/Kimi** | Balance, token quota | `https://api.moonshot.cn/v1/` |
| **OpenRouter** | Credit balance, usage, limits | `https://openrouter.ai/api/v1/` |
| **Hugging Face** | Rate limits, tier | `https://huggingface.co/api/` |
| **Deepseek** | Balance, usage | `https://api.deepseek.com/v1/` |

---

## Execution Workflow

### Step 1: Load Credentials

Read API keys from the environment configuration. Look in:
1. OpenClaw's `config.yaml` or `providers.yaml`
2. Environment variables (e.g., `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
3. `.env` file in the OpenClaw root directory
4. If running via script: accept a `--config` path argument

Only attempt checks for providers where a key is found. Skip unconfigured providers gracefully.

### Step 2: Query Each Provider

For each configured provider, call the appropriate endpoint(s). Use the provider-specific
methods described in the **Provider Details** section below.

- Set a **10-second timeout** per request
- On failure: log the error, mark provider as `ERROR`, continue to next provider
- Run provider checks **concurrently** where possible (async/parallel)

### Step 3: Normalize Data

Normalize each provider's response into a standard structure:

```json
{
  "provider": "OpenAI",
  "status": "OK",           // OK | WARNING | ERROR | UNCONFIGURED
  "checked_at": "2026-02-19T14:30:00Z",
  "balance": {
    "amount": 24.50,
    "currency": "USD",
    "type": "prepaid"       // prepaid | postpaid | subscription | free_tier
  },
  "limits": {
    "requests_per_minute": 500,
    "tokens_per_minute": 200000,
    "tokens_per_day": null,
    "requests_per_day": null
  },
  "usage": {
    "period": "2026-02",
    "tokens_used": 1850000,
    "requests_made": 4200,
    "cost_usd": 5.50
  },
  "tier": "tier-2",
  "warnings": [],
  "raw_notes": ""
}
```

Status thresholds:
- `WARNING`: balance < $5 OR usage > 80% of limit
- `ERROR`: API call failed, invalid key, or account suspended
- `OK`: Everything nominal

### Step 4: Generate Report

Compile all provider results into a formatted report. See **Report Format** section below.

### Step 5: Output

Present the report to the user in the chat. Optionally save to a file if the user requested it.

---

## Provider Details

### Anthropic

Anthropic does not expose a public balance API. Retrieve what's available via headers and
the usage endpoint.

```python
# Check rate limit headers from a lightweight API call
response = requests.get(
    "https://api.anthropic.com/v1/models",
    headers={
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
    }
)

# Extract from response headers:
# anthropic-ratelimit-requests-limit
# anthropic-ratelimit-requests-remaining
# anthropic-ratelimit-requests-reset
# anthropic-ratelimit-tokens-limit
# anthropic-ratelimit-tokens-remaining
# anthropic-ratelimit-tokens-reset
# anthropic-ratelimit-input-tokens-limit
# anthropic-ratelimit-output-tokens-limit
```

Note: For actual usage/spend data, direct the user to console.anthropic.com — the API
does not expose billing totals programmatically.

### OpenAI

```python
# Get subscription/billing info
requests.get(
    "https://api.openai.com/v1/dashboard/billing/subscription",
    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
)

# Get usage for current period
from datetime import date
start = date.today().replace(day=1).isoformat()
end = date.today().isoformat()
requests.get(
    f"https://api.openai.com/v1/dashboard/billing/usage?start_date={start}&end_date={end}",
    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
)

# Rate limits: check response headers on any API call
# x-ratelimit-limit-requests, x-ratelimit-remaining-requests
# x-ratelimit-limit-tokens, x-ratelimit-remaining-tokens
```

Note: OpenAI's billing endpoint may require org-level API key. If 401/403, note this in output.

### Google Gemini

```python
# List models to check access + rate limit headers
requests.get(
    f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
)

# Rate limits are per-model. Check headers:
# x-ratelimit-limit, x-ratelimit-remaining, x-ratelimit-reset
```

Google rate limits vary by model and are often in the response or quota console.
Direct user to console.cloud.google.com for detailed quotas.

### Groq

```python
# Models endpoint returns rate limit info in headers
response = requests.get(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {GROQ_API_KEY}"}
)

# Headers: x-ratelimit-limit-requests, x-ratelimit-remaining-requests
#          x-ratelimit-limit-tokens, x-ratelimit-remaining-tokens
#          x-ratelimit-reset-requests, x-ratelimit-reset-tokens
```

### OpenRouter

```python
# OpenRouter has a dedicated credits endpoint
response = requests.get(
    "https://openrouter.ai/api/v1/auth/key",
    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
)
# Returns: { "data": { "label": "...", "usage": 1234, "limit": null,
#            "is_free_tier": false, "rate_limit": { "requests": 200, "interval": "10s" } } }
```

### Together AI

```python
response = requests.get(
    "https://api.together.xyz/v1/organizations/me",
    headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"}
)
# May also check: /v1/users/me for credit info
```

### Mistral AI

```python
# Check workspace/usage
response = requests.get(
    "https://api.mistral.ai/v1/models",
    headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"}
)
# Rate limits in headers; billing at console.mistral.ai
```

### Deepseek

```python
response = requests.get(
    "https://api.deepseek.com/user/balance",
    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
)
# Returns: { "is_available": true, "balance_infos": [{ "currency": "CNY", "total_balance": "...", ... }] }
```

### Moonshot/Kimi

```python
response = requests.get(
    "https://api.moonshot.cn/v1/users/me/balance",
    headers={"Authorization": f"Bearer {MOONSHOT_API_KEY}"}
)
```

### Replicate

```python
response = requests.get(
    "https://api.replicate.com/v1/account",
    headers={"Authorization": f"Token {REPLICATE_API_TOKEN}"}
)
```

### Cohere

```python
# Use the /check-api-key endpoint for a lightweight validation
response = requests.post(
    "https://api.cohere.com/v1/check-api-key",
    headers={"Authorization": f"Bearer {COHERE_API_KEY}"}
)
# Rate limits from response headers
```

### Perplexity

```python
# No dedicated balance endpoint — make a minimal completion call and read headers
# Or check their dashboard at perplexity.ai/settings/api
```

---

## Report Format

Output a clean, scannable report. Use this structure:

```
╔══════════════════════════════════════════════════════════════╗
║         🔍 OpenClaw API Status Report                        ║
║         Generated: 2026-02-19 14:30 UTC                      ║
╚══════════════════════════════════════════════════════════════╝

📊 SUMMARY
──────────────────────────────────────────────────────────────
  Providers Checked:    8
  ✅ Healthy:           6
  ⚠️  Warnings:         1
  ❌ Errors:            1
  ⚫ Unconfigured:      5

──────────────────────────────────────────────────────────────
PROVIDER DETAILS
──────────────────────────────────────────────────────────────

✅ ANTHROPIC
   Tier:              Build (Tier 1)
   RPM Limit:         50 req/min  │  Remaining: 48
   TPM Limit:         40,000 tok/min  │  Remaining: 38,500
   Input TPM:         32,000  │  Output TPM: 8,000
   Resets in:         23s
   Billing:           → console.anthropic.com (not API-accessible)

✅ OPENAI
   Tier:              Tier 2
   Balance:           $24.50 USD (prepaid)
   Usage This Month:  $5.50 / ~$50 estimated cap
   RPM Limit:         500  │  Remaining: 498
   TPM Limit:         200,000  │  Remaining: 194,200
   Subscription:      Pay-as-you-go

⚠️  OPENROUTER                          [LOW BALANCE]
   Balance:           $2.30 USD
   Rate Limit:        200 req / 10s
   Free Tier:         No
   ⚠️  Warning: Balance below $5.00 threshold

✅ GROQ
   RPM Limit:         30  │  Remaining: 30
   TPM Limit:         14,400  │  Remaining: 14,400
   Reset (requests):  60s  │  Reset (tokens): 60s
   Billing:           Free tier / subscription via console

✅ TOGETHER AI
   Credit Balance:    $18.00 USD
   Status:            Active

✅ DEEPSEEK
   Balance:           ¥85.40 CNY (~$11.80 USD)
   Available:         Yes

❌ MISTRAL AI                           [API ERROR]
   Error:             401 Unauthorized — check API key
   Last Attempt:      2026-02-19 14:30:02 UTC

⚫ GEMINI          — not configured (no GEMINI_API_KEY found)
⚫ PERPLEXITY      — not configured
⚫ COHERE          — not configured
⚫ REPLICATE       — not configured
⚫ MOONSHOT        — not configured
⚫ HUGGING FACE    — not configured

──────────────────────────────────────────────────────────────
💡 RECOMMENDATIONS
──────────────────────────────────────────────────────────────
  • ⚠️  Top up OpenRouter — balance is low ($2.30)
  • ❌ Fix Mistral API key — returning 401 Unauthorized
  • ℹ️  Anthropic/Google billing details require web console access

Report saved to: ~/openclaw/reports/api-status-2026-02-19.txt
══════════════════════════════════════════════════════════════
```

---

## Script: `scripts/check_api_status.py`

This skill includes a ready-to-run Python script (see `scripts/check_api_status.py`) that:
- Loads keys from environment or `.env` file
- Runs all provider checks concurrently using `asyncio` + `httpx`
- Outputs JSON to stdout and formatted report to stderr/stdout
- Accepts `--json` flag for machine-readable output
- Accepts `--providers` flag to check specific providers only
- Accepts `--save` flag to save report to file

The agent can run this script directly and parse the output.

---

## Agent Execution Instructions

When this skill is triggered:

1. **Check if `scripts/check_api_status.py` exists** in the OpenClaw skills directory.
   If not, offer to create it (or generate inline code to run).

2. **Determine credential sources**: Ask the user where their API keys are stored if not obvious.

3. **Run the check**: Execute the script or make the API calls directly.

4. **Present results** using the report format above.

5. **Proactively flag issues**: Low balances, errors, expiring keys, or near-limit usage.

6. **Offer follow-up actions**:
   - "Would you like me to alert you when any balance drops below a threshold?"
   - "Should I save this report?"
   - "Want me to set up a scheduled check?"

---

## Error Handling

| Situation | Response |
|-----------|----------|
| No API key found | Mark as `UNCONFIGURED`, skip silently |
| 401 Unauthorized | Mark as `ERROR`, suggest checking key |
| 403 Forbidden | Mark as `ERROR`, note possible permission issue |
| 429 Rate Limited | Note irony, still mark as `OK` with rate limit info |
| Timeout (>10s) | Mark as `ERROR: TIMEOUT` |
| Endpoint not available | Mark with note, provide console link |

---

## Configuration

The skill reads optional configuration from `~/.openclaw/api-status.yaml`:

```yaml
api_status:
  # Balance warning thresholds (USD)
  warn_below_usd: 5.00
  
  # Usage warning threshold (percentage)
  warn_usage_pct: 80
  
  # Providers to skip even if configured
  skip_providers: []
  
  # Auto-save reports
  save_reports: true
  save_path: "~/openclaw/reports/"
  
  # Custom currency conversion for non-USD providers
  cny_to_usd_rate: 0.138
```

---

## Notes for OpenClaw Integration

- This skill is **read-only** — it never modifies anything, only reads status
- Safe to run frequently (respects provider rate limits by using lightweight endpoints)
- All API keys remain local — no data leaves except to the respective providers
- Designed to work with OpenClaw's multi-model agent system (Kimi K2.5 primary, with escalation)
- The skill can be scheduled via cron or OpenClaw's task scheduler for periodic reports
