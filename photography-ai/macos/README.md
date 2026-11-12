# Digi Observatory for Mac

An AppKit window containing the existing monitor in WKWebView. Requires macOS 12+, Xcode command-line tools, Python 3 for building, and an existing photography-ai Python environment. No Electron, extra packages, model loading, login items, or bundled training environment.

From the repository root:

```sh
python3 photography-ai/macos/build.py \
  --output "$PWD/output/Digi Observatory.app" \
  --source-root "$PWD/photography-ai" \
  --python "$PWD/photography-ai/.venv/bin/python" \
  --data-root "$PWD/photography-ai/data/adapters" \
  --data-root "$PWD/photography-ai/data/monitor_runs"
open "$PWD/output/Digi Observatory.app"
```

Choose any explicit output directory outside tracked source. The generated `Contents/Resources/config.json` stores your local checkout, Python executable, data roots, and port. Keep the generated bundle/config out of commits. `--port` defaults to 7872. Omit `--data-root` to use the checkout's two standard data directories. The script uses argument arrays to preserve spaces in paths, compiles for the current Mac's architecture, and ad-hoc signs the bundle.

See [setup and lifecycle details](../docs/macos-observatory.md).
