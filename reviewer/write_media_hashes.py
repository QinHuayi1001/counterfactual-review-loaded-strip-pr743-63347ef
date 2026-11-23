"""Publish the SHA-256 of every delivered media file so the visual pass can bind to it."""
import hashlib
import json
import os
import sys
from pathlib import Path

batch = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
branch = "counterfactual_creep_reversal"
manifest = json.loads((batch / "case-manifest.json").read_text())
out = {}
for entry in manifest["cases"]:
    cid = entry["case_id"]
    files = {"true": "true/video.mp4", "cf": branch + "/video.mp4",
             "mask": branch + "/mask.mp4", "overlay": branch + "/mask_overlay.mp4"}
    out[cid] = {role: hashlib.sha256((batch / cid / rel).read_bytes()).hexdigest()
                for role, rel in files.items()}
out_path.write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
