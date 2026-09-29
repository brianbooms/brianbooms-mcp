# brianbooms MCP server

Puts the Brian Booms x402 product catalog **inside AI agents** as callable tools.
Any MCP-capable agent can search the catalog, read license terms, fetch live
x402 payment requirements, and complete a purchase — without opening a browser.

*Made with Suno* (catalog ethics: disclose on first mention of how the music is made).

## Tools

| Tool | What it does |
|---|---|
| `search_catalog(query, max_price?)` | Search 33 agent-buyable digital products (music licenses, sample packs, commissions, wallpapers; $0.05–$999 USDC) |
| `get_product(sku)` | Full details: price, buy URL, delivery, license-terms summary |
| `buy_product(sku, partner?)` | Fetches the **live** HTTP 402 from the buy URL and returns payment requirements + step-by-step x402 signing instructions. Optional `partner` id attributes the purchase to a Booms Partner (20% revenue share) |
| `get_market()` | The 33 AP2 market listings (machine-readable directory) |

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

Or with uvx / pipx once published to npm/PyPI (not yet published).

## How payment works (x402 v1)

1. Agent calls `buy_product(sku)` → gets the 402 requirements
2. Human explicitly authorizes the purchase
3. Agent signs the EIP-3009 authorization **off-chain** (gasless for the buyer; the facilitator submits on-chain)
4. Agent resubmits to the buy URL with the signed payload
5. Settlement response contains the download/delivery URL

Network: Base `eip155:8453`, asset USDC. Catalog loads live from
`https://brianbooms.com/.well-known/purchase-catalog.json` at startup with a
local fallback copy (`catalog-fallback.json`).

## Files

- `server.py` — the MCP server (stdio)
- `catalog-fallback.json` — local catalog copy used if the hub is unreachable
- `package.json` — npm wrapper metadata (for registry publishing)
