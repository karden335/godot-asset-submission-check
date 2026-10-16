# Godot Asset Submission Check

A dependency-free preflight for Godot Asset Store add-ons. It checks the listing record, upload ZIP, bundled license, `plugin.cfg`, thumbnail dimensions and conservative catalog-size text rules before a human moderator sees the submission.

The checker follows the official requirements and recommendations published at <https://store.godotengine.org/guidelines/>. It is an independent community tool and is not affiliated with or endorsed by the Godot Foundation.

## Quick start

Requires Python 3.10 or newer. It never uploads files and has no telemetry.

```sh
cp sample/asset-guard.json ./asset-guard.json
cp sample/ASSET_STORE_SUBMISSION.md ./docs/ASSET_STORE_SUBMISSION.md
# Edit both files for your add-on, then run:
python3 asset_guard.py --config asset-guard.json
```

Use `--json` in CI. Use `--strict` only when you want recommendations, such as removing repository metadata from the ZIP, to fail the command.

## Checks

- Required listing fields, one to ten tags, no asset-name tag and no singular/plural duplicate.
- A substantive English summary and description instead of a repository URL alone.
- Dedicated AI disclosure when configured, limited to 256 characters and absent from the detailed description.
- A PNG or JPEG thumbnail with a 16:9 ratio and configurable minimum dimensions.
- Optional SVG source checks: only the asset name as text, no tiny catalog text, and a matching accessibility label.
- A ZIP rooted at `addons/asset_name/`, without path traversal, rejected standalone binaries or NuGet packages.
- Bundled `LICENSE`, `README.md`, `plugin.cfg`, implementation files, plugin metadata and referenced plugin script.
- MIT copyright year and holder when the configured license is MIT.
- Referenced `.gdextension` libraries are present in the ZIP.

Passing the checker cannot prove that an add-on works, that its claims are accurate or that a moderator will approve it. Test the add-on in every declared Godot version and inspect the thumbnail at 320×180 before submission.

## Optional preparation kit

The [$3 Godot Asset Submission Guard kit](https://karrden.itch.io/godot-asset-submission-guard) adds a deterministic ZIP/report command, an offline 1280x720 thumbnail maker, editable listing and CI templates, a final upload checklist, factual moderator-reply templates, and a tested sample add-on.

It is also included with the two other release-safety kits in the [$5 Godot Release Safety Bundle](https://itch.io/s/204610/godot-release-safety-bundle). The core checker in this repository remains free and MIT licensed.

## Configuration

See [`sample/asset-guard.json`](sample/asset-guard.json) and [`sample/ASSET_STORE_SUBMISSION.md`](sample/ASSET_STORE_SUBMISSION.md). Relative paths resolve from the configuration file.

## Why this exists

The Asset Store added a thumbnail-guidelines reminder on 2026-10-14 and its current rules explicitly reject unreadable, text-dominated, misleading or cluttered thumbnails. The current store also requires working plug-ins, a bundled matching license, `addons/asset_name/`, proper English, at least one tag and AI disclosure when applicable. Those checks are predictable enough to automate before entering the review queue.

## Test

```sh
python3 -m unittest discover -s tests -v
```

MIT licensed.
