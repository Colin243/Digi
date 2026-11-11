#!/usr/bin/env python3
"""Build a configured local developer app using only Xcode and Python stdlib."""
import argparse
import json
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True, type=Path, help="Explicit destination ending in .app")
parser.add_argument("--source-root", type=Path, default=HERE.parent)
parser.add_argument("--python", required=True, type=Path, help="Existing photography-ai Python environment")
parser.add_argument("--data-root", action="append", type=Path, dest="data_roots")
parser.add_argument("--port", type=int, default=7872)
args = parser.parse_args()
output = args.output.expanduser().absolute()
source = args.source_root.expanduser().resolve()
python = args.python.expanduser().absolute()  # Preserve venv executable symlink semantics.
if output.suffix != ".app" or not output.stem.strip():
    parser.error("--output must name an .app bundle")
if not 1024 <= args.port <= 65535:
    parser.error("--port must be between 1024 and 65535")
if not (source / "src/photo_ai/training/monitor/server.py").is_file():
    parser.error("--source-root must be a photography-ai checkout")
if output.exists():
    plist_path = output / "Contents/Info.plist"
    if not plist_path.is_file() or plistlib.loads(plist_path.read_bytes()).get("CFBundleIdentifier") != "local.digi.observatory":
        parser.error("Refusing to overwrite a bundle not built by this script")
macos = output / "Contents/MacOS"
resources = output / "Contents/Resources"
with tempfile.TemporaryDirectory(prefix="digi-swift-cache-") as cache:
    binary = Path(cache) / "DigiObservatory"
    subprocess.run(["xcrun", "swiftc", "-swift-version", "5", "-O", "-target", f"{platform.machine()}-apple-macosx12.0",
                    "-module-cache-path", cache, "-framework", "AppKit", "-framework", "WebKit",
                    str(HERE / "Observatory.swift"), "-o", str(binary)], check=True)
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, macos / "DigiObservatory")
roots = args.data_roots or [source / "data/adapters", source / "data/monitor_runs"]
(resources / "config.json").write_text(json.dumps({"sourceRoot": str(source), "pythonExecutable": str(python),
    "dataRoots": [str(p.expanduser().resolve()) for p in roots], "port": args.port}, indent=2) + "\n")
shutil.copyfile(HERE / "MonitorServer.py", resources / "MonitorServer.py")
(output / "Contents/Info.plist").write_bytes(plistlib.dumps({
    "CFBundleIdentifier": "local.digi.observatory", "CFBundleName": "Digi Observatory",
    "CFBundleDisplayName": "Digi Observatory", "CFBundleExecutable": "DigiObservatory",
    "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1",
    "LSMinimumSystemVersion": "12.0", "NSHighResolutionCapable": True,
    "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
}))
subprocess.run(["codesign", "--force", "--sign", "-", str(output)], check=True)
print(output)
