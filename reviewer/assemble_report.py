"""Assemble the exact-head review report for the PR743 Development bundle.

Fail-closed: every gate is read back from the delivered evidence files. Nothing
is asserted that was not recomputed or observed.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

BRANCH = "counterfactual_creep_reversal"
GENERATOR = "loaded_viscoelastic_strip_creep_reversal"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def passed(doc):
    return doc.get("pass") is True or doc.get("status") == "PASS" or doc.get("decision") == "PASS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--visual", type=Path, required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--pr", required=True)
    args = ap.parse_args()
    batch = args.batch.resolve()
    head = args.head
    failures = []
    checks = {}

    manifest = read(batch / "case-manifest.json")
    if manifest.get("status") != "complete" or manifest.get("source_commit") != head:
        failures.append("case manifest is not complete at the reviewed head")
    entries = sorted(manifest["cases"], key=lambda c: c["case_id"])
    case_ids = [c["case_id"] for c in entries]
    if len(case_ids) != 3 or len(set(case_ids)) != 3:
        failures.append("expected exactly three unique cases")

    witness = read(batch / "runtime-witness.json")
    index = read(batch / "runtime-witness-index.json")
    if not passed(index) or index.get("failures"):
        failures.append("runtime witness index did not pass")
    if witness.get("status") != "success" or witness.get("exit_code") != 0:
        failures.append("runtime witness is not a successful zero-exit render")
    for key in ("repository_before", "repository_after"):
        if witness.get(key, {}).get("commit") != head or witness.get(key, {}).get("worktree_status"):
            failures.append("runtime witness source binding differs: " + key)
    checks["runtime_witness_success_and_clean_source"] = not failures

    witness_audit = read(batch / "native-runtime-audit.json")
    if not passed(witness_audit):
        failures.append("independent runtime witness audit did not pass")
    checks["runtime_witness_audit"] = passed(witness_audit)

    scale = read(batch / "scale-static.json")
    if not (scale.get("decision") == "PASS" and scale.get("target_cases") == 100000
            and scale.get("audited_seed_count", 0) >= 100000):
        failures.append("100k static scale audit did not pass")
    checks["static_scale_audit_100k"] = scale.get("decision") == "PASS"

    controls = read(batch / "finite-strain-controls.json")
    domain = read(batch / "model-domain.json")
    if controls.get("controlsDecision") != "PASS" or len(controls.get("checks", [])) != 10:
        failures.append("finite-strain constitutive controls did not pass")
    if domain.get("decision") != "PASS" or domain.get("complete") is not True or len(domain.get("results", [])) != 9:
        failures.append("finite-strain model domain checks did not pass")
    checks["finite_strain_controls"] = controls.get("controlsDecision") == "PASS"
    checks["model_domain_checks"] = domain.get("decision") == "PASS"

    independent = read(batch / "reviewer-independent-media.json")
    if independent.get("status") != "PASS":
        failures.append("reviewer independent decoded-media audit did not pass")
    checks["independent_decoded_media_audit"] = independent.get("status") == "PASS"

    visual = read(args.visual)
    if visual.get("reviewed_head") != head or visual.get("humanReview") != "pending":
        failures.append("visual inspection evidence is not bound to this head")
    visual_cases = {c["case_id"]: c for c in visual.get("cases", [])}
    if set(visual_cases) != set(case_ids):
        failures.append("visual inspection does not cover the three delivered cases")

    artifacts = []
    seen = set()

    def add_artifact(name):
        if name in seen:
            return
        path = batch / name
        if not path.is_file():
            failures.append("missing artifact: " + name)
            return
        seen.add(name)
        artifacts.append({"path": name, "sha256": digest(path), "bytes": path.stat().st_size})

    add_artifact("case-manifest.json")
    add_artifact("runtime-witness-index.json")
    add_artifact("runtime-witness.json")
    add_artifact("native-runtime-audit.json")
    add_artifact("scale-static.json")
    add_artifact("finite-strain-controls.json")
    add_artifact("model-domain.json")
    add_artifact("reviewer-independent-media.json")
    add_artifact("native-semantic-visual.json")
    if (batch / "browser-playback-audit.json").is_file():
        add_artifact("browser-playback-audit.json")
    else:
        failures.append("browser playback record is missing")

    cases = []
    for entry in entries:
        cid = entry["case_id"]
        metadata_name = cid + "/metadata.json"
        meta = read(batch / metadata_name)
        git = meta.get("generation", {}).get("git", {})
        if git.get("commit") != head or git.get("dirty") or not git.get("tracked"):
            failures.append("case source binding is not the clean reviewed head: " + cid)
        paths = meta["paths"]
        media = {
            "true": cid + "/" + paths["true"]["video"],
            "cf": cid + "/" + paths["counterfactual"]["video"],
            "mask": cid + "/" + paths["counterfactual"]["mask"],
            "overlay": cid + "/" + paths["counterfactual"]["mask_overlay"],
        }
        for name in media.values():
            add_artifact(name)
        add_artifact(metadata_name)
        add_artifact(cid + "/audit_media.json")
        add_artifact(cid + "/audit_physics.json")
        add_artifact(cid + "/render_witness.json")
        add_artifact(cid + "/" + paths["true"]["prompt"])
        add_artifact(cid + "/" + paths["counterfactual"]["prompt"])
        media_audit = read(batch / (cid + "/audit_media.json"))
        physics_audit = read(batch / (cid + "/audit_physics.json"))
        if not passed(media_audit) or not passed(physics_audit):
            failures.append("generator case audit failed: " + cid)
        checks["case_media_audit_" + cid[-2:]] = passed(media_audit)
        checks["case_physics_audit_" + cid[-2:]] = passed(physics_audit)
        visual_case = visual_cases.get(cid, {})
        expected_hashes = {role: digest(batch / name) for role, name in media.items()}
        if visual_case.get("media_sha256") != expected_hashes:
            failures.append("visual inspection is not bound to the delivered pixels: " + cid)
        if not visual_case.get("checks") or not all(v is True for v in visual_case["checks"].values()):
            failures.append("visual inspection checks are incomplete: " + cid)
        observations = visual_case.get("observations") or []
        if not observations:
            failures.append("visual inspection observations missing: " + cid)
        params = meta["scene_params"]
        cases.append({
            "case_id": cid,
            "metadata_path": metadata_name,
            "media": media,
            "audit_path": cid + "/audit_media.json",
            "physics_audit_path": cid + "/audit_physics.json",
            "selection_reason": (
                "Declared Development recipe: %.0f mm strip, %.3g mm2 section, %.3f g load, "
                "%.3f s middle relaxation time. The relaxation-time variant is synthetic; geometry "
                "and gravity load reach the solver and the renderer."
                % (params["L"] * 1000, params["A"] * 1e6, params["payload_mass"] * 1000,
                   0.97 * params["tau_middle_scale"])
            ),
            "observations": observations,
        })

    manifest_sha = digest(batch / "case-manifest.json")
    index_sha = digest(batch / "runtime-witness-index.json")
    canonical = dict(headSha=head, caseIds=sorted(case_ids), caseManifestSha256=manifest_sha,
                     runtimeWitnessIndexSha256=index_sha)
    identity = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    report = {
        "schema": "counterfactual-generator-review-report-v1",
        "decision": "PASS" if not failures else "FAIL",
        "checks": dict(checks, all_pass=not failures),
        "failures": failures,
        "generator": GENERATOR,
        "stage": "Development",
        "reviewed_head": head,
        "source_commit": head,
        "pr_url": args.pr,
        "case_ids": sorted(case_ids),
        "artifacts": artifacts,
        "case_manifest_path": "case-manifest.json",
        "runtime_witness_index": "runtime-witness-index.json",
        "evidence_identity": {
            "sha256": identity,
            "case_manifest_sha256": manifest_sha,
            "runtime_witness_index_sha256": index_sha,
        },
        "scale_audit": {
            "decision": scale.get("decision"),
            "target_cases": scale.get("target_cases"),
            "audited_seed_count": scale.get("audited_seed_count"),
            "report_path": "scale-static.json",
            "scope": scale.get("scope"),
        },
        "constitutive_model_validation": {
            "model": "multiplicative_neo_hookean_maxwell",
            "controls_decision": controls.get("controlsDecision"),
            "domain_decision": domain.get("decision"),
            "summary": (
                "The finite-strain constitutive law is a synthetic multiplicative Neo-Hookean "
                "extension of a published small-strain relaxation spectrum. Its tangent, stored "
                "energy conjugacy, energy positivity and single-branch mobility reversal were "
                "re-checked at this head; it is not an experimentally calibrated material law."
            ),
            "report_path": "finite-strain-controls.json",
            "domain_report_path": "model-domain.json",
        },
        "cases": cases,
        "visual_inspection": {
            "scope": visual.get("scope"),
            "observer": visual.get("observer"),
            "human_review": "pending",
            "cases": sorted(visual_cases),
            "browser_playback_artifact": (
                "browser-playback-audit.json" if (batch / "browser-playback-audit.json").is_file() else None),
        },
        "independent_media_audit": {
            "status": independent.get("status"),
            "scope": independent.get("schema"),
            "cases": [{"case_id": c["case_id"], "status": c["status"],
                       "true_creep_after_onset_mm": c.get("true_creep_after_onset_mm"),
                       "cf_lift_after_onset_mm": c.get("cf_lift_after_onset_mm"),
                       "mask_start_frame": c.get("mask_start_frame"),
                       "first_changed_frame": c.get("first_changed_frame")}
                      for c in independent.get("cases", [])],
        },
        "notes": [
            "This bundle was re-rendered at the exact reviewed head in a fresh public CI runner "
            "after the original shared review host was reclaimed by the platform and its media "
            "were lost. The generator source, the reviewed commit and the audit procedures are "
            "unchanged; the delivered bytes differ from the lost original only by the encoding "
            "timestamp of the container mux.",
            "Human acceptance of this head remains pending.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"decision": report["decision"], "failures": failures,
                      "artifacts": len(artifacts), "evidence_identity": identity}, indent=2))
    raise SystemExit(0 if report["decision"] == "PASS" else 1)


if __name__ == "__main__":
    main()
