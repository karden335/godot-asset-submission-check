from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from asset_guard import run


LICENSE = """MIT License

Copyright (c) 2026 Example Publisher

Permission is hereby granted, free of charge, to any person obtaining a copy.
"""


class GuardTests(unittest.TestCase):
    def fixture(self) -> tuple[Path, dict]:
        root = Path(tempfile.mkdtemp())
        (root / ".gitignore").write_text("dist/\n", encoding="utf-8")
        for directory in ("dist", "media", "docs"):
            (root / directory).mkdir()
        config = {
            "name": "Example Godot Addon",
            "version": "0.1.0",
            "addon_directory": "example_addon",
            "license": "MIT",
            "uses_ai": True,
            "archive": "dist/example.zip",
            "thumbnail": "media/store-thumbnail.png",
            "thumbnail_source": "media/store-thumbnail.svg",
            "listing": "docs/ASSET_STORE_SUBMISSION.md",
            "thumbnail_max_bytes": 5_000_000,
            "thumbnail_max_text_elements": 2,
            "minimum_catalog_font_px": 20,
        }
        config_path = root / "asset-guard.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        listing = """# Submission

- **Name:** Example Godot Addon
- **Summary:** Finds predictable packaging mistakes before moderation.
- **Asset type:** Addon
- **License:** MIT
- **Source:** https://github.com/example/addon
- **Minimum Godot version:** 4.4
- **Version:** 0.1.0
- **Tags:** Editor, Testing
- **Archive:** `dist/example.zip`
- **Thumbnail:** `media/store-thumbnail.png`

## Detailed description

This add-on finds predictable release mistakes before a submission reaches moderation. It checks one focused workflow and reports each problem with a direct fix. The example includes installation steps, a reproducible result, and honest limits so reviewers and users can confirm the behavior. The package remains local and sends no project data anywhere.

## AI usage disclosure

> AI assisted the code and listing draft. The publisher reviewed the output and ran the tests.
"""
        (root / config["listing"]).write_text(listing, encoding="utf-8")
        # Enough PNG structure for the dependency-free dimension reader.
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 1280, 720) + b"\x08\x06\x00\x00\x00"
        (root / config["thumbnail"]).write_bytes(png)
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" aria-label="Example Godot Addon">
<text x="430" y="315" font-size="84">Example Godot</text>
<text x="430" y="420" font-size="84">Addon</text>
</svg>"""
        (root / config["thumbnail_source"]).write_text(svg, encoding="utf-8")
        prefix = "addons/example_addon/"
        files = {
            prefix + "LICENSE": LICENSE,
            prefix + "README.md": "# Example\n",
            prefix + "plugin.cfg": """[plugin]
name="Example"
description="Example plugin"
author="Example Publisher"
version="0.1.0"
script="plugin.gd"
""",
            prefix + "plugin.gd": "@tool\nextends EditorPlugin\n",
        }
        with ZipFile(root / config["archive"], "w", ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return config_path, config

    def codes(self, path: Path) -> set[str]:
        return {item.code for item in run(path)[1]}

    def test_valid_submission_passes(self) -> None:
        path, _ = self.fixture()
        report, findings = run(path)
        self.assertTrue(report["passed"], findings)
        self.assertEqual(report["errors"], 0)

    def test_duplicate_disclosure_is_rejected(self) -> None:
        path, config = self.fixture()
        listing = path.parent / config["listing"]
        text = listing.read_text(encoding="utf-8")
        disclosure = "AI assisted the code and listing draft. The publisher reviewed the output and ran the tests."
        listing.write_text(text.replace("This add-on finds", disclosure + " This add-on finds"), encoding="utf-8")
        self.assertIn("AI_DISCLOSURE_DUPLICATE", self.codes(path))

    def test_small_catalog_text_is_rejected(self) -> None:
        path, config = self.fixture()
        source = path.parent / config["thumbnail_source"]
        source.write_text(source.read_text().replace('font-size="84"', 'font-size="40"'), encoding="utf-8")
        self.assertIn("THUMBNAIL_TEXT_SMALL", self.codes(path))

    def test_likely_text_overflow_is_rejected(self) -> None:
        path, config = self.fixture()
        source = path.parent / config["thumbnail_source"]
        source.write_text(source.read_text().replace('x="430"', 'x="1000"'), encoding="utf-8")
        self.assertIn("THUMBNAIL_TEXT_OVERFLOW", self.codes(path))

    def test_file_outside_addon_is_rejected(self) -> None:
        path, config = self.fixture()
        archive_path = path.parent / config["archive"]
        with ZipFile(archive_path, "a", ZIP_DEFLATED) as archive:
            archive.writestr("project.godot", "[application]\n")
        self.assertIn("ARCHIVE_OUTSIDE_ADDON", self.codes(path))

    def test_missing_plugin_script_is_rejected(self) -> None:
        path, config = self.fixture()
        archive_path = path.parent / config["archive"]
        with ZipFile(archive_path) as source:
            entries = {name: source.read(name) for name in source.namelist() if not name.endswith("plugin.gd")}
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        self.assertIn("PLUGIN_SCRIPT_MISSING", self.codes(path))


if __name__ == "__main__":
    unittest.main()
