#!/usr/bin/env python3
"""Build one Jellyfin plugin repository manifest from several plugin repos.

Sources, per entry in plugins.json:
  1. The plugin repo's own manifest (default: manifest.json on its default
     branch). It stays the source of truth for metadata and versions.
  2. GitHub releases of that repo with a .zip asset whose version is missing
     from (1). Their MD5 checksum is computed from the downloaded ZIP.

If a plugin repo cannot be read, its entry from the previous catalog
manifest is kept, so a network hiccup never removes a plugin.

Optional per-plugin keys in plugins.json:
  "branch"      branch to read the manifest from (default: repo default branch)
  "manifest"    path of the manifest in the repo (default: manifest.json)
  "targetAbi"   targetAbi for release-only versions (default: newest known)
  "overrides"   fields replacing the plugin's own metadata (name, overview, ...)

Usage: build_manifest.py [--verify] [--check]
  --verify  download every listed ZIP and compare its MD5 with the manifest
  --check   do not write files; exit 1 if manifest.json would change
Set GH_TOKEN (or GITHUB_TOKEN) to avoid GitHub API rate limits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "plugins.json"
MANIFEST = ROOT / "manifest.json"
README = ROOT / "README.md"
CATALOG_URL = "https://raw.githubusercontent.com/skriewel/jellyfin-plugins/main/manifest.json"
VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){1,3})$")
META_KEYS = ("guid", "name", "description", "overview", "owner", "category", "imageUrl")
VERSION_KEYS = ("version", "changelog", "targetAbi", "sourceUrl", "checksum", "timestamp")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def http_get(url: str, api: bool = False) -> bytes:
    headers = {"User-Agent": "jellyfin-plugin-catalog"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
    if TOKEN and (api or url.startswith("https://raw.githubusercontent.com/")):
        headers["Authorization"] = f"Bearer {TOKEN}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        return response.read()


def api_json(path: str):
    return json.loads(http_get(f"https://api.github.com/{path}", api=True))


def version_key(version: str):
    return tuple(int(part) for part in version.split("."))


def collect(plugin: dict) -> list[dict]:
    repo = plugin["repo"]
    branch = plugin.get("branch") or api_json(f"repos/{repo}")["default_branch"]
    path = plugin.get("manifest", "manifest.json")
    entries = json.loads(http_get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"))
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{repo}/{path} is not a non-empty JSON array")

    releases = [r for r in api_json(f"repos/{repo}/releases?per_page=100") if not r.get("draft")]
    result = []
    for entry in entries:
        meta = {key: entry[key] for key in META_KEYS if entry.get(key) not in (None, "")}
        meta.update(plugin.get("overrides", {}))
        if "guid" not in meta or "name" not in meta:
            raise ValueError(f"{repo}: manifest entry without guid/name")
        versions = {v["version"]: {k: v[k] for k in VERSION_KEYS if k in v} for v in entry.get("versions", [])}
        abi = plugin.get("targetAbi") or next(
            (v["targetAbi"] for _, v in sorted(versions.items(), key=lambda kv: version_key(kv[0]), reverse=True)
             if v.get("targetAbi")), None)
        # Releases only fill gaps when the repo hosts exactly one plugin.
        for release in releases if len(entries) == 1 else []:
            match = VERSION_RE.match(release.get("tag_name", ""))
            zips = [a for a in release.get("assets", []) if a["name"].lower().endswith(".zip")]
            if not match or not zips or match.group(1) in versions:
                continue
            if not abi:
                print(f"  ! {repo} {release['tag_name']}: no targetAbi known, skipped", file=sys.stderr)
                continue
            if len(zips) > 1:
                print(f"  ! {repo} {release['tag_name']}: several ZIPs, using {zips[0]['name']}", file=sys.stderr)
            data = http_get(zips[0]["browser_download_url"])
            body = (release.get("body") or "").strip()
            versions[match.group(1)] = {
                "version": match.group(1),
                "changelog": body or release.get("name") or release["html_url"],
                "targetAbi": abi,
                "sourceUrl": zips[0]["browser_download_url"],
                "checksum": hashlib.md5(data).hexdigest(),
                "timestamp": release.get("published_at") or release.get("created_at"),
            }
            print(f"  + {meta['name']} {match.group(1)} from GitHub release (not in the plugin's manifest)")
        meta["versions"] = sorted(versions.values(), key=lambda v: version_key(v["version"]), reverse=True)
        result.append(meta)
    return result


def verify(manifest: list[dict]) -> int:
    failures = 0
    for plugin in manifest:
        for version in plugin["versions"]:
            try:
                actual = hashlib.md5(http_get(version["sourceUrl"])).hexdigest()
            except (urllib.error.URLError, OSError) as error:
                print(f"  ✗ {plugin['name']} {version['version']}: download failed ({error})")
                failures += 1
                continue
            if actual != version.get("checksum", "").lower():
                print(f"  ✗ {plugin['name']} {version['version']}: MD5 {actual} ≠ {version.get('checksum')}")
                failures += 1
    print(f"Verified {sum(len(p['versions']) for p in manifest)} downloads, {failures} problem(s).")
    return failures


def readme(manifest: list[dict]) -> str:
    rows = "\n".join(
        f"| {p['name']} | {p['versions'][0]['version'] if p['versions'] else '–'} | {p.get('overview', '').replace('|', '/')} |"
        for p in sorted(manifest, key=lambda p: p["name"].lower()))
    return f"""# Jellyfin plugins by skriewel

One Jellyfin plugin repository for all plugins below.

## Install

*Dashboard → Plugins → Repositories → +* and add:

```text
{CATALOG_URL}
```

Then install the plugins from the catalog and restart Jellyfin. Remove the
old per-plugin repository entries for these plugins, so that each plugin is
offered by exactly one repository.

## Plugins

| Plugin | Latest | Overview |
|---|---|---|
{rows}

## How this catalog is built

`build_manifest.py` merges the `manifest.json` of each repo listed in
`plugins.json` and adds GitHub releases with a ZIP that a plugin's manifest
does not list yet. The workflow runs hourly, on demand, and when a plugin
repo sends a `plugin-released` repository dispatch. This README's table is
generated; edit the template in `build_manifest.py`.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    previous = {p["guid"]: p for p in json.loads(MANIFEST.read_text(encoding="utf-8"))} if MANIFEST.exists() else {}
    previous_by_repo: dict[str, list[dict]] = {}
    for p in previous.values():
        for v in p.get("versions", []):
            m = re.match(r"https://github\.com/([^/]+/[^/]+)/", v.get("sourceUrl", ""))
            if m:
                previous_by_repo.setdefault(m.group(1).lower(), [])
                if p not in previous_by_repo[m.group(1).lower()]:
                    previous_by_repo[m.group(1).lower()].append(p)

    manifest, seen, errors = [], {}, 0
    for plugin in config["plugins"]:
        print(f"{plugin['repo']}")
        try:
            entries = collect(plugin)
        except Exception as error:  # keep the last good entry for this repo
            errors += 1
            entries = previous_by_repo.get(plugin["repo"].lower(), [])
            print(f"  ! could not read ({error}); keeping {len(entries)} previous entr{'y' if len(entries) == 1 else 'ies'}",
                  file=sys.stderr)
        for entry in entries:
            if entry["guid"] in seen:
                print(f"  ✗ GUID {entry['guid']} of {entry['name']} already used by {seen[entry['guid']]}", file=sys.stderr)
                return 1
            seen[entry["guid"]] = entry["name"]
            print(f"  {entry['name']}: {len(entry['versions'])} version(s), latest "
                  f"{entry['versions'][0]['version'] if entry['versions'] else '–'}")
            manifest.append(entry)

    manifest.sort(key=lambda p: p["name"].lower())
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    changed = not MANIFEST.exists() or MANIFEST.read_text(encoding="utf-8") != text
    if args.check:
        print("manifest.json is up to date." if not changed else "manifest.json would change.")
        return 1 if changed else 0
    if changed:
        MANIFEST.write_text(text, encoding="utf-8", newline="\n")
    README.write_text(readme(manifest), encoding="utf-8", newline="\n")
    print(f"{len(manifest)} plugins; manifest.json {'updated' if changed else 'unchanged'}.")
    if args.verify and verify(manifest):
        return 1
    return 1 if errors and not manifest else 0


if __name__ == "__main__":
    sys.exit(main())
