#!/usr/bin/env python3
"""Preflight a Godot Asset Store add-on before it reaches moderation."""

from __future__ import annotations

import argparse
import configparser
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


VERSION = "0.1.0"
FORBIDDEN_PARTS = {".git", ".github", ".DS_Store", "__MACOSX", "Thumbs.db"}
REJECTED_SUFFIXES = {".app", ".dmg", ".exe", ".msi", ".nupkg"}
IMPLEMENTATION_SUFFIXES = {
    ".gd", ".cs", ".gdextension", ".tscn", ".tres", ".shader", ".gdshader",
    ".png", ".jpg", ".jpeg", ".webp", ".svg", ".wav", ".ogg", ".mp3",
    ".glb", ".gltf", ".obj", ".fbx", ".ttf", ".otf",
}
SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    path: str = ""


class Guard:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def error(self, code: str, message: str, path: Path | str = "") -> None:
        self.findings.append(Finding("error", code, message, str(path)))

    def warning(self, code: str, message: str, path: Path | str = "") -> None:
        self.findings.append(Finding("warning", code, message, str(path)))

    def require(self, condition: bool, code: str, message: str, path: Path | str = "") -> None:
        if not condition:
            self.error(code, message, path)


def normalize(value: str) -> str:
    return " ".join(value.split())


def markdown_section(markdown: str, heading: str) -> str:
    pattern = rf"(?ms)^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, markdown)
    return match.group(1).strip() if match else ""


def listing_field(markdown: str, label: str) -> str:
    match = re.search(rf"(?m)^- \*\*{re.escape(label)}:\*\*\s*(.+?)\s*$", markdown)
    return match.group(1).strip() if match else ""


def image_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("thumbnail must be a PNG or JPEG")
    offset = 2
    while offset + 4 <= len(data):
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if length < 2 or offset + length > len(data):
            break
        if marker in SOF_MARKERS and offset + 7 <= len(data):
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return width, height
        offset += length
    raise ValueError("JPEG dimensions could not be read")


def number(value: str) -> float:
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
    return float(match.group(1)) if match else 0.0


def resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def read_config(path: Path) -> tuple[Path, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"name", "addon_directory", "archive", "thumbnail", "listing"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"config is missing: {', '.join(missing)}")
    return path.parent.resolve(), payload


def check_listing(guard: Guard, base: Path, config: dict) -> None:
    path = resolve(base, config["listing"])
    if not path.is_file():
        guard.error("LISTING_MISSING", "listing record does not exist", path)
        return
    markdown = path.read_text(encoding="utf-8")
    required = (
        "Name", "Summary", "Asset type", "License", "Source",
        "Minimum Godot version", "Version", "Tags", "Archive", "Thumbnail",
    )
    fields = {label: listing_field(markdown, label) for label in required}
    for label, value in fields.items():
        guard.require(bool(value), "LISTING_FIELD_MISSING", f"missing listing field: {label}", path)

    guard.require(fields["Name"] == config["name"], "NAME_MISMATCH", "listing name differs from config", path)
    guard.require(fields["Asset type"].casefold() == "addon", "ASSET_TYPE", "asset type must be Addon", path)
    expected_license = config.get("license", "MIT")
    guard.require(fields["License"].casefold() == expected_license.casefold(), "LICENSE_MISMATCH", "listing license differs from config", path)
    guard.require(fields["Source"].startswith("https://"), "SOURCE_URL", "source must be an HTTPS URL", path)
    guard.require(Path(config["archive"]).name in fields["Archive"], "ARCHIVE_MISMATCH", "listing archive differs from config", path)
    guard.require(Path(config["thumbnail"]).name in fields["Thumbnail"], "THUMBNAIL_MISMATCH", "listing thumbnail differs from config", path)
    if config.get("version"):
        guard.require(fields["Version"] == config["version"], "VERSION_MISMATCH", "listing version differs from config", path)
    guard.require(len(fields["Summary"]) >= 20, "SUMMARY_THIN", "summary is too short to explain the asset", path)

    tags = [tag.strip() for tag in fields["Tags"].split(",") if tag.strip()]
    guard.require(1 <= len(tags) <= 10, "TAG_COUNT", "use between 1 and 10 tags", path)
    folded_tags = {tag.casefold() for tag in tags}
    guard.require(config["name"].casefold() not in folded_tags, "TAG_IS_NAME", "asset name cannot also be a tag", path)
    for tag in folded_tags:
        if tag.endswith("s") and tag[:-1] in folded_tags:
            guard.error("TAG_SINGULAR_PLURAL", f"both singular and plural tags are present: {tag[:-1]} / {tag}", path)

    description = markdown_section(markdown, "Detailed description")
    guard.require(len(description) >= 200, "DESCRIPTION_THIN", "detailed description needs at least 200 characters", path)
    guard.require(len(re.findall(r"[.!?](?:\s|$)", description)) >= 3, "DESCRIPTION_SENTENCES", "detailed description needs complete English sentences", path)
    guard.require(not re.fullmatch(r"\s*https?://\S+\s*", description), "DESCRIPTION_URL_ONLY", "description cannot be only a URL", path)

    disclosure_section = markdown_section(markdown, "AI usage disclosure")
    disclosure_match = re.search(r"(?m)^>\s*(.+)$", disclosure_section)
    disclosure = normalize(disclosure_match.group(1)) if disclosure_match else ""
    if config.get("uses_ai", False):
        guard.require(bool(disclosure), "AI_DISCLOSURE_MISSING", "dedicated AI disclosure is required", path)
        guard.require(len(disclosure) <= 256, "AI_DISCLOSURE_LONG", "AI disclosure exceeds 256 characters", path)
        guard.require("ai" in disclosure.casefold() or "artificial intelligence" in disclosure.casefold(), "AI_DISCLOSURE_UNCLEAR", "AI disclosure must identify AI use", path)
        guard.require(disclosure.casefold() not in description.casefold(), "AI_DISCLOSURE_DUPLICATE", "keep AI disclosure out of the detailed description; use the dedicated field", path)
        guard.require("ai usage disclosure" not in description.casefold(), "AI_DISCLOSURE_DUPLICATE_LABEL", "detailed description contains a second AI disclosure label", path)
    elif disclosure:
        guard.warning("AI_DISCLOSURE_UNEXPECTED", "config says AI was not used but the listing contains a disclosure", path)


def check_thumbnail(guard: Guard, base: Path, config: dict) -> None:
    path = resolve(base, config["thumbnail"])
    if not path.is_file():
        guard.error("THUMBNAIL_MISSING", "thumbnail does not exist", path)
        return
    try:
        width, height = image_dimensions(path)
    except ValueError as exc:
        guard.error("THUMBNAIL_FORMAT", str(exc), path)
        return
    guard.require(width * 9 == height * 16, "THUMBNAIL_RATIO", f"thumbnail must be 16:9, got {width}x{height}", path)
    minimum = config.get("minimum_thumbnail", [1280, 720])
    guard.require(width >= minimum[0] and height >= minimum[1], "THUMBNAIL_SMALL", f"thumbnail is below {minimum[0]}x{minimum[1]}: {width}x{height}", path)
    maximum_bytes = int(config.get("thumbnail_max_bytes", 5_000_000))
    guard.require(path.stat().st_size <= maximum_bytes, "THUMBNAIL_LARGE", f"thumbnail exceeds configured {maximum_bytes} bytes", path)

    source_value = config.get("thumbnail_source")
    if not source_value:
        guard.warning("THUMBNAIL_SOURCE_MISSING", "add an SVG source to verify catalog-size text automatically", path)
        return
    source = resolve(base, source_value)
    if not source.is_file():
        guard.error("THUMBNAIL_SOURCE_MISSING", "thumbnail SVG source does not exist", source)
        return
    try:
        root = ElementTree.parse(source).getroot()
    except ElementTree.ParseError as exc:
        guard.error("THUMBNAIL_SVG_INVALID", f"invalid SVG: {exc}", source)
        return
    svg_width = number(str(root.attrib.get("width", "0")))
    svg_height = number(str(root.attrib.get("height", "0")))
    if not svg_width or not svg_height:
        view_box = [number(part) for part in str(root.attrib.get("viewBox", "")).replace(",", " ").split()]
        if len(view_box) == 4:
            svg_width, svg_height = view_box[2], view_box[3]
    guard.require(svg_width > 0 and svg_height > 0 and svg_width * 9 == svg_height * 16, "THUMBNAIL_SVG_RATIO", "thumbnail SVG must define a 16:9 canvas", source)
    guard.require(normalize(root.attrib.get("aria-label", "")).casefold() == config["name"].casefold(), "THUMBNAIL_ARIA", "thumbnail SVG aria-label must equal the asset name", source)
    text_nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "text"]
    text = normalize(" ".join("".join(node.itertext()) for node in text_nodes))
    max_text = int(config.get("thumbnail_max_text_elements", 2))
    guard.require(0 < len(text_nodes) <= max_text, "THUMBNAIL_TEXT_COUNT", f"thumbnail must use 1-{max_text} text elements", source)
    guard.require(text.casefold() == config["name"].casefold(), "THUMBNAIL_TEXT", "thumbnail text must contain only the asset name", source)
    catalog_width = float(config.get("catalog_width", 320))
    minimum_px = float(config.get("minimum_catalog_font_px", 20))
    if svg_width:
        sizes = [number(str(node.attrib.get("font-size", "0"))) * catalog_width / svg_width for node in text_nodes]
        guard.require(bool(sizes) and min(sizes) >= minimum_px, "THUMBNAIL_TEXT_SMALL", f"thumbnail text must remain at least {minimum_px:g}px at {catalog_width:g}px catalog width", source)
        for node in text_nodes:
            size = number(str(node.attrib.get("font-size", "0")))
            x = number(str(node.attrib.get("x", "0")))
            line = normalize("".join(node.itertext()))
            # A conservative dependency-free width estimate. Human visual review
            # is still required because exact glyph metrics depend on the font.
            estimated_width = len(line) * size * 0.68
            anchor = str(node.attrib.get("text-anchor", "start"))
            if anchor == "middle":
                fits = x - estimated_width / 2 >= 24 and x + estimated_width / 2 <= svg_width - 24
            elif anchor == "end":
                fits = x - estimated_width >= 24
            else:
                fits = x + estimated_width <= svg_width - 24
            guard.require(fits, "THUMBNAIL_TEXT_OVERFLOW", f"thumbnail text may leave the canvas: {line}", source)


def zip_is_symlink(info) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def check_plugin_config(guard: Guard, archive: ZipFile, name: str, prefix: str) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(archive.read(name).decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as exc:
        guard.error("PLUGIN_CFG_INVALID", f"plugin.cfg cannot be parsed: {exc}", name)
        return
    if not parser.has_section("plugin"):
        guard.error("PLUGIN_CFG_SECTION", "plugin.cfg lacks [plugin]", name)
        return
    for field in ("name", "description", "author", "version", "script"):
        value = parser.get("plugin", field, fallback="").strip().strip('"\'')
        guard.require(bool(value), "PLUGIN_CFG_FIELD", f"plugin.cfg is missing {field}", name)
    script = parser.get("plugin", "script", fallback="").strip().strip('"\'')
    if script:
        if script.startswith("res://"):
            script_name = script.removeprefix("res://")
        else:
            script_name = prefix + script.lstrip("/")
        guard.require(script_name in archive.namelist(), "PLUGIN_SCRIPT_MISSING", f"plugin.cfg references missing script: {script_name}", name)


def check_archive(guard: Guard, base: Path, config: dict) -> None:
    path = resolve(base, config["archive"])
    if not path.is_file():
        guard.error("ARCHIVE_MISSING", "archive does not exist", path)
        return
    guard.require(path.stat().st_size <= 1_000_000_000, "ARCHIVE_LARGE", "archive exceeds the 1 GB store limit", path)
    prefix = f"addons/{config['addon_directory'].strip('/')}/"
    try:
        archive = ZipFile(path)
    except BadZipFile:
        guard.error("ARCHIVE_INVALID", "archive is not a readable ZIP", path)
        return
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            parts = pure.parts
            guard.require(not name.startswith("/") and ".." not in parts, "ARCHIVE_PATH_UNSAFE", f"unsafe ZIP path: {name}", path)
            guard.require(name.startswith(prefix), "ARCHIVE_OUTSIDE_ADDON", f"file is outside {prefix}: {name}", path)
            guard.require(not zip_is_symlink(info), "ARCHIVE_SYMLINK", f"symlink is not allowed in the upload ZIP: {name}", path)
            if set(parts) & FORBIDDEN_PARTS:
                guard.warning("ARCHIVE_METADATA", f"remove repository or OS metadata: {name}", path)
            if any(PurePosixPath(part).suffix.casefold() in REJECTED_SUFFIXES for part in parts):
                guard.error("ARCHIVE_REJECTED_TYPE", f"store guidelines reject this package type: {name}", path)

        required = {prefix + "LICENSE", prefix + "README.md", prefix + "plugin.cfg"}
        for missing in sorted(required - set(names)):
            guard.error("ARCHIVE_REQUIRED_FILE", f"required add-on file is missing: {missing}", path)
        implementation = [name for name in names if PurePosixPath(name).suffix.casefold() in IMPLEMENTATION_SUFFIXES and name != prefix + "plugin.cfg"]
        guard.require(bool(implementation), "ARCHIVE_EMPTY_ASSET", "archive contains no implementation or asset files", path)

        license_name = prefix + "LICENSE"
        if license_name in names:
            license_text = archive.read(license_name).decode("utf-8", errors="replace")
            expected_license = config.get("license", "MIT")
            if expected_license.casefold() == "mit":
                guard.require("MIT License" in license_text, "LICENSE_TEXT", "archive license does not contain the MIT text", license_name)
            guard.require(bool(re.search(r"Copyright\s+\(c\)\s+20\d{2}\s+\S+", license_text, re.I)), "LICENSE_HOLDER", "license needs a year and copyright holder", license_name)

        plugin_name = prefix + "plugin.cfg"
        if plugin_name in names:
            check_plugin_config(guard, archive, plugin_name, prefix)

        for name in names:
            if name.endswith(".gdextension"):
                text = archive.read(name).decode("utf-8", errors="replace")
                for target in re.findall(r"res://([^\"']+)", text):
                    guard.require(target in names, "GDEXTENSION_LIBRARY_MISSING", f".gdextension references missing file: {target}", name)


def check_repository(guard: Guard, base: Path) -> None:
    if not (base / ".gitignore").is_file():
        guard.warning("REPOSITORY_GITIGNORE", "repository has no .gitignore", base)


def run(config_path: Path) -> tuple[dict, list[Finding]]:
    base, config = read_config(config_path.resolve())
    guard = Guard()
    check_repository(guard, base)
    check_listing(guard, base, config)
    check_thumbnail(guard, base, config)
    check_archive(guard, base, config)
    errors = sum(item.level == "error" for item in guard.findings)
    warnings = sum(item.level == "warning" for item in guard.findings)
    report = {
        "tool": "godot-asset-submission-check",
        "version": VERSION,
        "asset": config["name"],
        "config": str(config_path.resolve()),
        "errors": errors,
        "warnings": warnings,
        "passed": errors == 0,
    }
    return report, guard.findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("asset-guard.json"))
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--strict", action="store_true", help="make warnings fail the command")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    try:
        report, findings = run(args.config)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"passed": False, "errors": 1, "warnings": 0, "fatal": str(exc)}, indent=2))
        else:
            print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    if args.json:
        payload = dict(report)
        payload["findings"] = [asdict(item) for item in findings]
        print(json.dumps(payload, indent=2))
    else:
        for item in findings:
            location = f" [{item.path}]" if item.path else ""
            print(f"{item.level.upper():7} {item.code}: {item.message}{location}")
        status = "PASS" if report["passed"] else "FAIL"
        print(f"{status}: {report['asset']} — {report['errors']} error(s), {report['warnings']} warning(s)")
    return 1 if report["errors"] or (args.strict and report["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
