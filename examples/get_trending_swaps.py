#!/usr/bin/env python3
"""
get_trending_swaps.py — Query GMGN OpenAPI for trending token swap data.

Equivalent to the public GMGN web endpoint:
  GET https://gmgn.ai/api/v1/rank/sol/swaps/1h
      ?orderby=marketcap&direction=desc&filters[]=renounced&filters[]=frozen

OpenAPI endpoint used:
  GET https://openapi.gmgn.ai/v1/market/rank
      ?chain=sol&interval=1h&order_by=marketcap&direction=desc&filters=renounced&filters=frozen

Auth: normal auth — requires GMGN_API_KEY only (no private key needed).

Prerequisites:
  pip install requests python-dotenv   (requires Python 3.8+)

Config:
  Set GMGN_API_KEY in ~/.config/gmgn/.env or a local .env file.
  Apply for a key at https://gmgn.ai/ai

Usage:
  python get_trending_swaps.py [--chain sol|bsc|base] [--interval 1h|3h|6h|24h]
                               [--order-by <field>] [--direction asc|desc]
                               [--filter <tag>] [--limit <n>]
                               [--raw]

Examples:
  # Default: SOL / 1h / marketcap desc / renounced + frozen (mirrors the curl example)
  python get_trending_swaps.py

  # BSC, last 24 hours, sorted by volume
  python get_trending_swaps.py --chain bsc --interval 24h --order-by volume

  # SOL, Pump.fun hot tokens filtered by not_risk
  python get_trending_swaps.py --chain sol --interval 1h --order-by swaps --filter not_risk --limit 20

  # Raw JSON output (for piping to jq)
  python get_trending_swaps.py --raw | python -m json.tool
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    sys.exit("[error] 'requests' package not found. Install it with: pip install requests")

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("[error] 'python-dotenv' package not found. Install it with: pip install python-dotenv")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config() -> Dict[str, str]:
    """Load API key and host from ~/.config/gmgn/.env then local .env (local takes precedence)."""
    global_env = Path.home() / ".config" / "gmgn" / ".env"
    if global_env.exists():
        load_dotenv(dotenv_path=global_env)
    # Local .env overrides global
    load_dotenv(override=True)

    api_key = os.getenv("GMGN_API_KEY")
    if not api_key:
        sys.exit(
            "[error] GMGN_API_KEY is not set.\n"
            "Create ~/.config/gmgn/.env with:\n"
            "  GMGN_API_KEY=your_key_here\n"
            "Apply for a key at https://gmgn.ai/ai"
        )

    host = os.getenv("GMGN_HOST", "https://openapi.gmgn.ai").rstrip("/")
    return {"api_key": api_key, "host": host}


# ---------------------------------------------------------------------------
# Auth helpers (normal auth — no private key required)
# ---------------------------------------------------------------------------

def build_auth_params() -> Dict[str, str]:
    """
    Build normal-auth query parameters:
      timestamp : Unix seconds (server validates within ±5 s)
      client_id : UUID v4 (replays rejected within 7 s)
    """
    return {
        "timestamp": str(int(time.time())),
        "client_id": str(uuid.uuid4()),
    }


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def get_trending_swaps(
    api_key: str,
    host: str,
    chain: str = "sol",
    interval: str = "1h",
    order_by: str = "marketcap",
    direction: str = "desc",
    filters: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> object:
    """
    Call GET /v1/market/rank and return the parsed data payload.

    Parameters
    ----------
    chain     : sol / bsc / base
    interval  : 1h / 3h / 6h / 24h
    order_by  : marketcap / volume / swaps / price / change1h / ... (see docs)
    direction : asc / desc
    filters   : list of filter tags, e.g. ["renounced", "frozen"]
    limit     : max number of results (default 100, max 100)
    """
    if filters is None:
        filters = ["renounced", "frozen"]

    # Build base query params as list of tuples to support repeated keys
    params: List[tuple] = [
        ("chain", chain),
        ("interval", interval),
        ("order_by", order_by),
        ("direction", direction),
    ]
    # Repeatable 'filters' param — append each tag separately
    for tag in filters:
        params.append(("filters", tag))
    if limit is not None:
        params.append(("limit", str(limit)))

    # Add auth params
    auth = build_auth_params()
    params.append(("timestamp", auth["timestamp"]))
    params.append(("client_id", auth["client_id"]))

    url = "{}/v1/market/rank".format(host)
    headers = {
        "X-APIKEY": api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as exc:
        sys.exit("[error] HTTP request failed: {}".format(exc))

    # Parse response
    try:
        body = resp.json()
    except ValueError:
        sys.exit(
            "[error] Non-JSON response (HTTP {}):\n{}".format(resp.status_code, resp.text[:500])
        )

    if body.get("code") != 0:
        sys.exit(
            "[error] API error (HTTP {}): code={} message={} error={}".format(
                resp.status_code,
                body.get("code"),
                body.get("message", ""),
                body.get("error", ""),
            )
        )

    return body["data"]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Query GMGN trending token swap data via OpenAPI.\n"
            "Equivalent to: GET https://gmgn.ai/api/v1/rank/<chain>/swaps/<interval>"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--chain", default="sol", help="Chain: sol / bsc / base (default: sol)")
    parser.add_argument("--interval", default="1h", help="Time interval: 1h / 3h / 6h / 24h (default: 1h)")
    parser.add_argument(
        "--order-by", dest="order_by", default="marketcap",
        help=(
            "Sort field (default: marketcap). Options: marketcap / volume / swaps / price / "
            "change1h / change5m / change1m / holder_count / liquidity / "
            "smart_degen_count / renowned_count / bluechip_owner_percentage / "
            "rank / history_highest_market_cap / gas_fee / creation_timestamp"
        ),
    )
    parser.add_argument("--direction", default="desc", help="Sort direction: asc / desc (default: desc)")
    parser.add_argument(
        "--filter", dest="filters", action="append", default=None,
        metavar="TAG",
        help=(
            "Filter tag (repeatable). Default: renounced frozen. "
            "sol: renounced / frozen / not_risk / not_wash_trading / has_social / burn / distributed / ... "
            "evm: not_honeypot / verified / renounced / locked / not_risk / ..."
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="Number of results (max 100)")
    parser.add_argument("--raw", action="store_true", help="Output raw single-line JSON")
    args = parser.parse_args()

    # Default filters match the original curl example
    filters = args.filters if args.filters is not None else ["renounced", "frozen"]

    config = load_config()
    data = get_trending_swaps(
        api_key=config["api_key"],
        host=config["host"],
        chain=args.chain,
        interval=args.interval,
        order_by=args.order_by,
        direction=args.direction,
        filters=filters,
        limit=args.limit,
    )

    if args.raw:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

