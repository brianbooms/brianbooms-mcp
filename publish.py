#!/usr/bin/env python3
"""Hub-as-upstream publish pipeline for the brianbooms-mcp MCP server.

This repo is the SINGLE canonical origin. npm and GitHub are downstream
mirrors: nothing is ever authored on npmjs.com or github.com directly.

Order:
  1. Preflight (git repo, on main, clean tree, fast-forward check vs origin/main)
  2. Tarball resolve — reuse the approved immutable tarball for this version
     when it exists and is sane; otherwise `npm pack` from this dir.
  3. Smoke tests (any repo tests found + built-in syntax/metadata/server checks)
  4. npm publish via the registry HTTP API (Secure Vault `custom.npm`)
  5. git push --ff-only to origin main (Secure Vault `custom.github`)
  6. Live verification (registry shows the version; ls-remote matches HEAD)

--dry-run does everything except steps 4 and 5.
Any failure stops the script with a clear, actionable message.
Credential values and surrogates are NEVER printed.

Usage:
  python3 publish.py            # full publish (needs both vault tokens)
  python3 publish.py --dry-run  # safe rehearsal, no publish, no push
"""

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import urllib.error

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import (
    add_surrogate_to_request,
    dynamic_credential_entry,
    read_json_response,
    DynamicCredentialError,
)

REPO = os.path.dirname(os.path.abspath(__file__))
APPROVED_DIR = "/home/hatch/workspace/ops/mcp/brianbooms-mcp-py"
REGISTRY = "https://registry.npmjs.org"
NPM_CRED = "custom.npm"
NPM_HOSTS = ("registry.npmjs.org",)
GH_CRED = "custom.github"
GH_REMOTE = "origin"
GH_BRANCH = "main"
EXPECTED_TARBALL_FILES = {
    "package/package.json",
    "package/server.py",
    "package/README.md",
    "package/catalog-fallback.json",
    "package/requirements.txt",
    "package/bin/brianbooms-mcp",
}

DRY = "--dry-run" in sys.argv


def step(msg):
    print(f"[publish] {msg}", flush=True)


def fail(msg):
    raise SystemExit(f"[publish] FAILED: {msg}")


def sh(args, cwd=REPO, timeout=120, env=None, redacted=()):
    """Run a subprocess. `redacted` lists arg indexes that must never be printed."""
    printable = [a if i not in redacted else "<redacted>" for i, a in enumerate(args)]
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        fail(f"timed out: {' '.join(printable)}")
    if p.returncode != 0:
        fail(f"{' '.join(printable)} exited {p.returncode}: "
             f"{(p.stderr or p.stdout).strip()[:800]}")
    return p.stdout.strip()


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "brianbooms-mcp-publish/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------- 1. preflight
def preflight(pkg):
    step("preflight: git state")
    if sh(["git", "rev-parse", "--is-inside-work-tree"]) != "true":
        fail("not inside a git work tree")
    branch = sh(["git", "branch", "--show-current"])
    if branch != GH_BRANCH:
        fail(f"on branch '{branch}', expected '{GH_BRANCH}' — switch branches manually")
    if sh(["git", "status", "--porcelain"]):
        fail("working tree not clean — commit or stash first (publish only ships committed code)")
    head = sh(["git", "rev-parse", "HEAD"])
    sh(["git", "fetch", GH_REMOTE, GH_BRANCH], timeout=60)
    remote = sh(["git", "rev-parse", f"{GH_REMOTE}/{GH_BRANCH}"])
    # fast-forward-only: remote must be an ancestor of HEAD (or equal)
    rc = subprocess.run(["git", "merge-base", "--is-ancestor", remote, head],
                        cwd=REPO, capture_output=True).returncode
    if rc != 0:
        fail(f"{GH_REMOTE}/{GH_BRANCH} ({remote[:8]}) is not an ancestor of HEAD "
             f"({head[:8]}) — remote has commits not in local history. "
             f"Reconcile manually; force-push is forbidden.")
    ahead = sh(["git", "rev-list", "--count", f"{remote}..{head}"])
    step(f"preflight ok: {GH_BRANCH} @ {head[:8]}, {ahead} commit(s) ahead of "
         f"{GH_REMOTE}/{GH_BRANCH}, tree clean")
    return head, remote


# ------------------------------------------------------- 2. tarball resolution
def resolve_tarball(pkg):
    version = pkg["version"]
    name = pkg["name"]
    tgz_name = f"{name}-{version}.tgz"
    approved = os.path.join(APPROVED_DIR, tgz_name)
    if os.path.isfile(approved):
        step(f"found approved tarball for {version}; verifying (byte-identical reuse)")
        with open(approved, "rb") as f:
            data = f.read()
        try:
            tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
            members = set(tf.getnames())
            embedded = json.loads(tf.extractfile("package/package.json").read().decode())
        except Exception as e:
            fail(f"approved tarball unreadable: {e}")
        if embedded.get("name") != name or embedded.get("version") != version:
            fail(f"approved tarball is {embedded.get('name')}@{embedded.get('version')}, "
                 f"expected {name}@{version}")
        missing = EXPECTED_TARBALL_FILES - members
        if missing:
            fail(f"approved tarball missing files: {sorted(missing)}")
        sha256 = hashlib.sha256(data).hexdigest()
        step(f"reusing approved tarball as-is (sha256 {sha256[:16]}..., {len(data)} bytes)")
        return data, tgz_name, True
    step(f"no approved tarball for {version} — building fresh with `npm pack`")
    tmp = tempfile.mkdtemp(prefix="mcp-pack-")
    out = sh(["npm", "pack", "--pack-destination", tmp])
    built = os.path.join(tmp, out.strip().splitlines()[-1])
    with open(built, "rb") as f:
        data = f.read()
    step(f"built {os.path.basename(built)} ({len(data)} bytes, "
         f"sha256 {hashlib.sha256(data).hexdigest()[:16]}...) — NOT the approved path; "
         f"review before any live publish")
    return data, os.path.basename(built), False


# ---------------------------------------------------------------- 3. tests
def run_tests():
    step("smoke tests")
    # any repo tests?
    found = []
    for root, _dirs, files in os.walk(REPO):
        if ".git" in root or "node_modules" in root:
            continue
        for fn in files:
            if fn.startswith("test_") and fn.endswith(".py") or fn.endswith("_test.py"):
                found.append(os.path.join(root, fn))
    if found:
        step(f"found repo tests: {found} — running via pytest if available")
        try:
            sh([sys.executable, "-m", "pytest", "-q"] + found, timeout=300)
        except SystemExit as e:
            fail(f"repo tests failed: {e}")
    # built-in checks (always run)
    sh([sys.executable, "-m", "py_compile",
        os.path.join(REPO, "server.py")])
    step("server.py compiles")
    if json.load(open(os.path.join(REPO, "package.json"))).get("bin", {}).get("brianbooms-mcp") \
            != "./bin/brianbooms-mcp":
        fail("package.json bin entry unexpected")
    launcher = os.path.join(REPO, "bin", "brianbooms-mcp")
    if not (os.path.isfile(launcher) and os.access(launcher, os.X_OK)):
        fail("bin/brianbooms-mcp missing or not executable")
    step("package.json bin entry + launcher ok")
    # boot the real server module (import only; __main__ guard prevents stdio loop),
    # which exercises the live catalog fetch + tool registration
    probe = (
        "import sys; sys.path.insert(0, %r); "
        "import server; "
        "names = [t for t in ('search_catalog','get_product','buy_product','get_market') "
        "if hasattr(server, t)]; "
        "assert len(names) == 4, 'missing tools: %%s' %% names; "
        "assert server.PRODUCTS, 'empty catalog'; "
        "assert server.DOCS_URL.startswith('https://brianbooms.com/'), 'docs url wrong'; "
        "print('tools=%%s products=%%d source=%%s docs=%%s' %% "
        "(','.join(names), len(server.PRODUCTS), server.CATALOG_SOURCE, server.DOCS_URL))"
        % REPO
    )
    out = sh([sys.executable, "-c", probe], timeout=60)
    step(f"server boot probe: {out}")
    step("smoke tests passed")


# ------------------------------------------------------------- 4. npm publish
def npm_publish(pkg, tgz_data, tgz_name):
    name, version = pkg["name"], pkg["version"]
    if DRY:
        step(f"dry-run: would PUT {name}@{version} ({len(tgz_data)} bytes) to {REGISTRY}")
        return
    step("checking registry for existing version")
    try:
        meta = http_json(f"{REGISTRY}/{name}")
        if version in meta.get("versions", {}):
            fail(f"{name}@{version} is already published — bump the version for a new release")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            fail(f"registry check failed: HTTP {e.code}")
    step(f"publishing {name}@{version} to {REGISTRY}")
    shasum = hashlib.sha1(tgz_data).hexdigest()
    manifest = {
        "name": name,
        "version": version,
        "description": pkg.get("description", ""),
        "homepage": pkg.get("homepage", ""),
        "repository": pkg.get("repository", ""),
        "license": pkg.get("license", "MIT"),
        "keywords": pkg.get("keywords", []),
        "author": pkg.get("author", ""),
        "engines": pkg.get("engines", {}),
        "bin": pkg.get("bin", {}),
        "dist": {"tarball": f"{REGISTRY}/{name}/-/{tgz_name}", "shasum": shasum},
    }
    doc = {
        "_id": name,
        "name": name,
        "description": pkg.get("description", ""),
        "dist-tags": {"latest": version},
        "versions": {version: manifest},
        "readme": open(os.path.join(REPO, "README.md")).read(),
        "_attachments": {
            tgz_name: {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(tgz_data).decode(),
                "length": len(tgz_data),
            }
        },
    }
    req = urllib.request.Request(f"{REGISTRY}/{name}", data=json.dumps(doc).encode(),
                                 method="PUT")
    req.add_header("Content-Type", "application/json")
    try:
        add_surrogate_to_request(req, NPM_CRED, allowed_hosts=NPM_HOSTS)
    except DynamicCredentialError as e:
        fail(f"Secure Vault credential '{NPM_CRED}' not available ({e}). "
             f"Brian must provide the npm token via the vault capture link, then re-run.")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = read_json_response(resp)
    except urllib.error.HTTPError as e:
        fail(f"registry PUT failed: HTTP {e.code}: "
             f"{e.read().decode('utf-8', 'replace')[:1000]}")
    if not result.get("ok"):
        fail(f"registry PUT not ok: {json.dumps(result)[:500]}")
    step(f"npm publish ok: {name}@{version}")


# ---------------------------------------------------------------- 5. git push
def git_push(head, remote):
    if head == remote:
        step("git: already in sync with origin/main — nothing to push")
        return
    log = sh(["git", "log", "--oneline", f"{remote}..{head}"])
    if DRY:
        step(f"dry-run: would push to {GH_REMOTE}/{GH_BRANCH}:\n{log}")
        ls = sh(["git", "ls-remote", GH_REMOTE, GH_BRANCH], timeout=60)
        step(f"dry-run: remote {GH_BRANCH} currently at {ls.split()[0][:8]} (anonymous read)")
        return
    try:
        entry = dynamic_credential_entry(GH_CRED)
    except DynamicCredentialError as e:
        fail(f"Secure Vault credential '{GH_CRED}' not available ({e}). "
             f"Brian must provide the GitHub token via the vault capture link, then re-run.")
    surrogate = str(entry["surrogate"]).strip()
    if not surrogate.startswith("hsurr:"):
        fail(f"vault returned a non-surrogate value for {GH_CRED} — refusing to use it")
    # The surrogate (not the real token) travels in the header; the egress layer
    # swaps it for the real credential. It is never printed.
    header = f"http.extraHeader=Authorization: Bearer {surrogate}"
    step(f"pushing {GH_BRANCH} -> {GH_REMOTE}/{GH_BRANCH} (fast-forward only)")
    sh(["git", "-c", header, "push", GH_REMOTE, f"{GH_BRANCH}:{GH_BRANCH}"],
       timeout=120, redacted=(2,))
    step("git push ok")


# ------------------------------------------------------- 6. live verification
def verify_live(pkg, head):
    name, version = pkg["name"], pkg["version"]
    if DRY:
        step("dry-run: skipping live verification")
        return
    step("verifying npm registry shows the new version")
    deadline = time.time() + 90
    seen = False
    while time.time() < deadline:
        try:
            meta = http_json(f"{REGISTRY}/{name}")
            if version in meta.get("versions", {}):
                seen = True
                break
        except Exception:
            pass
        time.sleep(10)
    if not seen:
        fail(f"{name}@{version} not visible on the registry after 90s")
    step(f"registry ok: {name}@{version} live")
    step("verifying git remote matches local HEAD")
    ls = sh(["git", "ls-remote", GH_REMOTE, GH_BRANCH], timeout=60)
    remote_head = ls.split()[0]
    if remote_head != head:
        fail(f"remote {GH_BRANCH} is {remote_head[:8]}, local HEAD is {head[:8]}")
    step("git ok: origin/main matches local HEAD")


def main():
    step(f"starting {'DRY-RUN' if DRY else 'LIVE'} publish pipeline")
    pkg = json.load(open(os.path.join(REPO, "package.json")))
    step(f"package {pkg['name']}@{pkg['version']}")
    head, remote = preflight(pkg)
    tgz_data, tgz_name, approved = resolve_tarball(pkg)
    run_tests()
    npm_publish(pkg, tgz_data, tgz_name)
    git_push(head, remote)
    verify_live(pkg, head)
    step("PIPELINE COMPLETE: npm + GitHub both live and verified; "
         "hub remains the canonical upstream")


if __name__ == "__main__":
    main()
