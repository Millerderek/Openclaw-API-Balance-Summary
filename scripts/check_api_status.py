#!/usr/bin/env python3
"""
OpenClaw API Status Checker
Checks balances, rate limits, and usage across all configured AI providers.

Usage:
    python check_api_status.py                    # Full report
    python check_api_status.py --json             # JSON output only
    python check_api_status.py --providers openai groq  # Specific providers
    python check_api_status.py --save             # Save report to file
    python check_api_status.py --threshold 10.0   # Custom low-balance warning ($)
"""

import asyncio
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx python-dotenv", file=sys.stderr)
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

TIMEOUT = 10.0  # seconds per request
DEFAULT_WARN_BALANCE_USD = 5.00
DEFAULT_WARN_USAGE_PCT = 80
CNY_TO_USD = 0.138  # approximate, for display purposes

PROVIDERS_CONFIG = {
    "anthropic":   {"env": "ANTHROPIC_API_KEY",    "label": "Anthropic"},
    "openai":      {"env": "OPENAI_API_KEY",        "label": "OpenAI"},
    "gemini":      {"env": "GEMINI_API_KEY",        "label": "Google Gemini"},
    "groq":        {"env": "GROQ_API_KEY",          "label": "Groq"},
    "mistral":     {"env": "MISTRAL_API_KEY",       "label": "Mistral AI"},
    "together":    {"env": "TOGETHER_API_KEY",      "label": "Together AI"},
    "openrouter":  {"env": "OPENROUTER_API_KEY",    "label": "OpenRouter"},
    "perplexity":  {"env": "PERPLEXITY_API_KEY",    "label": "Perplexity"},
    "cohere":      {"env": "COHERE_API_KEY",        "label": "Cohere"},
    "replicate":   {"env": "REPLICATE_API_TOKEN",   "label": "Replicate"},
    "moonshot":    {"env": "MOONSHOT_API_KEY",      "label": "Moonshot/Kimi"},
    "deepseek":    {"env": "DEEPSEEK_API_KEY",      "label": "Deepseek"},
    "huggingface": {"env": "HUGGINGFACE_API_KEY",   "label": "Hugging Face"},
}


# ─────────────────────────────────────────────
# Result Data Structure
# ─────────────────────────────────────────────

def make_result(provider_id: str, label: str) -> dict:
    return {
        "provider_id": provider_id,
        "provider": label,
        "status": "OK",          # OK | WARNING | ERROR | UNCONFIGURED
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "balance": None,
        "limits": {
            "requests_per_minute": None,
            "tokens_per_minute": None,
            "tokens_per_day": None,
            "requests_per_day": None,
            "input_tokens_per_minute": None,
            "output_tokens_per_minute": None,
        },
        "remaining": {
            "requests": None,
            "tokens": None,
            "resets_in_seconds": None,
        },
        "usage": None,
        "tier": None,
        "warnings": [],
        "error": None,
        "console_url": None,
        "notes": [],
    }


def add_warning(result: dict, msg: str):
    result["warnings"].append(msg)
    result["status"] = "WARNING"


def set_error(result: dict, msg: str):
    result["error"] = msg
    result["status"] = "ERROR"


def parse_rate_limit_headers(headers: dict, result: dict, prefix: str = "x-ratelimit"):
    """Parse common rate limit headers from API responses."""
    h = {k.lower(): v for k, v in headers.items()}

    def get(key):
        return h.get(f"{prefix}-{key}")

    lim_req = get("limit-requests")
    lim_tok = get("limit-tokens")
    rem_req = get("remaining-requests")
    rem_tok = get("remaining-tokens")
    reset_req = get("reset-requests")

    if lim_req:
        result["limits"]["requests_per_minute"] = int(lim_req)
    if lim_tok:
        result["limits"]["tokens_per_minute"] = int(lim_tok)
    if rem_req:
        result["remaining"]["requests"] = int(rem_req)
    if rem_tok:
        result["remaining"]["tokens"] = int(rem_tok)
    if reset_req:
        result["remaining"]["resets_in_seconds"] = reset_req


# ─────────────────────────────────────────────
# Provider Checkers
# ─────────────────────────────────────────────

async def check_anthropic(key: str, client: httpx.AsyncClient) -> dict:
    result = make_result("anthropic", "Anthropic")
    result["console_url"] = "https://console.anthropic.com"
    try:
        resp = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code not in (200, 429):
            set_error(result, f"HTTP {resp.status_code}")
            return result

        h = {k.lower(): v for k, v in resp.headers.items()}

        def ah(key):
            return h.get(f"anthropic-ratelimit-{key}")

        rpm = ah("requests-limit")
        tpm = ah("tokens-limit")
        rem_req = ah("requests-remaining")
        rem_tok = ah("tokens-remaining")
        reset = ah("requests-reset")
        inp_tpm = ah("input-tokens-limit")
        out_tpm = ah("output-tokens-limit")

        if rpm:  result["limits"]["requests_per_minute"] = int(rpm)
        if tpm:  result["limits"]["tokens_per_minute"] = int(tpm)
        if inp_tpm: result["limits"]["input_tokens_per_minute"] = int(inp_tpm)
        if out_tpm: result["limits"]["output_tokens_per_minute"] = int(out_tpm)
        if rem_req: result["remaining"]["requests"] = int(rem_req)
        if rem_tok: result["remaining"]["tokens"] = int(rem_tok)
        if reset:   result["remaining"]["resets_in_seconds"] = reset

        result["notes"].append("Billing/balance not available via API — check console.anthropic.com")

        # Determine tier from TPM
        if tpm:
            t = int(tpm)
            if t <= 40000:    result["tier"] = "Tier 1 (Build)"
            elif t <= 400000: result["tier"] = "Tier 2 (Scale)"
            elif t <= 2000000: result["tier"] = "Tier 3"
            else:              result["tier"] = "Tier 4+"

    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_openai(key: str, client: httpx.AsyncClient, warn_usd: float) -> dict:
    result = make_result("openai", "OpenAI")
    result["console_url"] = "https://platform.openai.com/usage"
    try:
        # Subscription info
        sub_resp = await client.get(
            "https://api.openai.com/v1/dashboard/billing/subscription",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if sub_resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if sub_resp.status_code == 403:
            result["notes"].append("Billing endpoint requires org-level key; rate limits only")
        elif sub_resp.status_code == 200:
            sub = sub_resp.json()
            hard_limit = sub.get("hard_limit_usd") or sub.get("system_hard_limit_usd")
            plan = sub.get("plan", {}).get("title", "unknown")
            result["tier"] = plan
            if hard_limit:
                result["balance"] = {
                    "amount": float(hard_limit),
                    "currency": "USD",
                    "type": "limit",
                    "label": "Monthly hard limit"
                }

        # Usage this month
        today = datetime.now()
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        usage_resp = await client.get(
            f"https://api.openai.com/v1/dashboard/billing/usage?start_date={start}&end_date={end}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if usage_resp.status_code == 200:
            usage = usage_resp.json()
            total_cents = usage.get("total_usage", 0)
            result["usage"] = {
                "period": f"{today.year}-{today.month:02d}",
                "cost_usd": round(total_cents / 100, 4),
            }

        # Rate limits from a lightweight call
        models_resp = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if models_resp.status_code == 200:
            parse_rate_limit_headers(dict(models_resp.headers), result)

    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_groq(key: str, client: httpx.AsyncClient) -> dict:
    result = make_result("groq", "Groq")
    result["console_url"] = "https://console.groq.com"
    try:
        resp = await client.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code == 200:
            parse_rate_limit_headers(dict(resp.headers), result)
            result["notes"].append("Groq is free tier / subscription — no balance API")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_openrouter(key: str, client: httpx.AsyncClient, warn_usd: float) -> dict:
    result = make_result("openrouter", "OpenRouter")
    result["console_url"] = "https://openrouter.ai/account"
    try:
        resp = await client.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            usage = data.get("usage", 0)        # in USD
            limit = data.get("limit")           # null = unlimited
            is_free = data.get("is_free_tier", False)
            rate_limit = data.get("rate_limit", {})

            # Also check /api/v1/credits for total balance
            credits_resp = await client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {key}"},
                timeout=TIMEOUT,
            )
            total_credits = None
            if credits_resp.status_code == 200:
                credits_data = credits_resp.json().get("data", {})
                total_credits = credits_data.get("total_credits")
                credits_usage = credits_data.get("total_usage", 0)
                if total_credits is not None:
                    usage = credits_usage  # Use credits endpoint usage if available

            # Calculate balance
            if total_credits is not None:
                balance_amount = round(float(total_credits) - float(usage), 4)
            elif limit is not None:
                balance_amount = round(float(limit) - float(usage), 4)
            else:
                balance_amount = None

            result["balance"] = {
                "amount": balance_amount,
                "currency": "USD",
                "type": "free_tier" if is_free else "prepaid",
                "total_credits": total_credits,
                "total_limit": limit,
                "used": usage,
            }

            if rate_limit:
                requests = rate_limit.get("requests")
                interval = rate_limit.get("interval", "")
                if requests:
                    result["limits"]["requests_per_minute"] = requests
                    result["notes"].append(f"Rate limit: {requests} req / {interval}")

            if result["balance"]["amount"] is not None and result["balance"]["amount"] < warn_usd:
                add_warning(result, f"Balance ${result['balance']['amount']:.2f} below threshold ${warn_usd:.2f}")

            result["tier"] = "Free tier" if is_free else "Paid"

    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_deepseek(key: str, client: httpx.AsyncClient, warn_usd: float) -> dict:
    result = make_result("deepseek", "Deepseek")
    result["console_url"] = "https://platform.deepseek.com"
    try:
        resp = await client.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code == 200:
            data = resp.json()
            is_available = data.get("is_available", True)
            balances = data.get("balance_infos", [])
            for b in balances:
                currency = b.get("currency", "CNY")
                total = float(b.get("total_balance", 0))
                usd_equiv = total * CNY_TO_USD if currency == "CNY" else total
                result["balance"] = {
                    "amount": total,
                    "currency": currency,
                    "usd_equivalent": round(usd_equiv, 2),
                    "type": "prepaid",
                }
                if usd_equiv < warn_usd:
                    add_warning(result, f"Balance {currency} {total:.2f} (~${usd_equiv:.2f} USD) below threshold")
            if not is_available:
                add_warning(result, "Account marked as unavailable")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_together(key: str, client: httpx.AsyncClient, warn_usd: float) -> dict:
    result = make_result("together", "Together AI")
    result["console_url"] = "https://api.together.xyz/settings/billing"
    try:
        resp = await client.get(
            "https://api.together.xyz/v1/organizations/me",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code == 200:
            data = resp.json()
            credits = data.get("credits")
            if credits is not None:
                result["balance"] = {
                    "amount": float(credits),
                    "currency": "USD",
                    "type": "prepaid",
                }
                if float(credits) < warn_usd:
                    add_warning(result, f"Credit balance ${float(credits):.2f} below threshold")
        elif resp.status_code == 404:
            # Try alternate endpoint
            resp2 = await client.get(
                "https://api.together.xyz/v1/users/me",
                headers={"Authorization": f"Bearer {key}"},
                timeout=TIMEOUT,
            )
            if resp2.status_code == 200:
                result["notes"].append("Account active (billing details at console)")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_mistral(key: str, client: httpx.AsyncClient) -> dict:
    result = make_result("mistral", "Mistral AI")
    result["console_url"] = "https://console.mistral.ai"
    try:
        resp = await client.get(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code == 200:
            parse_rate_limit_headers(dict(resp.headers), result)
            result["notes"].append("Billing details available at console.mistral.ai")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_gemini(key: str, client: httpx.AsyncClient) -> dict:
    result = make_result("gemini", "Google Gemini")
    result["console_url"] = "https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas"
    try:
        resp = await client.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=TIMEOUT,
        )
        if resp.status_code == 400:
            set_error(result, "400 Bad Request — invalid API key format")
            return result
        if resp.status_code == 403:
            set_error(result, "403 Forbidden — key may be restricted or billing not enabled")
            return result
        if resp.status_code == 200:
            parse_rate_limit_headers(dict(resp.headers), result)
            result["notes"].append("Detailed quota limits available in Google Cloud Console")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_cohere(key: str, client: httpx.AsyncClient) -> dict:
    result = make_result("cohere", "Cohere")
    result["console_url"] = "https://dashboard.cohere.com"
    try:
        resp = await client.post(
            "https://api.cohere.com/v1/check-api-key",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code == 200:
            data = resp.json()
            valid = data.get("valid", False)
            if not valid:
                set_error(result, "API key reported as invalid by Cohere")
            else:
                parse_rate_limit_headers(dict(resp.headers), result)
                result["notes"].append("Billing details at dashboard.cohere.com")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_replicate(key: str, client: httpx.AsyncClient, warn_usd: float) -> dict:
    result = make_result("replicate", "Replicate")
    result["console_url"] = "https://replicate.com/account/billing"
    try:
        resp = await client.get(
            "https://api.replicate.com/v1/account",
            headers={"Authorization": f"Token {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API token")
            return result
        if resp.status_code == 200:
            data = resp.json()
            result["tier"] = data.get("type", "unknown")
            result["notes"].append("Billing details at replicate.com/account/billing")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_perplexity(key: str, client: httpx.AsyncClient) -> dict:
    result = make_result("perplexity", "Perplexity")
    result["console_url"] = "https://www.perplexity.ai/settings/api"
    result["notes"].append("No public balance API — check perplexity.ai/settings/api")
    # Validate key with a minimal models call
    try:
        resp = await client.get(
            "https://api.perplexity.ai/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
        elif resp.status_code in (200, 404):  # 404 = endpoint DNE but key valid
            parse_rate_limit_headers(dict(resp.headers), result)
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_moonshot(key: str, client: httpx.AsyncClient, warn_usd: float) -> dict:
    result = make_result("moonshot", "Moonshot/Kimi")
    result["console_url"] = "https://platform.moonshot.cn"
    try:
        # Try international endpoint first, fall back to China
        resp = await client.get(
            "https://api.moonshot.ai/v1/users/me/balance",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            # Try China endpoint
            resp = await client.get(
                "https://api.moonshot.cn/v1/users/me/balance",
                headers={"Authorization": f"Bearer {key}"},
                timeout=TIMEOUT,
            )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid API key")
            return result
        if resp.status_code == 200:
            data = resp.json()
            balance = data.get("data", {})
            # Handle both international and China API response formats
            available = float(balance.get("available_balance", 0))
            currency = balance.get("currency")
            # International API (api.moonshot.ai) returns USD, China API returns CNY
            is_international = "moonshot.ai" in str(resp.url)
            if currency is None:
                currency = "USD" if is_international else "CNY"
            usd_equiv = available if currency == "USD" else available * CNY_TO_USD
            result["balance"] = {
                "amount": available,
                "currency": currency,
                "usd_equivalent": round(usd_equiv, 2),
                "type": "prepaid",
            }
            if usd_equiv < warn_usd:
                add_warning(result, f"Balance {currency} {available:.2f} (~${usd_equiv:.2f} USD) below threshold")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


async def check_huggingface(key: str, client: httpx.AsyncClient) -> dict:
    result = make_result("huggingface", "Hugging Face")
    result["console_url"] = "https://huggingface.co/settings/billing"
    try:
        resp = await client.get(
            "https://huggingface.co/api/whoami",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 401:
            set_error(result, "401 Unauthorized — invalid token")
            return result
        if resp.status_code == 200:
            data = resp.json()
            result["tier"] = data.get("type", "user")
            result["notes"].append("Billing at huggingface.co/settings/billing")
    except httpx.TimeoutException:
        set_error(result, "Request timed out")
    except Exception as e:
        set_error(result, str(e))
    return result


# ─────────────────────────────────────────────
# Main Runner
# ─────────────────────────────────────────────

async def run_checks(providers_filter: list, warn_usd: float) -> list:
    results = []
    tasks = {}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        checker_map = {
            "anthropic":   lambda k: check_anthropic(k, client),
            "openai":      lambda k: check_openai(k, client, warn_usd),
            "groq":        lambda k: check_groq(k, client),
            "openrouter":  lambda k: check_openrouter(k, client, warn_usd),
            "deepseek":    lambda k: check_deepseek(k, client, warn_usd),
            "together":    lambda k: check_together(k, client, warn_usd),
            "mistral":     lambda k: check_mistral(k, client),
            "gemini":      lambda k: check_gemini(k, client),
            "cohere":      lambda k: check_cohere(k, client),
            "replicate":   lambda k: check_replicate(k, client, warn_usd),
            "perplexity":  lambda k: check_perplexity(k, client),
            "moonshot":    lambda k: check_moonshot(k, client, warn_usd),
            "huggingface": lambda k: check_huggingface(k, client),
        }

        # Collect configured providers
        for pid, cfg in PROVIDERS_CONFIG.items():
            if providers_filter and pid not in providers_filter:
                continue
            key = os.environ.get(cfg["env"], "").strip()
            if not key:
                r = make_result(pid, cfg["label"])
                r["status"] = "UNCONFIGURED"
                r["notes"].append(f"Set {cfg['env']} to enable this provider")
                results.append(r)
                continue
            if pid in checker_map:
                tasks[pid] = asyncio.create_task(checker_map[pid](key))

        # Run all checks concurrently
        if tasks:
            done = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for pid, result in zip(tasks.keys(), done):
                if isinstance(result, Exception):
                    r = make_result(pid, PROVIDERS_CONFIG[pid]["label"])
                    set_error(r, str(result))
                    results.append(r)
                else:
                    results.append(result)

    # Sort: OK first, then WARNING, ERROR, UNCONFIGURED
    order = {"OK": 0, "WARNING": 1, "ERROR": 2, "UNCONFIGURED": 3}
    results.sort(key=lambda r: order.get(r["status"], 9))
    return results


# ─────────────────────────────────────────────
# Report Formatter
# ─────────────────────────────────────────────

STATUS_ICONS = {"OK": "✅", "WARNING": "⚠️ ", "ERROR": "❌", "UNCONFIGURED": "⚫"}
WIDTH = 66


def fmt_limit(val):
    if val is None:
        return "N/A"
    return f"{val:,}"


def format_report(results: list, warn_usd: float) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []

    lines.append("╔" + "═" * (WIDTH - 2) + "╗")
    lines.append(f"║  🔍 OpenClaw API Status Report{' ' * (WIDTH - 32)}║")
    lines.append(f"║  Generated: {now}{' ' * (WIDTH - 14 - len(now))}║")
    lines.append("╚" + "═" * (WIDTH - 2) + "╝")
    lines.append("")

    counts = {s: sum(1 for r in results if r["status"] == s)
              for s in ("OK", "WARNING", "ERROR", "UNCONFIGURED")}

    lines.append("📊 SUMMARY")
    lines.append("─" * WIDTH)
    lines.append(f"  Providers Checked:  {len(results)}")
    lines.append(f"  ✅ Healthy:         {counts['OK']}")
    lines.append(f"  ⚠️  Warnings:        {counts['WARNING']}")
    lines.append(f"  ❌ Errors:          {counts['ERROR']}")
    lines.append(f"  ⚫ Unconfigured:    {counts['UNCONFIGURED']}")
    lines.append("")
    lines.append("─" * WIDTH)
    lines.append("PROVIDER DETAILS")
    lines.append("─" * WIDTH)

    for r in results:
        icon = STATUS_ICONS.get(r["status"], "?")
        warnings_str = f"  [{', '.join(r['warnings'])}]" if r["warnings"] else ""
        lines.append(f"\n{icon} {r['provider'].upper()}{warnings_str}")

        if r["status"] == "UNCONFIGURED":
            lines.append(f"   {'─' * 40}")
            for note in r["notes"]:
                lines.append(f"   ℹ️  {note}")
            continue

        if r["status"] == "ERROR":
            lines.append(f"   Error: {r['error']}")
            if r.get("console_url"):
                lines.append(f"   Console: {r['console_url']}")
            continue

        lines.append(f"   {'─' * 40}")

        if r.get("tier"):
            lines.append(f"   Tier:          {r['tier']}")

        if r.get("balance"):
            b = r["balance"]
            amt = b.get("amount")
            cur = b.get("currency", "USD")
            if amt is not None:
                display = f"{cur} {amt:,.4f}"
                usd_eq = b.get("usd_equivalent")
                if usd_eq and cur != "USD":
                    display += f"  (~${usd_eq:.2f} USD)"
                btype = b.get("type", "")
                lines.append(f"   Balance:       {display}  [{btype}]")

        lim = r.get("limits", {})
        rem = r.get("remaining", {})

        rpm = lim.get("requests_per_minute")
        tpm = lim.get("tokens_per_minute")
        r_rem = rem.get("requests")
        t_rem = rem.get("tokens")
        reset = rem.get("resets_in_seconds")

        if rpm or tpm:
            if rpm:
                rem_str = f"  │  Remaining: {fmt_limit(r_rem)}" if r_rem is not None else ""
                lines.append(f"   RPM Limit:     {fmt_limit(rpm)}{rem_str}")
            if tpm:
                rem_str = f"  │  Remaining: {fmt_limit(t_rem)}" if t_rem is not None else ""
                lines.append(f"   TPM Limit:     {fmt_limit(tpm)}{rem_str}")
            if lim.get("input_tokens_per_minute"):
                lines.append(f"   Input TPM:     {fmt_limit(lim['input_tokens_per_minute'])}"
                             f"  │  Output TPM: {fmt_limit(lim.get('output_tokens_per_minute'))}")
            if reset:
                lines.append(f"   Resets in:     {reset}")

        if r.get("usage"):
            u = r["usage"]
            cost = u.get("cost_usd")
            period = u.get("period", "")
            if cost is not None:
                lines.append(f"   Usage ({period}): ${cost:.4f} USD")

        for note in r.get("notes", []):
            lines.append(f"   ℹ️  {note}")
        if r.get("console_url") and r.get("notes"):
            lines.append(f"   🔗 {r['console_url']}")

    # Recommendations
    recs = []
    for r in results:
        if r["status"] == "WARNING":
            for w in r["warnings"]:
                recs.append(f"  • ⚠️  {r['provider']}: {w}")
        elif r["status"] == "ERROR":
            recs.append(f"  • ❌ {r['provider']}: {r.get('error', 'Check configuration')}")

    no_billing = [r["provider"] for r in results
                  if r["status"] == "OK" and any("not available via API" in n or "Billing" in n
                                                   for n in r.get("notes", []))]
    if no_billing:
        recs.append(f"  • ℹ️  {', '.join(no_billing)}: billing requires web console access")

    if recs:
        lines.append("")
        lines.append("─" * WIDTH)
        lines.append("💡 RECOMMENDATIONS")
        lines.append("─" * WIDTH)
        lines.extend(recs)

    lines.append("")
    lines.append("═" * WIDTH)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OpenClaw API Status Checker")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--providers", nargs="+", metavar="PROVIDER",
                        help=f"Check specific providers only: {list(PROVIDERS_CONFIG.keys())}")
    parser.add_argument("--save", action="store_true", help="Save report to ~/openclaw/reports/")
    parser.add_argument("--threshold", type=float, default=DEFAULT_WARN_BALANCE_USD,
                        help=f"Low balance warning threshold in USD (default: {DEFAULT_WARN_BALANCE_USD})")
    args = parser.parse_args()

    providers_filter = [p.lower() for p in args.providers] if args.providers else []
    invalid = [p for p in providers_filter if p not in PROVIDERS_CONFIG]
    if invalid:
        print(f"ERROR: Unknown providers: {invalid}", file=sys.stderr)
        print(f"Valid providers: {list(PROVIDERS_CONFIG.keys())}", file=sys.stderr)
        sys.exit(1)

    results = asyncio.run(run_checks(providers_filter, args.threshold))

    if args.json:
        print(json.dumps(results, indent=2))
        return

    report = format_report(results, args.threshold)
    print(report)

    if args.save:
        save_dir = Path.home() / "openclaw" / "reports"
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_path = save_dir / f"api-status-{timestamp}.txt"
        json_path = save_dir / f"api-status-{timestamp}.json"
        report_path.write_text(report)
        json_path.write_text(json.dumps(results, indent=2))
        print(f"\nReport saved to: {report_path}", file=sys.stderr)
        print(f"JSON saved to:   {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
