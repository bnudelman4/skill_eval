"""Daloopa MCP connection smoke test.

Verifies the env vars are set and the MCP endpoint responds to a standard
`tools/list` JSON-RPC call with the bearer token. Does NOT call any
Daloopa-specific tool yet (those need the real method names from Daloopa's
docs). This is just: "can we reach the server and does auth work?"

Run:
    PYTHONPATH=src python scripts/daloopa_smoke.py
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import load_dotenv


def main() -> int:
    load_dotenv(".env", override=True)
    url = os.environ.get("DALOOPA_MCP_URL", "").rstrip("/")
    token = os.environ.get("DALOOPA_TOKEN", "")

    if not url:
        print("FAIL: DALOOPA_MCP_URL not set in .env")
        return 2

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        print(f"  using bearer token ({len(token)} chars)")
    else:
        print("  no token (assuming open/public MCP)")
    # Standard MCP method that lists available tools; works for any MCP server.
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    print(f"Connecting to {url} ...")
    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=20.0)
    except httpx.RequestError as e:
        print(f"FAIL: network/transport error -> {type(e).__name__}: {e}")
        print("  Check DALOOPA_MCP_URL is reachable from this machine.")
        return 3

    print(f"  HTTP {r.status_code}")
    if r.status_code == 401 or r.status_code == 403:
        print("FAIL: auth rejected. Token wrong, expired, or wrong scheme.")
        print(f"  body: {r.text[:300]}")
        return 4
    if r.status_code == 404:
        print("FAIL: 404. URL likely wrong; check the exact MCP endpoint.")
        print(f"  body: {r.text[:300]}")
        return 5
    if r.status_code >= 500:
        print(f"FAIL: server error {r.status_code}. Retry or contact Daloopa.")
        print(f"  body: {r.text[:300]}")
        return 6

    # parse response
    try:
        data = r.json()
    except json.JSONDecodeError:
        print(f"WARN: non-JSON response (status {r.status_code}):")
        print(f"  body: {r.text[:300]}")
        return 7

    if "error" in data:
        print(f"FAIL: JSON-RPC error -> {data['error']}")
        return 8

    tools = data.get("result", {}).get("tools", [])
    print(f"OK: connected. Server returned {len(tools)} tool(s).")
    for t in tools[:8]:
        print(f"  - {t.get('name', '?'):30s}  {t.get('description','')[:60]}")
    if len(tools) > 8:
        print(f"  ... and {len(tools)-8} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
