"""Session events -> feature dict (SPEC section 6).

ONE implementation: used online by the scorer and offline by
``ml/build_dataset.py``. Pure function, no I/O, deterministic.
Missing data -> feature value ``-1.0`` (never NaN).

The ordered ``FEATURE_NAMES`` list is the contract: the model, the
BigQuery schema and the console all read from it. Adding a feature =
append to the list + a unit test.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from typing import Any, Iterable

MISSING = -1.0

FEATURE_NAMES: list[str] = [
    # fingerprint (taken from the latest `fingerprint` event)
    "fp_webdriver",
    "fp_headless_ua",
    "fp_plugins_zero",
    "fp_outer_zero",
    "fp_languages_count",
    "fp_no_chrome_obj",
    "fp_swiftshader",
    "fp_inner_eq_outer",
    # mouse
    "mouse_move_count",
    "mouse_moves_per_sec",
    "mouse_path_len",
    "mouse_straightness_mean",
    "mouse_speed_mean",
    "mouse_speed_cv",
    "mouse_accel_std",
    "mouse_angle_change_mean",
    "mouse_pause_count",
    # clicks
    "click_count",
    "click_no_premove_ratio",
    "click_center_offset_mean",
    "click_center_offset_std",
    "click_untrusted_ratio",
    # keyboard
    "key_count",
    "key_interval_mean",
    "key_interval_cv",
    "key_hold_mean",
    "key_hold_cv",
    "key_backspace_ratio",
    "key_tab_ratio",
    "key_untrusted_ratio",
    # input
    "input_programmatic_ratio",
    "paste_count",
    "input_fields_touched",
    # timing / navigation
    "time_total_s",
    "time_to_first_interaction_s",
    "time_page_dwell_mean_s",
    "time_page_dwell_cv",
    "time_action_interval_cv",
    "actions_per_sec",
    "nav_page_count",
    "nav_direct_to_sensitive",
    "focus_without_click_ratio",
    "scroll_count",
    "visibility_hidden_count",
]

# Events that count as a physical interaction for time_to_first_interaction.
_INTERACTIONS = {"click", "keydown", "input", "scroll", "focus", "paste", "submit"}
# Deliberate actions for time_action_interval_cv / actions_per_sec.
_ACTIONS = {"click", "keydown", "submit"}

_SENSITIVE_PAGE = "/transfer"
_HOME_PAGE = "/dashboard"


def _get(ev: Any, name: str) -> Any:
    return ev.get(name) if isinstance(ev, dict) else getattr(ev, name, None)


def _norm(events: Iterable[Any]) -> list[tuple[int, float, str, str, dict]]:
    """(seq, wall_ms, type, page, data) tuples sorted by seq."""
    out = []
    for ev in events:
        out.append(
            (
                int(_get(ev, "seq") or 0),
                float(_get(ev, "wall") or 0.0),
                _get(ev, "type") or "",
                _get(ev, "page") or "",
                _get(ev, "data") or {},
            )
        )
    out.sort(key=lambda e: e[0])
    return out


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else MISSING


def _std(values: list[float]) -> float:
    if not values:
        return MISSING
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _cv(values: list[float]) -> float:
    """Coefficient of variation; needs >= 2 samples to show regularity."""
    if len(values) < 2:
        return MISSING
    m = statistics.fmean(values)
    return statistics.pstdev(values) / m if m > 0 else MISSING


def _flag(value: Any) -> float:
    if value is None:
        return MISSING
    return 1.0 if value else 0.0


def _fp_features(evs: list) -> dict[str, float]:
    fps = [e for e in evs if e[2] == "fingerprint"]
    if not fps:
        return {n: MISSING for n in FEATURE_NAMES if n.startswith("fp_")}
    d = fps[-1][4]

    def num(key: str) -> float:
        v = d.get(key)
        return float(v) if isinstance(v, (int, float)) else MISSING

    ua = d.get("ua")
    renderer = (d.get("webgl_renderer") or "").lower()
    inner_w, inner_h = d.get("inner_w"), d.get("inner_h")
    outer_w, outer_h = d.get("outer_w"), d.get("outer_h")

    outer_zero = MISSING
    if isinstance(outer_w, (int, float)) or isinstance(outer_h, (int, float)):
        outer_zero = 1.0 if (outer_w == 0 or outer_h == 0) else 0.0

    inner_eq_outer = MISSING
    if all(isinstance(v, (int, float)) for v in (inner_w, inner_h, outer_w, outer_h)):
        inner_eq_outer = 1.0 if (inner_w == outer_w and inner_h == outer_h) else 0.0

    return {
        "fp_webdriver": _flag(d.get("webdriver")),
        "fp_headless_ua": MISSING if ua is None else (1.0 if "HeadlessChrome" in str(ua) else 0.0),
        "fp_plugins_zero": MISSING if not isinstance(d.get("plugins_count"), (int, float)) else (1.0 if d["plugins_count"] == 0 else 0.0),
        "fp_outer_zero": outer_zero,
        "fp_languages_count": num("languages_count"),
        "fp_no_chrome_obj": MISSING if d.get("has_chrome_obj") is None else (0.0 if d["has_chrome_obj"] else 1.0),
        "fp_swiftshader": 1.0 if ("swiftshader" in renderer or "llvmpipe" in renderer) else (0.0 if renderer else MISSING),
        "fp_inner_eq_outer": inner_eq_outer,
    }


def _mouse_features(evs: list) -> dict[str, float]:
    moves = [e for e in evs if e[2] == "mousemove"]
    n = len(moves)
    out = {"mouse_move_count": float(n), "mouse_pause_count": MISSING}
    if n == 0:
        return out

    pts = [(float(e[4].get("x") or 0.0), float(e[4].get("y") or 0.0)) for e in moves]
    times = [e[1] for e in moves]

    if n == 1:
        out["mouse_path_len"] = 0.0
        out["mouse_pause_count"] = 0.0
        return out

    dists, dts = [], []
    for i in range(1, n):
        dt = (times[i] - times[i - 1]) / 1000.0
        d = math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        dists.append(d)
        dts.append(dt)

    span = (times[-1] - times[0]) / 1000.0
    out["mouse_moves_per_sec"] = n / span if span > 0 else MISSING
    out["mouse_path_len"] = sum(dists)
    out["mouse_pause_count"] = float(sum(1 for dt in dts if dt > 0.3))

    speeds = [d / dt for d, dt in zip(dists, dts) if dt > 0]
    out["mouse_speed_mean"] = _mean(speeds)
    out["mouse_speed_cv"] = _cv(speeds)

    if n >= 3:
        accels = [
            (speeds[i + 1] - speeds[i]) / dts[i + 1]
            for i in range(len(speeds) - 1)
            if dts[i + 1] > 0
        ]
        out["mouse_accel_std"] = _std(accels)
        angles = []
        for i in range(len(pts) - 2):
            ax, ay = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            bx, by = pts[i + 2][0] - pts[i + 1][0], pts[i + 2][1] - pts[i + 1][1]
            cross, dot = ax * by - ay * bx, ax * bx + ay * by
            if cross == 0 and dot == 0:
                continue
            angles.append(abs(math.degrees(math.atan2(cross, dot))))
        out["mouse_angle_change_mean"] = _mean(angles)

    # Straightness: per segment between clicks, displacement / path length.
    clicks = [e[0] for e in evs if e[2] == "click"]
    ratios = []
    start = 0
    move_seqs = [e[0] for e in moves]
    for cseq in clicks + [float("inf")]:
        idx = [i for i, ms in enumerate(move_seqs) if start <= ms < cseq]
        if len(idx) >= 2:
            first, last = pts[idx[0]], pts[idx[-1]]
            disp = math.hypot(last[0] - first[0], last[1] - first[1])
            path = sum(
                math.hypot(
                    pts[idx[j + 1]][0] - pts[idx[j]][0],
                    pts[idx[j + 1]][1] - pts[idx[j]][1],
                )
                for j in range(len(idx) - 1)
            )
            if path > 0:
                ratios.append(disp / path)
        if cseq != float("inf"):
            start = cseq + 1
    out["mouse_straightness_mean"] = _mean(ratios)
    return out


def _click_features(evs: list) -> dict[str, float]:
    clicks = [e for e in evs if e[2] == "click"]
    n = len(clicks)
    if n == 0:
        return {"click_count": 0.0}

    move_walls = sorted(e[1] for e in evs if e[2] == "mousemove")
    no_premove = 0
    offsets = []
    untrusted = 0
    for c in clicks:
        wall, d = c[1], c[4]
        # any mousemove in the 500 ms before this click? (inclusive window)
        i = bisect_left(move_walls, wall - 500.0)
        if i >= len(move_walls) or move_walls[i] > wall:
            no_premove += 1
        rect = d.get("target_rect") or {}
        try:
            rw, rh = float(rect["w"]), float(rect["h"])
            cx, cy = float(rect["x"]) + rw / 2, float(rect["y"]) + rh / 2
            half_diag = math.hypot(rw, rh) / 2
            if half_diag > 0:
                dist = math.hypot(float(d["x"]) - cx, float(d["y"]) - cy)
                offsets.append(dist / half_diag)
        except (KeyError, TypeError, ValueError):
            pass
        if d.get("is_trusted") is False:
            untrusted += 1

    return {
        "click_count": float(n),
        "click_no_premove_ratio": no_premove / n,
        "click_center_offset_mean": _mean(offsets),
        "click_center_offset_std": _std(offsets),
        "click_untrusted_ratio": untrusted / n,
    }


def _key_features(evs: list) -> dict[str, float]:
    downs = [e for e in evs if e[2] == "keydown"]
    ups = [e for e in evs if e[2] == "keyup"]
    n = len(downs)
    if n == 0:
        return {"key_count": 0.0}

    last_down: dict[str, float] = {}
    intervals = []
    for kd in downs:
        field = kd[4].get("field_id") or ""
        if field in last_down:
            intervals.append(kd[1] - last_down[field])
        last_down[field] = kd[1]

    # pair each keyup with the earliest unmatched keydown in the same field
    pending: dict[str, list[float]] = {}
    for kd in downs:
        pending.setdefault(kd[4].get("field_id") or "", []).append(kd[1])
    holds = []
    for ku in ups:
        field = ku[4].get("field_id") or ""
        queue = pending.get(field)
        if queue:
            down_wall = queue.pop(0)
            if ku[1] >= down_wall:
                holds.append(ku[1] - down_wall)

    classes = [kd[4].get("key_class") for kd in downs]
    untrusted = sum(1 for kd in downs if kd[4].get("is_trusted") is False)

    return {
        "key_count": float(n),
        "key_interval_mean": _mean(intervals),
        "key_interval_cv": _cv(intervals),
        "key_hold_mean": _mean(holds),
        "key_hold_cv": _cv(holds),
        "key_backspace_ratio": sum(1 for c in classes if c == "backspace") / n,
        "key_tab_ratio": sum(1 for c in classes if c == "tab") / n,
        "key_untrusted_ratio": untrusted / n,
    }


def _input_features(evs: list) -> dict[str, float]:
    inputs = [e for e in evs if e[2] == "input"]
    out = {
        "paste_count": float(sum(1 for e in evs if e[2] == "paste")),
        "input_fields_touched": float(
            len({e[4].get("field_id") or "" for e in inputs})
        ),
    }
    if not inputs:
        return out

    # Walk events in order, tracking the most recent keydown/paste per field,
    # so "no keydown in the same field within 100 ms" is evaluated correctly.
    last_down: dict[str, float] = {}
    last_paste: dict[str, float] = {}
    prev_len: dict[str, float] = {}
    programmatic = 0
    for e in evs:
        etype, wall, field = e[2], e[1], e[4].get("field_id") or ""
        if etype == "keydown":
            last_down[field] = wall
            continue
        if etype == "paste":
            last_paste[field] = wall
            continue
        if etype != "input":
            continue
        value_length = float(e[4].get("value_length") or 0)
        delta = value_length - prev_len.get(field, 0)
        prev_len[field] = value_length
        if delta < 2:
            continue
        kd_wall = last_down.get(field)
        paste_wall = last_paste.get(field)
        keyed_recently = kd_wall is not None and 0 <= wall - kd_wall <= 100
        pasted_recently = paste_wall is not None and 0 <= wall - paste_wall <= 100
        if not keyed_recently and not pasted_recently:
            programmatic += 1
    out["input_programmatic_ratio"] = programmatic / len(inputs)
    return out


def _timing_nav_features(evs: list) -> dict[str, float]:
    if not evs:
        return {}
    out: dict[str, float] = {}
    total_s = (evs[-1][1] - evs[0][1]) / 1000.0
    out["time_total_s"] = total_s

    pages = [e for e in evs if e[2] == "page"]
    out["nav_page_count"] = float(len(pages))

    # dwell per page view: until the next page event (or the last event)
    dwells = []
    for i, p in enumerate(pages):
        end = pages[i + 1][1] if i + 1 < len(pages) else evs[-1][1]
        dwells.append((end - p[1]) / 1000.0)
    out["time_page_dwell_mean_s"] = _mean(dwells)
    out["time_page_dwell_cv"] = _cv(dwells)

    # time to first interaction per page view
    ttfi = []
    for i, p in enumerate(pages):
        next_page_seq = pages[i + 1][0] if i + 1 < len(pages) else float("inf")
        first = next(
            (e for e in evs
             if p[0] < e[0] < next_page_seq and e[2] in _INTERACTIONS),
            None,
        )
        if first is not None:
            ttfi.append((first[1] - p[1]) / 1000.0)
    out["time_to_first_interaction_s"] = _mean(ttfi)

    actions = sorted(e[1] for e in evs if e[2] in _ACTIONS)
    intervals = [b - a for a, b in zip(actions, actions[1:])]
    out["time_action_interval_cv"] = _cv(intervals)
    if not actions:
        out["actions_per_sec"] = 0.0
    elif total_s > 0:
        out["actions_per_sec"] = len(actions) / total_s
    else:
        out["actions_per_sec"] = MISSING

    paths = [p[3] for p in pages]
    if not paths:
        out["nav_direct_to_sensitive"] = MISSING
    else:
        first_sensitive = next((i for i, p in enumerate(paths) if p == _SENSITIVE_PAGE), None)
        first_home = next((i for i, p in enumerate(paths) if p == _HOME_PAGE), None)
        direct = (
            first_sensitive is not None
            and (first_home is None or first_sensitive < first_home)
        )
        out["nav_direct_to_sensitive"] = 1.0 if direct else 0.0

    clicks = [e for e in evs if e[2] == "click"]
    focuses = [e for e in evs if e[2] == "focus"]
    if focuses:
        without = 0
        for f in focuses:
            field = f[4].get("field_id") or ""
            clicked = any(
                0 <= f[1] - c[1] <= 500
                and (not field or c[4].get("target_id") == field)
                for c in clicks
            )
            if not clicked:
                without += 1
        out["focus_without_click_ratio"] = without / len(focuses)
    else:
        out["focus_without_click_ratio"] = MISSING

    out["scroll_count"] = float(sum(1 for e in evs if e[2] == "scroll"))
    out["visibility_hidden_count"] = float(
        sum(1 for e in evs if e[2] == "visibility" and e[4].get("state") != "visible")
    )
    return out


def compute_features(events: Iterable[Any], until_seq: int | None = None) -> dict[str, float]:
    """Compute the full feature dict for a session's events.

    ``events``: ``harnessguard_core.events.Event`` objects or plain dicts
    with the same fields (seq/t/wall/type/page/data). ``until_seq`` drops
    events with ``seq > until_seq`` (score "as of" a decision point).
    """
    evs = _norm(e for e in events if until_seq is None or (_get(e, "seq") or 0) <= until_seq)
    if not evs:
        return {name: MISSING for name in FEATURE_NAMES}
    feats: dict[str, float] = {}
    feats.update(_fp_features(evs))
    feats.update(_mouse_features(evs))
    feats.update(_click_features(evs))
    feats.update(_key_features(evs))
    feats.update(_input_features(evs))
    feats.update(_timing_nav_features(evs))
    return {name: float(feats.get(name, MISSING)) for name in FEATURE_NAMES}
