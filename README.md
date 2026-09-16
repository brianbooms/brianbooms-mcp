# brianbooms MCP server

Puts the Brian Booms x402 product catalog **inside AI agents** as callable tools.
Any MCP-capable agent can search the catalog, read license terms, fetch live
x402 payment requirements, and complete a purchase — without opening a browser.

Docs & agent storefront: https://brianbooms.com/agents/

*Made with Suno* (catalog ethics: disclose on first mention of how the music is made).

## Tools

| Tool | What it does |
|---|---|
| `search_catalog(query, max_price?)` | Search 24 agent-buyable digital products (music packs, wallpapers, ringtones, zines, sleep memberships; $0.05–$299 USDC) |
| `get_product(sku)` | Full details: price, buy URL, delivery, license-terms summary |
| `buy_product(sku)` | Fetches the **live** HTTP 402 from the buy URL and returns payment requirements + step-by-step x402 signing instructions |
| `get_market()` | The AP2 market listings (machine-readable directory of buyable products) |

**Read-only by design.** The server never signs, submits, or executes a payment.
`buy_product` returns *what to sign*, not a completed purchase. The catalog
itself requires **explicit human authorization, one purchase per request**.

## Install

```bash
pip install mcp
```

## Run (stdio)

```jsonc
// Claude Desktop / claude-code MCP config
{
  "mcpServers": {
    "brianbooms": {
      "command": "python3",
      "args": ["/path/to/brianbooms-mcp/server.py"]
    }
  }
}
```

Published to npm as `brianbooms-mcp` (v1.0.3). Run the published package:
`npx -y brianbooms-mcp` — or install the Python entrypoint with pipx/uvx.

## How payment works (x402 v1)

1. Agent calls `buy_product(sku)` → gets the 402 requirements
2. Human explicitly authorizes the purchase
3. Agent signs the EIP-3009 authorization **off-chain** (gasless for the buyer; the facilitator submits on-chain)
4. Agent resubmits to the buy URL with the signed payload
5. Settlement response contains the download/delivery URL

Networks: Base, Polygon, Arbitrum, Avalanche, Solana — asset USDC, x402 v1
(exact scheme). Catalog loads live from
`https://brianbooms.com/.well-known/purchase-catalog.json` at startup with a
local fallback copy (`catalog-fallback.json`).

## Booms Rewards (live rates, 2026-09-16)

Buyers earn store credit on every settled purchase: 10% standard, 15% on the
first purchase, 20% on a referred buyer's first purchase (referrer earns 10%
of the referred identity's first purchase), 5% universal cashback on top.
First-buy faucet: the first-ever settled x402 purchase per wallet is rebated
100% as store credit (agents only, automatic). Credit is non-withdrawable and
spends at brianbooms.com. Rates: https://pay.brianbooms.com/api/v1/rewards/info

## Files

- `server.py` — the MCP server (stdio)
- `catalog-fallback.json` — local catalog copy used if the hub is unreachable
- `package.json` — npm wrapper metadata (for registry publishing)
