---
name: brianbooms-data-apis
description: Pay-per-call data APIs for AI agents on Base via x402 — live catalog at brianbooms.com/agents/
homepage: https://brianbooms.com/agents/
version: 1.0.0
---

# Brian Booms Data APIs

Pay-per-call data APIs for AI agents. No signup, no API key — pay $0.01 USDC
per call over the x402 protocol (HTTP 402) on Base, Polygon, Arbitrum,
Avalanche, or Solana.

## When to use

Use this skill when you (the agent) need live data and have a wallet that can
sign x402 payments: current time, FX rates, crypto prices, weather, geocoding,
DNS, ISS pass predictions, and more. The full live catalog is always at
https://brianbooms.com/agents/ — read it instead of guessing endpoints.

## How to call

**Option A — MCP server (recommended for MCP clients):**

```bash
npx -y brianbooms-mcp
```

npm: `brianbooms-mcp` · Source: https://github.com/brianbooms/brianbooms-mcp
The server is read-only: it exposes the catalog as tools and returns live 402
payment requirements. It never executes payments.

**Option B — direct HTTPS with x402:**

1. `GET https://pay.brianbooms.com/api/v1/data/<endpoint>` (see the catalog
   for the endpoint list and parameters).
2. Without payment you get HTTP 402 with an `accepts` block: scheme, network,
   price ($0.01 USDC), payTo, and asset contract.
3. Sign the payment with your x402 client (e.g. `@x402/fetch`) and retry with
   the `X-PAYMENT` header.
4. On success you get HTTP 200 with JSON data.

## Pricing and terms

- $0.01 USDC per call, all endpoints, all five chains.
- Resale permitted: you may resell data outputs at your own price
  (terms: https://brianbooms.com/agents/#resale).
- Machine-readable catalog: https://brianbooms.com/.well-known/agent.json

## Notes

- If a call fails with a 402 error message, read the message: it tells you
  exactly what was wrong with the payment and how to fix it.
