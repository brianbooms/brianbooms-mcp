#!/usr/bin/env python3
"""brianbooms MCP server — puts the Brian Booms x402 product catalog INSIDE AI agents.

Read-only by design: this server NEVER signs, submits, or executes a payment.
The buy_product tool fetches the live 402 payment requirements and returns
step-by-step instructions so the AGENT (with its human's explicit authorization)
can complete the x402 payment itself.

Catalog: 24 digital products (music packs, wallpapers, ringtones, zines,
sleep memberships), $0.05-$299 USDC, settled via x402 v1 on Base, Polygon, Arbitrum,
Avalanche, or Solana (EIP-3009 on EVM, gasless for the buyer).
"""

import json
import os
import subprocess
import sys
import urllib.request

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("brianbooms")

CATALOG_URL = "https://brianbooms.com/.well-known/purchase-catalog.json"
MARKET_URL = "https://x402-market.brianbooms.workers.dev/api/listings"
NETWORKS = ["base", "polygon", "arbitrum", "avalanche", "solana"]
HERE = os.path.dirname(os.path.abspath(__file__))
FALLBACK_PATH = os.path.join(HERE, "catalog-fallback.json")
DISCLOSURE = "Made with Suno"  # catalog ethics: disclose on first mention of how the music is made


def _http_get_json(url, timeout=15):
    """GET JSON with retries; urllib intermittently hits IncompleteRead through
    the egress proxy, so fall back to curl (proven reliable on this host)."""
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "brianbooms-mcp/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "-A", "brianbooms-mcp/1.0", url],
            capture_output=True, timeout=timeout + 5, check=True)
        return json.loads(out.stdout.decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"GET {url} failed (urllib: {last}; curl: {e})")


def _load_catalog():
    """Live catalog at startup; local fallback copy if the hub is unreachable."""
    try:
        data = _http_get_json(CATALOG_URL)
        if data.get("products"):
            return data, "live"
    except Exception as e:
        sys.stderr.write(f"[brianbooms-mcp] live catalog failed ({e}); using fallback\n")
    with open(FALLBACK_PATH, encoding="utf-8") as f:
        return json.load(f), "fallback"


CATALOG, CATALOG_SOURCE = _load_catalog()
PRODUCTS = {p["sku"]: p for p in CATALOG.get("products", [])}


def _money(p):
    return f"${float(p['price_usd']):.2f} USDC"


def _license_summary(p):
    """Pull the rights-relevant line out of the description; never invent terms."""
    desc = p.get("description", "")
    low = desc.lower()
    if "commercial" in low:
        scope = "commercial use permitted (see description)"
    elif "personal use" in low:
        scope = "personal use"
    elif "lease" in low:
        scope = "lease terms as described"
    else:
        scope = "as described"
    return {"scope_hint": scope, "full_description": desc,
            "delivery": p.get("delivery", "instant download")}


@mcp.tool()
def search_catalog(query: str, max_price: float | None = None) -> str:
    """Search the Brian Booms catalog of 24 agent-buyable digital products.

    query: keywords like "podcast intro", "game music", "wallpaper", "commission", "lease"
    max_price: optional USD cap (e.g. 30 for products at most $30)
    """
    q = query.lower().split()
    hits = []
    for p in PRODUCTS.values():
        hay = f"{p['name']} {p['sku']} {p.get('description','')}".lower()
        if all(w in hay for w in q):
            if max_price is not None and float(p["price_usd"]) > max_price:
                continue
            hits.append({
                "sku": p["sku"],
                "name": p["name"],
                "price_usd": p["price_usd"],
                "description": p.get("description", "")[:160],
            })
    hits.sort(key=lambda h: float(h["price_usd"]))
    return json.dumps({
        "disclosure": DISCLOSURE,
        "catalog_source": CATALOG_SOURCE,
        "count": len(hits),
        "results": hits[:25],
        "note": "Prices in USDC. One purchase per request; human authorization required before paying.",
    }, indent=1)


@mcp.tool()
def get_product(sku: str) -> str:
    """Full details for one product: price, buy URL, delivery, and license terms summary."""
    p = PRODUCTS.get(sku)
    if not p:
        close = [s for s in PRODUCTS if sku.lower() in s.lower()][:5]
        return json.dumps({"error": f"Unknown SKU '{sku}'.", "did_you_mean": close})
    return json.dumps({
        "disclosure": DISCLOSURE,
        "sku": p["sku"],
        "name": p["name"],
        "price": _money(p),
        "buy_url": p["buy_url"],
        "human_checkout": p.get("human_checkout"),
        "license": _license_summary(p),
        "rewards_eligible": p.get("rewards_eligible"),
        "network": CATALOG.get("x402_network", "Base eip155:8453"),
        "accepted_networks": NETWORKS,
        "asset": CATALOG.get("asset", "USDC"),
        "purchase_policy": "Human explicit authorization required, one purchase per request. This server never pays.",
    }, indent=1)


@mcp.tool()
def buy_product(sku: str) -> str:
    """Get the LIVE x402 payment requirements for a product.

    Returns the 402 requirements plus step-by-step signing instructions.
    READ-ONLY: this tool never signs or submits anything. The calling agent
    completes the payment itself after explicit human authorization.
    """
    p = PRODUCTS.get(sku)
    if not p:
        return json.dumps({"error": f"Unknown SKU '{sku}'."})
    buy_url = p["buy_url"]
    try:
        req = urllib.request.Request(buy_url, headers={"User-Agent": "brianbooms-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            status, body = r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8")
    except Exception as e:
        # urllib IncompleteRead on some egress paths; curl is the proven fallback
        try:
            out = subprocess.run(
                ["curl", "-s", "--max-time", "20", "-A", "brianbooms-mcp/1.0",
                 "-w", "\n%{http_code}", buy_url],
                capture_output=True, timeout=25, check=True)
            *body_lines, code = out.stdout.decode("utf-8").rsplit("\n", 1)
            status, body = int(code), "\n".join(body_lines)
        except Exception as e2:
            return json.dumps({"error": f"buy_url unreachable: {e} / {e2}"})
    if status != 402:
        return json.dumps({
            "error": f"Expected HTTP 402 from {buy_url}, got {status}.",
            "body_preview": body[:300],
        })
    try:
        reqs = json.loads(body)
    except json.JSONDecodeError:
        reqs = {"raw": body[:2000]}
    return json.dumps({
        "disclosure": DISCLOSURE,
        "sku": sku,
        "name": p["name"],
        "price": _money(p),
        "requirements": reqs,
        "how_to_pay": [
            "1. Confirm your human explicitly authorized THIS purchase (one purchase per request).",
            "2. Read the 402 'requirements': network, asset (USDC), amount, payTo, and scheme (x402 v1 exact / EIP-3009).",
            "3. Sign the EIP-3009 authorization off-chain with the payer wallet (gasless for you; the facilitator submits on-chain).",
            "4. Resubmit the request to buy_url with the signed payload per the x402 v1 spec.",
            "5. On success the settlement response contains the download/delivery URL. Keep the transaction receipt.",
        ],
        "note": "This MCP server cannot and will not sign or pay on your behalf.",
    }, indent=1)


@mcp.tool()
def get_market() -> str:
    """AP2 market listings (machine-readable directory of buyable products)."""
    try:
        listings = _http_get_json(MARKET_URL)
        if isinstance(listings, dict):
            listings = listings.get("listings", [])
        brief = [{"name": l.get("name"), "url": l.get("url")} for l in listings]
        return json.dumps({
            "disclosure": DISCLOSURE,
            "count": len(brief),
            "listings": brief,
            "source": MARKET_URL,
        }, indent=1)
    except Exception as e:
        return json.dumps({"error": f"Market unreachable: {e}", "source": MARKET_URL})


if __name__ == "__main__":
    sys.stderr.write(f"[brianbooms-mcp] catalog: {len(PRODUCTS)} products ({CATALOG_SOURCE})\n")
    mcp.run(transport="stdio")
