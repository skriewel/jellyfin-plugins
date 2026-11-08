# Jellyfin plugins by skriewel

One Jellyfin plugin repository for all plugins below.

## Install

*Dashboard → Plugins → Repositories → +* and add:

```text
https://raw.githubusercontent.com/skriewel/jellyfin-plugins/main/manifest.json
```

Then install the plugins from the catalog and restart Jellyfin. Remove the
old per-plugin repository entries for these plugins, so that each plugin is
offered by exactly one repository.

## Plugins

| Plugin | Latest | Overview |
|---|---|---|
| Alternative Titles | 1.0.0.0 | Search by English, German, romanized and original titles |
| Companions | 1.0.7.0 | Soundtracks, books and audiobooks for your movies |
| Content Warnings | 1.0.0.0 | Content warnings from DoesTheDogDie.com |
| Franchise Explorer | 0.8.9.26 | Experimental virtual franchise browsing for Jellyfin 12.2 (use caution). |
| Hover Cards | 1.0.4.1 | Streaming-style hover previews for media cards |
| Pitch Meetings | 1.0.0.1 | Links Pitch Meeting videos to their movies and shows |
| Previously On | 1.0.0.0 | Previously on: recap after a break |

## How this catalog is built

`build_manifest.py` merges the `manifest.json` of each repo listed in
`plugins.json` and adds GitHub releases with a ZIP that a plugin's manifest
does not list yet. The workflow runs hourly, on demand, and when a plugin
repo sends a `plugin-released` repository dispatch. This README's table is
generated; edit the template in `build_manifest.py`.
