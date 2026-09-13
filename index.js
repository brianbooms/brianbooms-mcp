#!/usr/bin/env node
// brianbooms-mcp — MCP server for Brian Booms' agent-commerce storefront.
// Read-only discovery tools: catalog, product details, x402 purchase
// instructions (parsed live from the 402 response), and Booms Rewards info.
// The server never moves money: the calling agent pays with its own x402 client.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const CATALOG_URL = "https://brianbooms.com/.well-known/purchase-catalog.json";
const BUY_BASE = "https://pay.brianbooms.com/api/v1/buy/";
const REWARDS_INFO = "https://pay.brianbooms.com/api/v1/rewards/info";
const PARTNER_URL = "https://brianbooms.com/partner/";

let catalogCache = null;
let catalogAt = 0;
async function catalog() {
  if (catalogCache && Date.now() - catalogAt < 10 * 60 * 1000) return catalogCache;
  const r = await fetch(CATALOG_URL, { headers: { "User-Agent": "brianbooms-mcp/1.0" } });
  if (!r.ok) throw new Error("catalog fetch failed: " + r.status);
  const d = await r.json();
  catalogCache = d.products || d.items || [];
  catalogAt = Date.now();
  return catalogCache;
}

const server = new McpServer({ name: "brianbooms", version: "1.0.0" });

server.tool(
  "catalog",
  "List everything buyable from Brian Booms (ambient music, ringtones, wallpapers, track leases, game licenses, commissions). Returns sku, name, and USD price for all products.",
  {},
  async () => {
    const items = await catalog();
    const list = items.map((p) => ({
      sku: p.sku || p.id,
      name: p.name,
      price_usd: p.price_usd || p.price || p.priceUsd,
    }));
    return { content: [{ type: "text", text: JSON.stringify(list, null, 2) }] };
  }
);

server.tool(
  "product",
  "Full details for one product: description, price, delivery, and buy URL.",
  { sku: z.string().describe("Product SKU from the catalog tool") },
  async ({ sku }) => {
    const items = await catalog();
    const p = items.find((x) => (x.sku || x.id) === sku);
    if (!p) return { content: [{ type: "text", text: JSON.stringify({ error: "unknown sku", sku }) }] };
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          sku: p.sku || p.id,
          name: p.name,
          price_usd: p.price_usd || p.price || p.priceUsd,
          description: p.description,
          delivery: p.delivery,
          buy_url: BUY_BASE + (p.sku || p.id),
        }, null, 2),
      }],
    };
  }
);

server.tool(
  "purchase_instructions",
  "Exact x402 payment requirements for buying a product: pay-to address, amount, asset, network, and facilitator — parsed live from the product's 402 response. Your agent pays with its own x402/EVM wallet, then downloads instantly.",
  { sku: z.string().describe("Product SKU from the catalog tool") },
  async ({ sku }) => {
    const r = await fetch(BUY_BASE + sku, { headers: { "User-Agent": "brianbooms-mcp/1.0" } });
    if (r.status !== 402) {
      return { content: [{ type: "text", text: JSON.stringify({ error: "expected 402, got " + r.status, sku }) }] };
    }
    const header = r.headers.get("payment-required") || r.headers.get("PAYMENT-REQUIRED");
    let reqs = null;
    try {
      const decoded = JSON.parse(Buffer.from(header, "base64").toString("utf8"));
      const a = (decoded.accepts && decoded.accepts[0]) || {};
      reqs = {
        scheme: a.scheme, network: a.network, asset: a.asset,
        amount: a.maxAmountRequired, payTo: a.payTo,
        facilitator: "https://facilitator.xpay.sh",
      };
    } catch { /* fall through */ }
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          sku,
          buy_url: BUY_BASE + sku,
          flow: "GET the buy_url with an x402 v1 payment (EVM, USDC on Base). On success the response is your order: download link or fulfillment status.",
          payment_requirements: reqs,
          rewards: "Earn 10% back in Booms Rewards credit on every purchase (15% on first). Details: " + REWARDS_INFO,
        }, null, 2),
      }],
    };
  }
);

server.tool(
  "rewards",
  "How Booms Rewards works for buyers and for merchants: earn rates, referral rates, and how a store joins free.",
  {},
  async () => ({
    content: [{
      type: "text",
      text: [
        "Booms Rewards — shared loyalty for independent stores, settled in USDC on Base.",
        "BUYERS: earn 10% back in store credit on every purchase at brianbooms.com (15% on the first purchase, 20% when buying via a referral link). Credit spends like cash on future purchases.",
        "REFERRALS: share a ?ref= link and earn 5% of everything your referrals buy.",
        "MERCHANTS: join free at " + PARTNER_URL + " — verify your domain (~60 seconds, one meta tag), no wallet, no reserve, no agreement, no fees. Your buyers earn portable credit redeemable across the network.",
        "Machine-readable program: https://brianbooms.com/partner/program.json",
      ].join("\n"),
    }],
  })
);

const transport = new StdioServerTransport();
await server.connect(transport);
