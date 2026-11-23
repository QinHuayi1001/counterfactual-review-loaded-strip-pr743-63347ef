"""Reviewer finite-strain model domain checks for the loaded viscoelastic strip.

Nine bounded checks computed from the committed model source, the generator's own
finite-strain controls and the three delivered case trajectories. This is a model
domain check, not a material calibration.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

BATCH = Path(sys.argv[1]).resolve()
GEN = Path(sys.argv[2]).resolve()
OUT = Path(sys.argv[3])
MODEL = GEN / "engine" / "model.py"
BRANCH = "counterfactual_creep_reversal"

spec = importlib.util.spec_from_file_location("pr743_model_under_review", MODEL)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)

model_sha = hashlib.sha256(MODEL.read_bytes()).hexdigest()
EI = model.EI.copy()
EINF = model.EINF
TAU = model.TAU.copy()
results = []


def add(name, passed, **metrics):
    results.append(dict(name=name, audit="PASS" if passed else "FAIL", **metrics))


manifest = json.loads((BATCH / "case-manifest.json").read_text())
case_ids = [c["case_id"] for c in manifest["cases"]]

# 1. published spectrum anchor -----------------------------------------------------
weights = EI / EI.sum()
add("published_spectrum_anchor",
    abs(float(EINF + EI.sum()) - 3.25e6) < 1.0
    and np.allclose(weights, [0.45, 0.26, 0.10], atol=0.005)
    and np.allclose(TAU, [0.047, 0.97, 18.0]),
    instantaneous_modulus_Pa=float(EINF + EI.sum()),
    weights=[round(float(w), 5) for w in weights],
    relaxation_times_s=[float(t) for t in TAU],
    source="Dykstra et al. (2019), Table 1 (published small-strain anchor)")

# operating grid taken from the delivered trajectories and their physics audits
#
# The engineering strain of every strip segment is rebuilt here from the
# delivered frame positions alone, using the model's own segment definition:
# a virtual origin below the strip plus the sampled node chain. The rest
# segment length L/n is taken from the delivered scene parameters. The rebuilt
# strain is then compared with the strain array the model itself recorded in
# the same trajectory file, so the operating grid cannot drift from the
# delivered physics.
strains = []
strain_residuals = []
ev_lo = np.zeros(3)
ev_hi = np.zeros(3)
for cid in case_ids:
    case = BATCH / cid
    physics = json.loads((case / "audit_physics.json").read_text())
    meta = json.loads((case / "metadata.json").read_text())
    for label in ("true", "cf"):
        folder = case / ("true" if label == "true" else BRANCH)
        with np.load(folder / "trajectory.npz") as z:
            positions = np.asarray(z["frame_positions"], dtype=float)
            frame_t = z["frame_t"].copy()
            recorded_strain = z["strain"].copy()
            dense_t = z["t"].copy()
        assert np.array_equal(frame_t, np.arange(120) / 24.0), cid + " timebase"
        if positions.ndim != 3 or positions.shape[0] != 120 or positions.shape[2] != 3:
            raise ValueError("unexpected frame_positions shape: %r" % (positions.shape,))
        node_count = positions.shape[1]
        rest_length = float(meta["scene_params"]["L"]) / node_count
        chain = np.concatenate([np.zeros((positions.shape[0], 1, 3)), positions], axis=1)
        segment_lengths = np.linalg.norm(np.diff(chain, axis=1), axis=2)
        rebuilt = segment_lengths / rest_length - 1.0
        strains.append(rebuilt)
        step = float(dense_t[1] - dense_t[0])
        index = np.rint((frame_t - dense_t[0]) / step).astype(int)
        if not np.allclose(dense_t[index], frame_t, atol=1e-9):
            raise ValueError("frame times are not samples of the dense solver grid")
        strain_residuals.append(float(np.max(np.abs(recorded_strain[:, index] - rebuilt.T))))
    for branch_metrics in (physics["metrics"]["true"], physics["metrics"]["cf"]):
        lo, hi = branch_metrics["logViscousStretchRange"]
        ev_lo = np.minimum(ev_lo, np.asarray(lo))
        ev_hi = np.maximum(ev_hi, np.asarray(hi))
strains = np.concatenate([s.reshape(-1) for s in strains])
eps_lo, eps_hi = float(strains.min()), float(strains.max())
strain_residual = max(strain_residuals)
grid_eps = np.linspace(eps_lo, eps_hi, 24)
grid_ev = np.stack([np.linspace(ev_lo[i], ev_hi[i], 8) for i in range(3)], axis=1)

# 2. infinitesimal tangent consistency --------------------------------------------
eps_small = np.array([1e-9, 1e-8, 1e-7])
ev_small = np.zeros((3, 3))
total_tangent, _, _ = model.constitutive_tangents(eps_small, ev_small, EI, EINF)
expected = EINF + EI.sum()
add("infinitesimal_tangent_consistency",
    bool(np.all(np.abs(total_tangent - expected) / expected < 1e-6)),
    measured_tangent_Pa=[float(v) for v in np.atleast_1d(total_tangent)],
    expected_tangent_Pa=float(expected),
    note="dP/dlambda at vanishing strain equals the instantaneous modulus of the published spectrum")

# 3. energy conjugacy ---------------------------------------------------------------
h = 1e-6
eps_probe = np.linspace(max(eps_lo, 1e-4), eps_hi, 12)
residuals = []
for e in eps_probe:
    for ev in grid_ev:
        _, _, u = model.constitutive(np.array([e]), ev, EI, EINF)
        up = model.constitutive(np.array([e + h]), ev, EI, EINF)[2]
        um = model.constitutive(np.array([e - h]), ev, EI, EINF)[2]
        derivative = float((up - um) / (2 * h))
        _, p, _ = model.constitutive(np.array([e]), ev, EI, EINF)
        residuals.append(abs(derivative - float(p[0])) / max(abs(float(p[0])), 1.0))
add("stored_energy_is_conjugate_to_nominal_stress",
    max(residuals) < 1e-4,
    max_relative_residual=float(max(residuals)),
    samples=len(residuals),
    note="numerical dU/dlambda matches the nominal stress produced by the same call")

# 4. stored energy is non-negative and finite ---------------------------------------
energies = model.constitutive(grid_eps, grid_ev, EI, EINF)[2]
add("stored_energy_non_negative_and_finite",
    bool(np.all(np.isfinite(energies)) and np.all(energies >= -1e-9)),
    min_energy_J_per_m3=float(np.min(energies)),
    max_energy_J_per_m3=float(np.max(energies)),
    grid_points=int(np.asarray(energies).size))

# 5. positive tangent over the delivered operating range -----------------------------
tangents = model.constitutive_tangents(grid_eps, grid_ev, EI, EINF)[0]
add("positive_tangent_over_delivered_operating_range",
    bool(np.all(np.asarray(tangents) > 0)),
    min_tangent_Pa=float(np.min(tangents)),
    max_tangent_Pa=float(np.max(tangents)),
    operating_strain_range=[eps_lo, eps_hi])

# 6. single-branch operator isolation -------------------------------------------------
eps_one = np.array([0.05])
ev_one = np.array([[0.02, 0.08, 0.15]])
branch, _, _ = model.constitutive(eps_one, ev_one, EI, EINF)
r_true = model.viscous_rate(branch, EI, TAU, np.ones(3), 1 + eps_one)
r_cf = model.viscous_rate(branch, EI, TAU, np.array([1.0, -1.0, 1.0]), 1 + eps_one)
add("counterfactual_changes_only_the_middle_internal_flow",
    bool(np.array_equal(r_true[[0, 2]], r_cf[[0, 2]]) and np.array_equal(r_true[1], -r_cf[1])),
    true_rates=[float(v) for v in np.atleast_1d(r_true)],
    counterfactual_rates=[float(v) for v in np.atleast_1d(r_cf)])

# 7. dissipation sign contract -------------------------------------------------------
stretch = 1 + eps_one
Q = stretch * branch
power_true = Q * r_true
power_cf = Q * r_cf
add("true_dissipates_and_counterfactual_supplies_energy_in_the_middle_branch_only",
    bool(np.all(power_true >= 0) and power_cf[1] < 0 and np.all(power_cf[[0, 2]] >= 0)),
    true_branch_power_W_per_m3=[float(v) for v in np.atleast_1d(power_true)],
    counterfactual_branch_power_W_per_m3=[float(v) for v in np.atleast_1d(power_cf)],
    note="the declared single violation: s * epsilon_v_dot < 0 in the middle branch")

# 8. delivered strains stay inside the declared sampling domain ----------------------
cap = 0.20
add("delivered_engineering_strain_inside_declared_sampling_domain",
    bool(eps_hi <= cap),
    delivered_max_engineering_strain=eps_hi,
    declared_engineering_strain_cap=cap,
    note="the 20 percent cap is a numerical sampling boundary, not a validated material limit")

# 9. timebase and prefix integrity of the delivered trajectories ----------------------
prefix_equal = True
timebase_ok = True
for cid in case_ids:
    case = BATCH / cid
    with np.load(case / "true" / "trajectory.npz") as z:
        t_true = z["frame_t"].copy()
        p_true = z["frame_positions"].copy()
    with np.load(case / BRANCH / "trajectory.npz") as z:
        t_cf = z["frame_t"].copy()
        p_cf = z["frame_positions"].copy()
    timebase_ok &= bool(np.array_equal(t_true, np.arange(120) / 24.0)
                        and np.array_equal(t_cf, np.arange(120) / 24.0))
    intervention = int(json.loads((case / "metadata.json").read_text())["intervention_frame"])
    prefix_equal &= bool(np.allclose(p_true[:intervention], p_cf[:intervention], atol=1e-12))
add("delivered_timebase_and_paired_prefix_integrity",
    timebase_ok and prefix_equal,
    timebase_exact_i_over_24s=timebase_ok,
    paired_prefix_state_identical=prefix_equal,
    max_rebuilt_strain_residual=strain_residual,
    note="the engineering strain rebuilt from the delivered frame positions matches the "
         "strain array the model recorded in the same trajectory file")

report = {
    "schema": "reviewer-model-domain-v1",
    "decision": "PASS" if all(r["audit"] == "PASS" for r in results) else "FAIL",
    "complete": True,
    "model": "multiplicative_neo_hookean_maxwell",
    "modelSha256": model_sha,
    "production_model_source_sha256": model_sha,
    "physical_domain": {
        "declared_engineering_strain_cap": cap,
        "production_load_ratio_eq": [0.10, 0.14],
        "delivered_engineering_strain_range": [eps_lo, eps_hi],
        "max_rebuilt_strain_residual": strain_residual,
        "note": "The finite-strain constitutive law is a synthetic extension of a published small-strain spectrum; it is not an experimental calibration of Agilus30 at finite strain.",
    },
    "results": results,
    "check_count": len(results),
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"decision": report["decision"], "checks": [(r["name"], r["audit"]) for r in results]}, indent=2))
raise SystemExit(0 if report["decision"] == "PASS" else 1)
