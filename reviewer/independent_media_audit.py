"""Reviewer-written independent decoded-media audit of a delivered case batch.

This script does not import the generator. It re-decodes the delivered MP4
files and re-derives the camera projection from the documented scene so the
mask can be checked against the projected geometry of the violating objects.
"""
import json
import math
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np

BATCH = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
BRANCH = "counterfactual_creep_reversal"


def open_stream(path):
    it = imageio_ffmpeg.read_frames(
        str(path), pix_fmt="rgb24",
        input_params=["-threads", "1"], output_params=["-threads", "1"])
    info = next(it)
    return info, it


def project(points, view, proj, width, height):
    """OpenGL-style projection of world points to pixel coordinates."""
    p = np.asarray(points, dtype=float)
    homo = np.concatenate([p, np.ones((len(p), 1))], axis=1)
    cam = (view @ homo.T).T
    clip = (proj @ cam.T).T
    wclip = clip[:, 3]
    ndc = clip[:, :3] / wclip[:, None]
    u = (ndc[:, 0] * 0.5 + 0.5) * width
    v = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * height
    return np.stack([u, v], axis=1), wclip


def fixtures(params):
    jaw_width = float(params["width"]) + 0.005
    fixture = (2 * jaw_width * .004 * .008 * 2700
               + math.pi * .0018 ** 2 * .004 * 7850
               + 2 * math.pi * .0016 ** 2 * .002 * 7850
               + .024 * .001 * .001 * 2700)
    mass = float(params["payload_mass"])
    radius = (3 * (mass - fixture) / (4 * math.pi * 19300.0)) ** (1 / 3)
    return radius, fixture


def audit_case(case_dir):
    case_dir = Path(case_dir)
    meta = json.loads((case_dir / "metadata.json").read_text())
    params = meta["scene_params"]
    render = meta["render"]
    w, h, n = int(render["width"]), int(render["height"]), int(render["n_frames"])
    intervention = int(meta["intervention_frame"])
    onset_frame = int(meta["mask_start_frame"])
    problems = []
    streams = {
        "true": case_dir / "true" / "video.mp4",
        "cf": case_dir / BRANCH / "video.mp4",
        "mask": case_dir / BRANCH / "mask.mp4",
        "overlay": case_dir / BRANCH / "mask_overlay.mp4",
    }
    infos = {}
    readers = {}
    for key, path in streams.items():
        info, it = open_stream(path)
        infos[key] = info
        readers[key] = it
        if tuple(info["size"]) != (w, h):
            problems.append("%s: delivered size %s != native %s" % (key, info["size"], (w, h)))
        if abs(float(info["fps"]) - 24.0) > 1e-6:
            problems.append("%s: fps %s != 24" % (key, info["fps"]))
        if abs(float(info["duration"]) - n / 24.0) > 0.002:
            problems.append("%s: duration %s != %s" % (key, info["duration"], n / 24.0))
        if not str(info.get("codec", "")).lower().startswith("h264"):
            problems.append("%s: codec %r is not H.264" % (key, info.get("codec")))

    import pybullet as pb
    sign = -1.0 if params.get("mirror", False) else 1.0
    top = float(params["L"]) + 0.24
    az = math.radians(4 + float(params["camera_azimuth"]))
    eye = (sign * .88 * math.sin(az), -.88 * math.cos(az), .339)
    lookat = (-.005 * sign, 0.0, .319)
    view = np.array(pb.computeViewMatrix(eye, lookat, [0, 0, 1]), dtype=float).reshape(4, 4, order='F')
    proj = np.array(pb.computeProjectionMatrixFOV(30, w / h, .01, 5), dtype=float).reshape(4, 4, order='F')

    radius, fixture_mass = fixtures(params)
    adapter = .007
    with np.load(case_dir / "true" / "trajectory.npz") as z:
        t_true = z["frame_t"].copy()
        pos_true = z["frame_positions"].copy()
        plat_true = z["frame_platform"].copy()
    with np.load(case_dir / BRANCH / "trajectory.npz") as z:
        t_cf = z["frame_t"].copy()
        pos_cf = z["frame_positions"].copy()
        plat_cf = z["frame_platform"].copy()

    def world(positions):
        ps = np.vstack([np.zeros((1, 3)), positions])
        return np.stack([sign * ps[:, 0], ps[:, 1], top - ps[:, 2]], axis=1)

    first_changed = None
    mask_counts = []
    overlay_inside_red = []
    sentinel = object()
    geom_rows = []
    yy, xx = np.mgrid[0:h, 0:w]
    for i in range(n):
        raw = {}
        for key in streams:
            buf = next(readers[key], sentinel)
            if buf is sentinel:
                problems.append("%s: stream truncated at frame %d" % (key, i))
                buf = b"\x00" * (w * h * 3)
            raw[key] = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        true, cf = raw["true"], raw["cf"]
        mask_rgb, ov = raw["mask"], raw["overlay"]
        changed = not np.array_equal(true, cf)
        if i < intervention and changed:
            problems.append("frame %d: paired prefix differs before intervention %d" % (i, intervention))
        if changed and first_changed is None:
            first_changed = i
        if not (np.array_equal(mask_rgb[:, :, 0], mask_rgb[:, :, 1])
                and np.array_equal(mask_rgb[:, :, 0], mask_rgb[:, :, 2])):
            problems.append("frame %d: mask channels differ" % i)
        vals = np.unique(mask_rgb)
        if not set(vals.tolist()) <= {0, 255}:
            problems.append("frame %d: mask has non-binary values %s" % (i, vals[:8].tolist()))
        mask = mask_rgb[:, :, 0] == 255
        count = int(mask.sum())
        mask_counts.append(count)
        if i < onset_frame and count:
            problems.append("frame %d: mask active before onset %d" % (i, onset_frame))
        if i >= onset_frame and not count:
            problems.append("frame %d: mask empty at/after onset %d" % (i, onset_frame))
        outside = ~mask
        if not np.array_equal(ov[outside], cf[outside]):
            problems.append("frame %d: overlay changed pixels outside the mask" % i)
        if count:
            inside = ov[mask].astype(np.int16)
            red_ok = (inside[:, 0] - inside[:, 2] > 40) & (inside[:, 0] - inside[:, 1] > 20)
            overlay_inside_red.append(float(red_ok.mean()))
        ws = world(pos_true[i] if i < intervention else pos_cf[i])
        down = ws[-1] - ws[-2]
        down = down / np.linalg.norm(down)
        center = ws[-1] + down * (adapter + radius)
        p_ref = float(plat_cf[i][0] if i >= intervention else plat_true[i][0])
        platform_top = top - p_ref - adapter - 2 * radius
        corners = np.array([[x, y, platform_top - 0.004 + dz]
                            for x in (-.0375, .0375) for y in (-.030, .030)
                            for dz in (-.004, .004)])
        pts = np.vstack([center, corners])
        uv, wclip = project(pts, view, proj, w, h)
        if wclip.min() <= 0:
            problems.append("frame %d: projected geometry behind the camera" % i)
        c = uv[0]
        if not (0 <= c[0] < w and 0 <= c[1] < h):
            problems.append("frame %d: projected payload outside the frame" % i)
        px = int(round(c[0]))
        py = int(round(c[1]))
        inside_sphere = bool(mask[py, px]) if (0 <= px < w and 0 <= py < h) else False
        if i >= onset_frame and not inside_sphere:
            problems.append("frame %d: projected payload centre is not masked" % i)
        view_dir = center - np.asarray(eye)
        view_dir = view_dir / np.linalg.norm(view_dir)
        helper = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(helper, view_dir)) > 0.9:
            helper = np.array([0.0, 1.0, 0.0])
        perp = helper - view_dir * np.dot(helper, view_dir)
        perp = perp / np.linalg.norm(perp)
        edge_uv, _ = project(np.vstack([center, center + perp * radius]), view, proj, w, h)
        pix_radius = float(np.linalg.norm(edge_uv[1] - edge_uv[0]))
        order = [1, 3, 7, 5]
        poly = uv[order]
        inside_poly = np.zeros((h, w), bool)
        for j in range(4):
            a = poly[j]
            b = poly[(j + 1) % 4]
            cond = ((a[1] > yy) != (b[1] > yy))
            xint = (b[0] - a[0]) * (yy - a[1]) / (b[1] - a[1]) + a[0]
            inside_poly ^= cond & (xx < xint)
        dist = np.hypot(xx - c[0], yy - c[1])
        far = inside_poly & (dist > 1.8 * pix_radius)
        mask_hits_platform = int((far & mask).sum())
        if mask_hits_platform:
            problems.append("frame %d: mask covers %d platform/shadow pixels" % (i, mask_hits_platform))
        # The fixed reference ruler is excluded from the mask by contract.
        rail = np.array([[0.041 * sign, 0.009, 0.24]])
        rail_uv, _ = project(rail, view, proj, w, h)
        rpx, rpy = int(round(rail_uv[0, 0])), int(round(rail_uv[0, 1]))
        if 0 <= rpx < w and 0 <= rpy < h and mask[rpy, rpx]:
            problems.append("frame %d: the fixed reference ruler is inside the mask" % i)
        # The visible strip between the clamp and the lower fixture must be masked.
        axis = ws[1:-1]
        axis_uv, _ = project(axis, view, proj, w, h)
        hit = 0
        for (ax, ay) in axis_uv:
            found = False
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    qx, qy = int(round(ax)) + dx, int(round(ay)) + dy
                    if 0 <= qx < w and 0 <= qy < h and mask[qy, qx]:
                        found = True
                        break
                if found:
                    break
            hit += 1 if found else 0
        strip_cover = hit / max(len(axis_uv), 1)
        if i >= onset_frame and strip_cover < 0.8:
            problems.append("frame %d: only %.0f%% of the strip axis is masked" % (i, strip_cover * 100))
        geom_rows.append({"frame": i, "payload_px": [round(float(c[0]), 1), round(float(c[1]), 1)],
                          "payload_radius_px": round(pix_radius, 1),
                          "platform_top_z_m": round(platform_top, 5),
                          "payload_gap_m": round(float(center[2] - radius - platform_top), 5),
                          "mask_pixels": count, "mask_platform_hits": mask_hits_platform, "strip_axis_masked_fraction": round(strip_cover, 3)})
    for key in streams:
        if next(readers[key], sentinel) is not sentinel:
            problems.append("%s: more frames than the declared %d" % (key, n))
        readers[key].close()

    if first_changed is None:
        problems.append("no decoded True/Counterfactual difference")
    elif first_changed != int(meta["first_changed_frame"]):
        problems.append("decoded first changed frame %d != metadata %s" % (first_changed, meta["first_changed_frame"]))
    if first_changed is not None and first_changed != onset_frame:
        problems.append("first changed frame %d != mask onset %d" % (first_changed, onset_frame))
    if intervention != math.ceil(float(params["onset"]) * 24 - 1e-12):
        problems.append("intervention frame is not the declared onset instant")
    if not np.array_equal(t_true, np.arange(n) / 24.0):
        problems.append("True trajectory timebase is not exactly i/24 s")
    if not np.array_equal(t_cf, np.arange(n) / 24.0):
        problems.append("Counterfactual trajectory timebase is not exactly i/24 s")
    pre = min(intervention, n)
    if not np.allclose(pos_true[:pre], pos_cf[:pre], atol=1e-12):
        problems.append("branches are not state-identical before the intervention")

    onset_t = float(params["onset"])
    zt = pos_true[:, -1, 2]
    zc = pos_cf[:, -1, 2]
    ref = float(np.interp(onset_t, t_true, zt))
    true_disp = float(zt[-1] - ref)
    cf_disp = float(zc[-1] - ref)
    if not (true_disp > 0.002):
        problems.append("True does not visibly creep downward after the load release (%.2f mm)" % (true_disp * 1000))
    if not (cf_disp < -0.005):
        problems.append("Counterfactual does not visibly lift the load (%.2f mm)" % (cf_disp * 1000))
    tail = [float(zc[i] - zc[onset_frame]) for i in (onset_frame + 6, onset_frame + 12, onset_frame + 24, n - 1)]
    sustained = all(tail[i + 1] <= tail[i] + 1e-6 for i in range(len(tail) - 1))
    if not sustained:
        problems.append("Counterfactual lift is not sustained (tail %s)" % tail)

    prompts = {
        "true": (case_dir / "true" / "prompt.txt").read_text().strip(),
        "cf": (case_dir / BRANCH / "prompt.txt").read_text().strip(),
    }
    for key, label in (("true", "true"), ("cf", "counterfactual")):
        if prompts[key] != meta["descriptions"][label].strip():
            problems.append("%s prompt file differs from the metadata description" % key)

    return {
        "case_id": case_dir.name,
        "seed": meta["seed"],
        "commit": meta["generation"]["git"]["commit"],
        "dirty": meta["generation"]["git"]["dirty"],
        "stream_info": {k: {kk: vv for kk, vv in v.items() if kk in ("size", "fps", "duration", "codec", "pix_fmt")}
                        for k, v in infos.items()},
        "first_changed_frame": first_changed,
        "intervention_frame": intervention,
        "mask_start_frame": onset_frame,
        "mask_pixel_counts": mask_counts,
        "mask_min_after_onset": int(min(mask_counts[onset_frame:])) if onset_frame < n else 0,
        "overlay_red_fraction_inside_mask_min": round(min(overlay_inside_red), 4) if overlay_inside_red else None,
        "true_creep_after_onset_mm": round(true_disp * 1000, 3),
        "cf_lift_after_onset_mm": round(cf_disp * 1000, 3),
        "cf_lift_tail_mm": [round(v * 1000, 3) for v in tail],
        "payload_radius_m": round(radius, 6),
        "fixture_mass_kg": round(fixture_mass, 6),
        "geometry_head": geom_rows[:2],
        "geometry_tail": geom_rows[-2:],
        "problems": problems,
        "status": "PASS" if not problems else "FAIL",
    }


def main():
    cases = sorted(p for p in BATCH.iterdir() if p.is_dir() and (p / "metadata.json").exists())
    report = {"schema": "reviewer-independent-media-audit-v1", "batch": str(BATCH),
              "cases": [audit_case(p) for p in cases],
              "generator": json.loads((BATCH / "case-manifest.json").read_text()).get("generator")}
    report["status"] = "PASS" if all(c["status"] == "PASS" for c in report["cases"]) else "FAIL"
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"],
                      "cases": [{k: c[k] for k in ("case_id", "status", "problems")} for c in report["cases"]]}, indent=2))


if __name__ == "__main__":
    main()
