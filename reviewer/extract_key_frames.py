"""Extract key frames from every delivered stream as small PNGs for visual inspection."""
import json
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

BATCH = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
BRANCH = "counterfactual_creep_reversal"
SIZE = 512

manifest = json.loads((BATCH / "case-manifest.json").read_text())
index = []
for entry in sorted(manifest["cases"], key=lambda c: c["case_id"]):
    cid = entry["case_id"]
    meta = json.loads((BATCH / cid / "metadata.json").read_text())
    wanted = sorted({0, int(meta["intervention_frame"]) - 1, int(meta["first_changed_frame"]),
                     int(meta["evidence_frame"]), 119})
    files = {"true": "true/video.mp4", "cf": BRANCH + "/video.mp4",
             "mask": BRANCH + "/mask.mp4", "overlay": BRANCH + "/mask_overlay.mp4"}
    target_dir = OUT / cid
    target_dir.mkdir(parents=True, exist_ok=True)
    for role, rel in files.items():
        reader = imageio_ffmpeg.read_frames(str(BATCH / cid / rel), pix_fmt="rgb24",
                                            input_params=["-threads", "1"],
                                            output_params=["-threads", "1"])
        info = next(reader)
        w, h = info["size"]
        for i in range(120):
            raw = next(reader)
            if i in wanted:
                frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
                image = Image.fromarray(frame).resize((SIZE, SIZE), Image.LANCZOS)
                name = "%s-f%03d.png" % (role, i)
                image.save(target_dir / name)
                index.append({"case_id": cid, "role": role, "frame": i, "file": "%s/%s" % (cid, name)})
        reader.close()
(OUT / "key-frames.json").write_text(json.dumps({"frames": index}, indent=2) + "\n")
print(json.dumps({"extracted": len(index), "output": str(OUT)}))
