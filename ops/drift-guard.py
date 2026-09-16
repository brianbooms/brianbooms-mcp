#!/usr/bin/env python3
"""Drift guard for the brianbooms-mcp hub-as-upstream pipeline. READ-ONLY.

Compares three copies that must all say the same thing:
  1. npm README      — the published package's README (registry metadata)
  2. GitHub README   — raw README.md on origin/main
  3. Hub docs        — https://brianbooms.com/agents/ (the canonical upstream)

Signals compared: version mentions, product-count mentions, canonical doc URL
presence, Suno disclosure presence.

Exit codes: 0 = no drift, 1 = drift detected (lines prefixed DRIFT:), 2 = check error.
Never writes, never restamps. Restamping is a human decision (Brian's tap):
run publish.py from the canonical repo after reconciling the source.

Usage: python3 drift-guard.py
"""

import gzip
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request

NPM_META = "https://registry.npmjs.org/brianbooms-mcp"
GH_README = ("https://raw.githubusercontent.com/brianbooms/brianbooms-mcp"
             "/main/README.md")
HUB_DOCS = "https://brianbooms.com/agents/"
UA = {"User-Agent": "brianbooms-mcp-drift-guard/1.0"}
CANONICAL_DOCS = "https://brianbooms.com/agents"


def fetch(url, timeout=30):
    # urllib intermittently hits IncompleteRead through the egress proxy on hub
    # pages (known host quirk); curl is the proven fallback.
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        last = e
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "-A", UA["User-Agent"], url],
            capture_output=True, timeout=timeout + 5, check=True)
        return out.stdout.decode("utf-8", "replace")
    except Exception as e2:
        raise RuntimeError(f"fetch failed for {url}: {last} / curl: {e2}")


def npm_readme(meta):
    """Ground truth: the README.md inside the latest published tarball.

    (The registry metadata `readme` field is inconsistently populated across
    clients; the tarball is what `npm install` actually ships.)
    """
    latest = meta.get("dist-tags", {}).get("latest")
    if not latest:
        raise RuntimeError("registry has no dist-tags.latest")
    ver = meta.get("versions", {}).get(latest, {})
    tarball_url = (ver.get("dist") or {}).get("tarball")
    if not tarball_url:
        raise RuntimeError(f"no tarball URL for version {latest}")
    req = urllib.request.Request(tarball_url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except Exception as e:
        raise RuntimeError(f"tarball download failed for {tarball_url}: {e}")
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
        member = next((m for m in tf.getnames()
                       if m.lower().endswith("readme.md")), None)
        if not member:
            raise RuntimeError("no README.md in tarball")
        return latest, tf.extractfile(member).read().decode("utf-8", "replace")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"tarball unreadable: {e}")


def versions(text):
    # matches 1.0.3 and v1.0.3 (no \b before the digit: "v1" has no boundary)
    return sorted(set(re.findall(r"[vV]?(\d+\.\d+\.\d+)", text)))


def product_counts(text):
    # e.g. "24 agent-buyable", "33 products", "24 SKUs"
    return sorted(set(re.findall(r"\b(\d{2,3})\s+(?:agent-buyable|products|SKUs|product)\b",
                                 text, re.IGNORECASE)))


def signals(name, text):
    return {
        "versions": versions(text),
        "product_counts": product_counts(text),
        "has_docs_url": CANONICAL_DOCS in text,
        "has_suno_disclosure": bool(re.search(r"suno", text, re.IGNORECASE)),
        "has_homepage_link": "brianbooms.com" in text,
    }


def main():
    try:
        meta = json.loads(fetch(NPM_META))
        latest, npm_readme_text = npm_readme(meta)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 2
    try:
        gh_readme = fetch(GH_README)
        hub_docs = fetch(HUB_DOCS)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 2

    sig = {
        f"npm README (@{latest})": signals("npm", npm_readme_text),
        "GitHub README (main)": signals("gh", gh_readme),
        "hub docs (/agents/)": signals("hub", hub_docs),
    }

    drift = []

    # 1. version agreement: npm latest vs versions mentioned in GitHub README
    gh_versions = sig["GitHub README (main)"]["versions"]
    if latest != "?" and latest not in gh_versions:
        drift.append(f"github README never mentions npm latest {latest} "
                     f"(mentions: {gh_versions or 'none'})")

    # 2. product-count agreement across all three
    counts = {k: v["product_counts"] for k, v in sig.items()}
    flat = {c for cs in counts.values() for c in cs}
    if len(flat) > 1:
        drift.append(f"product-count mismatch: " +
                     "; ".join(f"{k}={v or 'none'}" for k, v in counts.items()))

    # 3. canonical docs URL present in npm + GitHub copies
    for k in ("npm README (@%s)" % latest, "GitHub README (main)"):
        if not sig[k]["has_docs_url"]:
            drift.append(f"{k} does not link the canonical docs URL {CANONICAL_DOCS}/")

    # 4. Suno disclosure present everywhere
    for k, v in sig.items():
        if not v["has_suno_disclosure"]:
            drift.append(f"{k} has no Suno disclosure mention")

    # 5. hub link present everywhere
    for k, v in sig.items():
        if not v["has_homepage_link"]:
            drift.append(f"{k} links nowhere to brianbooms.com")

    print(f"checked: npm@{latest} | github main | {HUB_DOCS}")
    if drift:
        for d in drift:
            print(f"DRIFT: {d}")
        return 1
    print("OK: no drift — npm, GitHub, and hub docs agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
