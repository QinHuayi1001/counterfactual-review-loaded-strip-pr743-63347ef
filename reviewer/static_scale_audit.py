"""Reviewer static scale audit: 100,000 seed allocations checked without rendering.

Uses the generator's own CGC-v1 allocation module so the audited space is the
production space. No rendering, no simulation, no solver import.
"""
import hashlib
import json
import random
import sys
from pathlib import Path

GEN = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
sys.path.insert(0, str(GEN))

from src.scaling import (AXES, PROFILE_SPACE_SIZE, PROFILE_VERSION, SCALING_CONTRACT_VERSION,
                         SCALING_TARGET_CASES, effective_scaling_signature, profile_for_seed,
                         sample_params, validate_params)
from engine.spec import RenderCfg, SceneSpec

TARGET = SCALING_TARGET_CASES
render = RenderCfg()
profile_ids = set()
signatures = set()
buckets = {axis["name"]: set() for axis in AXES}
invalid = []
effective_by_profile = {}
for seed in range(TARGET):
    profile = profile_for_seed(seed)
    profile_ids.add(profile["profile_id"])
    for name, value in profile["axis_buckets"].items():
        buckets[name].add(value)
    rng = random.Random(seed)
    params = sample_params(rng, seed, profile)
    errors = validate_params(params)
    if errors:
        invalid.append({"seed": seed, "errors": errors})
        continue
    true_spec = SceneSpec(task_id="scale", seed=seed, params=params, render=render,
                          branch="true", mobility_signs_after_event=(1.0, 1.0, 1.0))
    cf_spec = SceneSpec(task_id="scale", seed=seed, params=params, render=render,
                        branch="counterfactual", mobility_signs_after_event=(1.0, -1.0, 1.0))
    signature = effective_scaling_signature(true_spec, cf_spec)
    key = json.dumps(signature, sort_keys=True, default=repr)
    signatures.add(hashlib.sha256(key.encode()).hexdigest())

coverage = {}
for axis in AXES:
    coverage[axis["name"]] = {
        "buckets": axis["buckets"],
        "covered": len(buckets[axis["name"]]),
        "fraction": round(len(buckets[axis["name"]]) / axis["buckets"], 6),
    }
report = {
    "schema": "reviewer-static-scale-audit-v1",
    "decision": "PASS" if not invalid and len(profile_ids) == TARGET and len(signatures) == TARGET
                and all(v["fraction"] == 1.0 for v in coverage.values()) else "FAIL",
    "scope": "Static allocation audit only: no case was rendered or simulated here.",
    "contract_version": SCALING_CONTRACT_VERSION,
    "profile_version": PROFILE_VERSION,
    "target_cases": TARGET,
    "audited_seed_count": TARGET,
    "accepted_static": len(signatures),
    "audit_samples": TARGET,
    "distinct_profile_ids": len(profile_ids),
    "distinct_effective_signatures": len(signatures),
    "profile_space_size": PROFILE_SPACE_SIZE,
    "axis_bucket_coverage": {k: v["fraction"] for k, v in coverage.items()},
    "axis_bucket_detail": coverage,
    "invalid_parameter_samples": invalid[:10],
    "invalid_parameter_sample_count": len(invalid),
    "source_files": {
        "src/scaling.py": hashlib.sha256((GEN / "src" / "scaling.py").read_bytes()).hexdigest(),
        "engine/spec.py": hashlib.sha256((GEN / "engine" / "spec.py").read_bytes()).hexdigest(),
    },
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: report[k] for k in ("decision", "target_cases", "audited_seed_count",
                                         "distinct_profile_ids", "distinct_effective_signatures",
                                         "invalid_parameter_sample_count")}, indent=2))
raise SystemExit(0 if report["decision"] == "PASS" else 1)
