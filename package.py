#!/usr/bin/env python3
"""Build the deterministic free release archive."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "dist" / "godot-asset-submission-check-0.1.0.zip"
TIMESTAMP = (2026, 10, 16, 0, 0, 0)
FILES = [
    Path("asset_guard.py"),
    Path("README.md"),
    Path("LICENSE"),
    Path("sample/asset-guard.json"),
    Path("sample/ASSET_STORE_SUBMISSION.md"),
]


def main() -> None:
    TARGET.parent.mkdir(exist_ok=True)
    with ZipFile(TARGET, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in FILES:
            info = ZipInfo((Path("godot-asset-submission-check") / path).as_posix(), TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (ROOT / path).read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    print(f"{TARGET} ({TARGET.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
