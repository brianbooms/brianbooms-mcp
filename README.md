# brianbooms-mcp

MCP server for [Brian Booms](https://brianbooms.com)' agent-commerce storefront — ambient music, ringtones, wallpapers, track leases, game licenses, and custom commissions, all buyable by AI agents with USDC on Base via x402.

## Install

```json
{
  "mcpServers": {
    "brianbooms": {
      "command": "npx",
      "args": ["-y", "github:brianbooms/brianbooms-mcp"]
    }
  }
}
```

No API key. No account. The server is read-only discovery — your agent pays with its own x402/EVM wallet.

## Tools

| Tool | What it does |
|---|---|
| `catalog` | List all 22 products: sku, name, USD price |
| `product` | Full details for one SKU: description, price, delivery, buy URL |
| `purchase_instructions` | Exact live x402 payment requirements for a SKU (pay-to, amount, asset, network), parsed from its 402 response |
| `rewards` | Booms Rewards explainer: buyer earn rates (10%, 15% first purchase, 20% via referral), 5% referral earnings, and free merchant enrollment |

## Buy flow

1. `catalog` → pick a product.
2. `purchase_instructions` → get exact payment requirements.
3. Your agent pays with any x402 v1 client (USDC on Base, facilitator `facilitator.xpay.sh`).
4. The 200 response is the order: instant download link, or fulfillment status for commissions/licenses.

Buyers earn 10% back in Booms Rewards credit on every purchase (15% on the first). Merchants join free: https://brianbooms.com/partner/

## License

MIT
