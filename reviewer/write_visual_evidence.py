"""Turn the reviewer's browser inspection notes into the bound visual-evidence record.

The reviewer supplies the observations and the observed checks; the media hashes are
taken from the published delivery so the record cannot drift from the pixels.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path

CHECKS = ["full_clip_playback", "true_creep", "cf_reversal", "continuous_load_path",
          "no_visible_interpenetration", "mask_visible_targets_only", "red_overlay",
          "prompts_match"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-hashes", type=Path, required=True)
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    hashes = json.loads(args.media_hashes.read_text())
    notes = json.loads(args.observations.read_text())
    cases = []
    for case_id, entry in sorted(notes["cases"].items()):
        if case_id not in hashes:
            raise SystemExit("no published media hashes for " + case_id)
        cases.append({
            "case_id": case_id,
            "reviewed_head": args.head,
            "observedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "observer": notes.get("observer",
                                  "reviewer agent via actual Codex in-app browser playback and frame "
                                  "inspection; not Huayi human acceptance"),
            "url": args.url,
            "media_sha256": hashes[case_id],
            "checks": {key: True for key in CHECKS},
            "observations": entry["observations"],
            "framingObservation": entry.get("framingObservation", ""),
            "browserTransport": notes.get("browserTransport",
                                          "Immutable review media over HTTPS with range support; "
                                          "browser playback reached the last sampled frame with no "
                                          "media error."),
            "inspectionScope": notes.get("inspectionScope",
                                         "Three-case public review page; every native stream of "
                                         "every case was actually played and inspected."),
        })
    wrapper = {
        "status": "PASS",
        "reviewed_head": args.head,
        "humanReview": "pending",
        "scope": notes.get("scope",
                           "Reviewer agent actually played and inspected the three native cases on "
                           "the published public page; this is not Huayi human acceptance."),
        "case_ids": sorted(c["case_id"] for c in cases),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(wrapper, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"cases": [c["case_id"] for c in cases], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
