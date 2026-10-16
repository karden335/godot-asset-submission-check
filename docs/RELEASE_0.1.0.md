# Godot Asset Submission Check v0.1.0

First public release of the free, local Godot Asset Store submission preflight.

- Checks current listing, tag, AI disclosure, thumbnail and upload ZIP rules.
- Reads PNG and JPEG dimensions without third-party packages.
- Verifies `addons/asset_name/`, license metadata, `plugin.cfg`, its script and `.gdextension` libraries.
- Emits readable findings or JSON for CI.
- Sends no project data and performs no uploads.

This is an independent community tool. Passing does not guarantee approval; functional testing and human visual review remain required.
