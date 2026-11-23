"""Build the provisional inspection page used for the reviewer browser pass.

This page is not the validated review bundle. It exists so the reviewer can
actually play every native stream of the re-render before the official bundle
is assembled.
"""
import html
import json
import shutil
import sys
from pathlib import Path

BATCH = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
BRANCH = "counterfactual_creep_reversal"
HEAD = "63347efe67b880f81742980913c5229a421df3eb"

manifest = json.loads((BATCH / "case-manifest.json").read_text())
OUT.mkdir(parents=True, exist_ok=True)
cards = []
for entry in sorted(manifest["cases"], key=lambda c: c["case_id"]):
    cid = entry["case_id"]
    meta = json.loads((BATCH / cid / "metadata.json").read_text())
    media_dir = OUT / "media" / cid
    media_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "true": "true/video.mp4",
        "cf": BRANCH + "/video.mp4",
        "mask": BRANCH + "/mask.mp4",
        "overlay": BRANCH + "/mask_overlay.mp4",
    }
    sources = {}
    for role, rel in files.items():
        target = media_dir / (role + ".mp4")
        shutil.copyfile(BATCH / cid / rel, target)
        sources[role] = "media/%s/%s.mp4" % (cid, role)
    prompts = {
        "true": (BATCH / cid / "true" / "prompt.txt").read_text().strip(),
        "cf": (BATCH / cid / BRANCH / "prompt.txt").read_text().strip(),
    }
    params = meta["scene_params"]
    motion = meta["visible_motion"]
    cards.append("""
<article class="case" data-case-id="%(cid)s">
  <h2>%(cid)s</h2>
  <p class="facts">L %(L).0f mm · section %(A).3g mm&sup2; · payload %(m).3f g · intervention frame %(i)d · first changed frame %(fc)d · evidence frame %(ef)d · True creep %(tc).2f mm · CF lift %(cf).2f mm</p>
  <div class="grid">
    <figure><figcaption>True</figcaption><video controls muted playsinline preload="auto" src="%(true)s"></video></figure>
    <figure><figcaption>Counterfactual</figcaption><video controls muted playsinline preload="auto" src="%(cf)s"></video></figure>
    <figure><figcaption>Binary mask (0/255)</figcaption><video controls muted playsinline preload="auto" src="%(mask)s"></video></figure>
    <figure><figcaption>Red mask overlay #FF0000</figcaption><video controls muted playsinline preload="auto" src="%(overlay)s"></video></figure>
  </div>
  <details><summary>Standalone prompts</summary><h3>True</h3><p>%(pt)s</p><h3>Counterfactual</h3><p>%(pc)s</p></details>
</article>""" % {
        "cid": html.escape(cid),
        "L": params["L"] * 1000,
        "A": params["A"] * 1e6,
        "m": params["payload_mass"] * 1000,
        "i": meta["intervention_frame"],
        "fc": meta["first_changed_frame"],
        "ef": meta["evidence_frame"],
        "tc": abs(motion["true"]["displacement_from_intervention_m"]) * 1000,
        "cf": abs(motion["counterfactual"]["displacement_from_intervention_m"]) * 1000,
        "true": sources["true"], "cf": sources["cf"], "mask": sources["mask"], "overlay": sources["overlay"],
        "pt": html.escape(prompts["true"]), "pc": html.escape(prompts["cf"]),
    })

page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PR #743 re-render inspection page</title>
<style>
body{font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;background:#0b121c;color:#e7eef7;margin:0;padding:28px}
main{max-width:1700px;margin:0 auto}
h1{font-size:34px;margin:0 0 10px}
.notice{background:#3a2410;border:1px solid #b06a1c;border-left:4px solid #e08b2a;padding:12px 16px;border-radius:8px;margin:14px 0 26px}
.case{border:1px solid #22374d;border-radius:12px;padding:18px;margin:0 0 26px;background:#101a26}
.facts{color:#9fb4cc;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:1100px){.grid{grid-template-columns:repeat(2,1fr)}}
figure{margin:0;background:#060c14;border:1px solid #22374d;border-radius:8px;overflow:hidden}
figcaption{padding:8px 10px;font-size:14px}
video{width:100%%;display:block;aspect-ratio:1;background:#000}
details{margin-top:14px}
p{white-space:pre-wrap}
code{background:#0b121c;padding:2px 6px;border-radius:5px}
</style></head>
<body><main>
<h1>PR #743 · loaded_viscoelastic_strip_creep_reversal</h1>
<p>Re-render inspection page for the exact reviewed head <code>%(head)s</code>.</p>
<div class="notice"><strong>Provisional page, not the validated bundle.</strong> The original shared review host was
reclaimed by the platform and its media were lost, so the three Development cases were re-rendered from the
unchanged reviewed commit in a fresh runner. This page exists so every native stream can be played and inspected
before the official bundle is assembled. No automatic verdict, human acceptance or Gate B/C approval is claimed here.</div>
%(cards)s
</main></body></html>
""" % {"head": HEAD, "cards": "\n".join(cards)}
(OUT / "index.html").write_text(page, encoding="utf-8")
print(json.dumps({"output": str(OUT / "index.html"), "cases": len(cards)}))
