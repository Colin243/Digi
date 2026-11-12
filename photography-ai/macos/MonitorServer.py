"""Launch only the read-only monitor; never load a model or start training."""
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text())
sys.path.insert(0, str(Path(config["sourceRoot"]) / "src"))
from photo_ai.training.monitor.server import serve

serve(host="127.0.0.1", port=config["port"], roots=[Path(p) for p in config["dataRoots"]])
