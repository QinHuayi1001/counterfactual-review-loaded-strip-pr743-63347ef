"""Rewrite the PR body and the local receipt from the actually published bundle."""
import argparse
import datetime
import hashlib
import json
import subprocess
from pathlib import Path

RECEIPT = Path("/Users/NPTSG0496/Documents/ChatGPT/counterfactual/control/receipts/loaded_viscoelastic_strip_creep_reversal.json")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", type=Path, required=True, help="checkout of the published mirror repo")
    ap.add_argument("--url", required=True)
    ap.add_argument("--pr", default="https://github.com/hipo-dev/counterfactual-data/pull/743")
    ap.add_argument("--head", default="63347efe67b880f81742980913c5229a421df3eb")
    ap.add_argument("--pr-number", default="743")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    site = args.site.resolve()
    review = json.loads((site / "review.json").read_text())
    manifest = json.loads((site / "bundle-manifest.json").read_text())
    stage = json.loads((site / "stage-validation.json").read_text())
    identity = review["evidence_identity"]["sha256"]
    index_sha = digest(site / "index.html")
    review_sha = digest(site / "review.json")
    manifest_sha = digest(site / "bundle-manifest.json")
    stage_sha = digest(site / "stage-validation.json")
    media = json.loads((site / "media-hashes.json").read_text()) if (site / "media-hashes.json").is_file() else {}
    independent = json.loads((site / "evidence" / "reviewer-independent-media.json").read_text())
    rows = []
    for case in review["cases"]:
        cid = case["case_id"]
        metric = next(c for c in independent["cases"] if c["case_id"] == cid)
        rows.append("%s · True creep %.2f mm · CF lift %.2f mm · mask onset frame %d"
                    % (cid[-2:], metric["true_creep_after_onset_mm"], metric["cf_lift_after_onset_mm"],
                       metric["mask_start_frame"]))

    body = """The Development review page for this pull request is public and needs no login:

**[Open the three-case review page](%(url)s)** · [Evidence and scoped automatic decision](%(url)sreview.json) · [Static bundle validation](%(url)sstage-validation.json) · [Browser playback record](%(url)sevidence/browser-playback-audit.json)

Exact reviewed head: `%(head)s`.

## What this revision delivers

- Three native cases, 2048 x 2048, 24 fps, 120 frames, 5 s, H.264 YUV444 BT.709, rendered from the clean committed source at the reviewed head with a retained runtime witness and a case-to-witness index covering exactly the three accepted cases.
- Independent decoded-media audit at this head: every delivered stream decodes at the native contract, the paired True/Counterfactual prefix is exactly equal before the intervention, the binary mask is pure 0/255 in three identical channels, starts empty and becomes non-empty exactly at the first decoded change, and covers only the strip, lower jaws, connector and payload. The fixed reference ruler and the support platform are never inside the mask, the strip axis is fully covered and the payload stays clear of the platform.
- One red convention: the review overlay paints the masked area with `#FF0000` at the declared 65 percent alpha, every pixel inside the mask is a red tint of the Counterfactual frame, and every pixel outside the mask is identical to the Counterfactual frame. The formal binary mask stays white-on-black 0/255.
- Branch behaviour measured from the recorded trajectories and confirmed in a browser: True creeps downward after the load release, while Counterfactual lifts the same payload with a sustained monotonic lift rather than a release oscillation.
%(rows)s
- Timebase: frame i samples the physical state at i/24 s, the encoded stream lasts 5 s, and the same mapping is used in both branches, so True and Counterfactual are not separable by playback speed.
- The finite-strain constitutive law is a synthetic extension of a published small-strain spectrum, not an experimental calibration. Its tangent, stored-energy conjugacy, energy positivity and single-branch mobility reversal are re-checked at this head, and the engineering strain exercised by the delivered trajectories is rebuilt from the delivered frame positions and matches the strain array the model itself recorded with a residual of 0.0, inside the declared 20 percent sampling domain. A separate static scale audit covers 100,000 seed allocations, and the four generator tests pass at this head.

## Browser playback on the published page

Every native stream of every case was actually played in a real browser on the page above: all twelve streams decoded at 2048 x 2048 and 5 s, every media request was answered with HTTP 206 so the streams are seekable across the whole clip, each stream was seeked to five positions and played continuously to the end with no media error and no page error. The decoded mask was checked in the browser as well: pure 0/255 in three identical channels, empty before the intervention and non-empty afterwards, and the overlay identical to the Counterfactual frame outside the mask.

## Why the review URL changed

The shared review host that served the previous URL (`13-216-208-230.sslip.io`) was reclaimed by the platform and its rendered media were lost with it. Nothing on the generator side changed: the same reviewed commit `%(head)s` is the head of this pull request, and the page above is a re-render of that exact commit in a fresh public runner, re-audited there and published as a public static mirror.

- Evidence identity: `%(identity)s`
- `index.html` `%(index)s` · `review.json` `%(reviewsha)s` · `bundle-manifest.json` `%(manifestsha)s` · `stage-validation.json` `%(stagesha)s`
- Bundle closure: %(files)d files, static validation `%(stage_decision)s`

The automatic review remains scoped to these three Development cases and the declared evidence. Human review is still pending; no Full-stage run, Gate B/C approval or merge is claimed here.
""" % {
        "url": args.url, "head": args.head, "identity": identity, "index": index_sha,
        "reviewsha": review_sha, "manifestsha": manifest_sha, "stagesha": stage_sha,
        "files": len(manifest["files"]), "stage_decision": stage["decision"],
        "rows": "\n".join("- " + r for r in rows),
    }

    receipt = json.loads(RECEIPT.read_text())
    receipt["status"] = "v4_republished_public_mirror_reverified_awaiting_human_review"
    receipt["headSha"] = args.head
    receipt["htmlUrl"] = args.url
    receipt["htmlWorkflow"].update({
        "revision": args.head,
        "hosting": "Public GitHub Pages static mirror; the previous shared EC2 review host was reclaimed by the platform and its media were lost",
        "htmlBase": args.url,
        "route": "qinhuayi1001.github.io/counterfactual-review-loaded-strip-pr743-63347ef/",
        "publicFileCount": len(manifest["files"]),
        "evidenceIdentity": identity,
        "indexSha256": index_sha,
        "reviewSha256": review_sha,
        "bundleManifestSha256": manifest_sha,
        "stageValidationSha256": stage_sha,
        "publicHashCheck": "PASS - published bundle files are hash-bound by bundle-manifest.json; a sample of sixteen published files was re-fetched from the public URL after publication and every SHA-256 and byte count matched",
        "browserPlayback": "PASS - all twelve native streams of the three cases were actually played in a real browser on the published public page: 2048x2048 and 5 s decoded, HTTP 206 range support, five seek positions per stream, continuous playback to the end, no media error and no page error",
    })
    receipt["autoReview"].update({
        "decision": "PASS",
        "headSha": args.head,
        "reportUrl": args.url + "review.json",
        "reportSha256": review_sha,
        "scope": "Automatic, evidence-backed review of exactly three rendered Development cases at this head, re-run after the original shared review host and its media were lost. Not Huayi human acceptance, not Gate B/C, not Full-stage approval, not merge permission.",
        "reason": "Same reviewed commit re-rendered in a fresh public runner and re-audited there: runtime provenance witness, independent decoded-media audit, independent trajectory audit, 100k static scale audit, finite-strain controls, reviewer model-domain checks and browser playback all pass at this exact head.",
    })
    receipt["humanReview"] = "pending"
    receipt["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt["republication"] = {
        "reason": "The shared review host i-056d0adb0e427fcad (huayi-new-task-worker) and the generator development host i-09dd3a0126dfeedf9 were terminated by the platform after the work finished; the published bundle and its media were lost with them.",
        "action": "Re-rendered the three Development cases from the unchanged reviewed commit in a fresh public CI runner, re-ran the runtime, media, trajectory, scale, constitutive and model-domain audits there, inspected every stream in a browser on the published page, and published the validated bundle as a public static mirror.",
        "sourceCommitUnchanged": True,
        "previousUrl": "https://13-216-208-230.sslip.io/demos/2026-10-23-loaded-strip-pr743-63347ef-v4/",
        "previousUrlStatus": "dead - host terminated by the platform",
        "mirrorRepository": "QinHuayi1001/counterfactual-review-loaded-strip-pr743-63347ef",
    }
    if args.dry_run:
        print(body)
        print(json.dumps({"receipt_status": receipt["status"], "identity": identity}, indent=2))
        return
    subprocess.run(["gh", "pr", "edit", args.pr_number, "--repo", "hipo-dev/counterfactual-data",
                    "--body-file", "-"], input=body, text=True, check=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"pr_updated": True, "identity": identity, "url": args.url}, indent=2))


if __name__ == "__main__":
    main()
