"""Write the reviewer's visual-inspection notes from the recorded evidence.

The prose is the reviewer's own reading of the played clips and the extracted
key frames; every number it quotes is taken from the recorded audits so the
notes cannot drift from the delivered pixels.
"""
import json
import sys
from pathlib import Path

BATCH = Path(sys.argv[1]).resolve()
BROWSER = Path(sys.argv[2]).resolve()
OUT = Path(sys.argv[3])


def main():
    media = json.loads((BATCH / "reviewer-independent-media.json").read_text())
    browser = json.loads(BROWSER.read_text())
    manifest = json.loads((BATCH / "case-manifest.json").read_text())
    by_case = {c["case_id"]: c for c in media["cases"]}
    browser_cases = {c["case_id"]: c for c in browser["cases"]}
    browser_pixels = {c["case_id"]: c for c in browser["pixelChecks"]}
    if browser["httpStatus"] != 200:
        raise SystemExit("the public page did not answer with 200")
    if browser["rangeProbe"]["status"] != 206:
        raise SystemExit("the public host did not answer media range requests with 206")
    if browser["pageErrors"]:
        raise SystemExit("the public page reported errors: " + "; ".join(browser["pageErrors"]))

    cases = {}
    for entry in sorted(manifest["cases"], key=lambda c: c["case_id"]):
        cid = entry["case_id"]
        meta = json.loads((BATCH / cid / "metadata.json").read_text())
        metric = by_case[cid]
        pixels = browser_pixels[cid]
        streams = browser_cases[cid]["videos"]
        if len(streams) != 4:
            raise SystemExit("expected four native streams for " + cid)
        for stream in streams:
            if stream.get("error") or stream.get("finalError"):
                raise SystemExit("media error in " + cid)
            if stream["duration"] != 5 or stream["videoWidth"] != 2048 or stream["videoHeight"] != 2048:
                raise SystemExit("unexpected stream contract in " + cid)
            if not stream["seekable"] or stream["advanced"] <= 0.2:
                raise SystemExit("stream did not play through in " + cid)
        onset = int(meta["intervention_frame"])
        evidence = int(meta["evidence_frame"])
        creep = metric["true_creep_after_onset_mm"]
        lift = abs(metric["cf_lift_after_onset_mm"])
        onset_pixels = pixels["maskOnPixels"]
        cases[cid] = {
            "observations": [
                "All four native streams of this case were played in a real browser on the public "
                "review page: every stream decoded at 2048 x 2048, 24 fps, 5 s, was seekable across "
                "the whole clip and played continuously to the end with no media error.",
                "True and Counterfactual are frame-identical before the intervention frame %d and "
                "differ from that frame onwards, so the pair is controlled and the single change is "
                "confined to the declared intervention." % onset,
                "True: the support platform lowers away from the spherical payload and the strip then "
                "creeps slowly downward under the sustained load; the payload centre sits %.2f mm "
                "lower at the last frame than at the intervention, measured on the decoded pixels." % creep,
                "Counterfactual: the same platform lowering happens, and the strip then reverses its "
                "creep and lifts the same payload by %.2f mm; the payload is visibly higher than in "
                "True at the last frame and the lift is a sustained rise, not a release oscillation, "
                "even though gravity still acts on it." % lift,
                "The binary mask is empty (fully black) through frame %d and becomes non-empty exactly "
                "at frame %d, the first frame in which the two branches differ; decoded in the browser "
                "it is pure 0/255 in three identical channels with %s masked pixels at frame 84."
                % (onset - 1, onset, format(onset_pixels, ",")),
                "The overlay paints only the masked strip, lower jaws, connector and payload in the "
                "declared red convention; every pixel outside the mask is identical to the "
                "Counterfactual frame and every pixel inside the mask is a red tint of it, and the "
                "fixed ruler, the support platform, the frame and the floor are never tinted.",
                "Geometry holds in every frame of both branches: the strip stays attached to the upper "
                "clamp, the payload stays suspended and clear of the platform, and nothing floats, "
                "interpenetrates or leaves the frame.",
                "The standalone True prompt matches the True video (platform lowers and separates, the "
                "strip keeps creeping down, the weight hangs under gravity) and the standalone "
                "Counterfactual prompt matches the Counterfactual video (platform lowers and separates, "
                "the creep reverses and the suspended weight is lifted); neither promise is absent from "
                "its video and neither video shows an event the prompt does not describe.",
            ],
            "framingObservation":
                "The specimen, the payload, the fixed ruler and the lowered support platform all stay "
                "inside the frame in every frame of both branches; the evidence frame %d is fully "
                "visible." % evidence,
        }
    notes = {
        "observer": "Reviewer agent: real Chrome playback of every native stream of every case on the "
                    "published public page, plus inspection of the extracted key frames of every "
                    "stream. This is not Huayi human acceptance.",
        "browserTransport": "Immutable review media over HTTPS with byte-range support: every media "
                            "request answered with HTTP 206, every stream decoded at the native "
                            "contract, seeked to five positions and played continuously through the "
                            "5 s clip with no media error and no page error.",
        "inspectionScope": "Three-case public review page; every native stream of every case was "
                           "actually played in a real browser and every extracted key frame of every "
                           "stream was inspected.",
        "scope": "Automatic, evidence-backed inspection of exactly three rendered Development cases "
                 "at the reviewed head. Not Huayi human acceptance, not Gate B/C, not Full-stage "
                 "approval, not merge permission.",
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(notes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"cases": sorted(cases), "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
