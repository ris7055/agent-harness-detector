"""Feature calculation tests (SPEC section 6, task D2).

Hand-built fixture event lists: a "human-like" session (curvy mouse,
varied key timing) and a "bot-like" one (webdriver, no premove clicks,
centre clicks, programmatic input) — key features must differ in the
expected direction, and compute_features must be deterministic.
"""

from __future__ import annotations

from harnessguard_core.events import Event
from harnessguard_core.features import FEATURE_NAMES, compute_features
from harnessguard_core.rules import score_rules

WALL0 = 1_760_000_000_000.0


def _ev(seq, wall, type_, page, data=None):
    return {"seq": seq, "t": wall, "wall": wall, "type": type_, "page": page,
            "data": data or {}}


HUMAN_FP = {
    "webdriver": False,
    "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "languages_count": 2, "plugins_count": 5,
    "hardware_concurrency": 8, "device_memory": 8,
    "screen_w": 1920, "screen_h": 1080,
    "inner_w": 1536, "inner_h": 820, "outer_w": 1536, "outer_h": 920,
    "dpr": 1.0, "timezone": "Asia/Kuala_Lumpur", "touch_points": 0,
    "has_chrome_obj": True, "webgl_renderer": "ANGLE (Intel UHD)",
    "notification_permission": "default",
}

BOT_FP = {
    "webdriver": True,
    "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) HeadlessChrome/126.0.0.0 Safari/537.36",
    "languages_count": 1, "plugins_count": 0,
    "hardware_concurrency": 4, "device_memory": 8,
    "screen_w": 800, "screen_h": 600,
    "inner_w": 800, "inner_h": 600, "outer_w": 800, "outer_h": 600,
    "dpr": 1.0, "timezone": "UTC", "touch_points": 0,
    "has_chrome_obj": False, "webgl_renderer": "SwiftShader",
    "notification_permission": "default",
}

_USERNAME = "username"


def human_events() -> list[dict]:
    """login (curvy mouse + jittered typing) -> dashboard -> transfer."""
    evs, seq = [], 0

    def add(wall, type_, page, data=None):
        nonlocal seq
        seq += 1
        evs.append(_ev(seq, WALL0 + wall, type_, page, data))

    add(0, "page", "/login", {"path": "/login", "referrer_path": ""})
    add(5, "fingerprint", "/login", HUMAN_FP)
    # curvy mouse arc towards the username field, varied 55-120 ms gaps
    wall = 800.0
    for (x, y), dt in zip(
        [(100, 500), (140, 470), (190, 452), (250, 440), (310, 430),
         (360, 412), (400, 392), (430, 372), (455, 356), (470, 348)],
        [0, 90, 60, 110, 75, 100, 55, 95, 80, 120],
    ):
        wall += dt
        add(wall, "mousemove", "/login", {"x": x, "y": y})
    wall += 160
    add(wall, "click", "/login", {
        "x": 470, "y": 348, "target_id": _USERNAME, "target_tag": "input",
        "target_rect": {"x": 430, "y": 328, "w": 200, "h": 40},
        "is_trusted": True, "button": 0})
    add(wall + 40, "focus", "/login", {"field_id": _USERNAME})
    # type "daniel": jittered keydown/keyup holds and inter-key intervals
    wall += 250
    for i, (gap, hold) in enumerate([(0, 82), (140, 95), (260, 70),
                                     (430, 110), (560, 88), (800, 76)]):
        add(wall + gap, "keydown", "/login",
            {"key_class": "char", "field_id": _USERNAME, "is_trusted": True})
        add(wall + gap + hold, "keyup", "/login",
            {"key_class": "char", "field_id": _USERNAME, "is_trusted": True})
        add(wall + gap + hold + 8, "input", "/login",
            {"field_id": _USERNAME, "value_length": i + 1})
    wall += 1400
    add(wall, "click", "/login", {
        "x": 480, "y": 520, "target_id": "login-btn", "target_tag": "button",
        "target_rect": {"x": 430, "y": 500, "w": 200, "h": 44},
        "is_trusted": True, "button": 0})
    add(wall + 60, "submit", "/login", {"form_id": "login-form"})

    wall += 2000
    add(wall, "page", "/dashboard", {"path": "/dashboard", "referrer_path": "/login"})
    add(wall + 900, "scroll", "/dashboard", {"scroll_y": 240})
    wall += 2600
    add(wall, "click", "/dashboard", {
        "x": 300, "y": 200, "target_id": "nav-transfer", "target_tag": "a",
        "target_rect": {"x": 250, "y": 180, "w": 120, "h": 36},
        "is_trusted": True, "button": 0})

    wall += 1800
    add(wall, "page", "/transfer", {"path": "/transfer", "referrer_path": "/dashboard"})
    wall += 500
    for x, y in [(500, 300), (520, 290), (545, 285), (560, 282)]:
        wall += 70
        add(wall, "mousemove", "/transfer", {"x": x, "y": y})
    wall += 120
    add(wall, "click", "/transfer", {
        "x": 560, "y": 282, "target_id": "to_name", "target_tag": "input",
        "target_rect": {"x": 500, "y": 260, "w": 240, "h": 40},
        "is_trusted": True, "button": 0})
    add(wall + 30, "focus", "/transfer", {"field_id": "to_name"})
    return evs


def bot_events() -> list[dict]:
    """script-like agent: webdriver, no premove clicks, centre clicks,
    robotic 100 ms typing in one field, programmatic fill elsewhere,
    straight to /transfer."""
    evs, seq = [], 0

    def add(wall, type_, page, data=None):
        nonlocal seq
        seq += 1
        evs.append(_ev(seq, WALL0 + wall, type_, page, data))

    add(0, "page", "/login", {"path": "/login", "referrer_path": ""})
    add(2, "fingerprint", "/login", BOT_FP)
    add(120, "click", "/login", {
        "x": 530, "y": 348, "target_id": _USERNAME, "target_tag": "input",
        "target_rect": {"x": 430, "y": 328, "w": 200, "h": 40},
        "is_trusted": True, "button": 0})
    # robotic typing: exactly 100 ms between keydowns, 40 ms holds
    wall = 400.0
    for i in range(6):
        add(wall + i * 100, "keydown", "/login",
            {"key_class": "char", "field_id": _USERNAME, "is_trusted": True})
        add(wall + i * 100 + 40, "keyup", "/login",
            {"key_class": "char", "field_id": _USERNAME, "is_trusted": True})
        add(wall + i * 100 + 45, "input", "/login",
            {"field_id": _USERNAME, "value_length": i + 1})
    wall += 900
    add(wall, "click", "/login", {
        "x": 530, "y": 522, "target_id": "login-btn", "target_tag": "button",
        "target_rect": {"x": 430, "y": 500, "w": 200, "h": 44},
        "is_trusted": True, "button": 0})
    add(wall + 30, "submit", "/login", {"form_id": "login-form"})

    wall += 1500
    add(wall, "page", "/transfer", {"path": "/transfer", "referrer_path": "/dashboard"})
    wall += 300
    # page.fill()-style programmatic input: value jumps with no key events
    add(wall, "input", "/transfer", {"field_id": "to_name", "value_length": 11})
    add(wall + 20, "input", "/transfer", {"field_id": "to_account", "value_length": 14})
    add(wall + 40, "input", "/transfer", {"field_id": "amount", "value_length": 6})
    wall += 200
    add(wall, "click", "/transfer", {
        "x": 620, "y": 640, "target_id": "review-btn", "target_tag": "button",
        "target_rect": {"x": 500, "y": 620, "w": 240, "h": 40},
        "is_trusted": True, "button": 0})
    add(wall + 30, "submit", "/transfer", {"form_id": "transfer-form"})
    return evs


def test_empty_input_is_all_missing():
    f = compute_features([])
    assert set(f) == set(FEATURE_NAMES)
    assert all(v == -1.0 for v in f.values())


def test_all_features_present():
    for evs in (human_events(), bot_events()):
        f = compute_features(evs)
        assert set(f) == set(FEATURE_NAMES)


def test_deterministic():
    assert compute_features(human_events()) == compute_features(human_events())


def test_accepts_event_objects_and_dicts():
    dicts = human_events()
    objs = [Event.model_validate(e) for e in dicts]
    assert compute_features(objs) == compute_features(dicts)


def test_bot_vs_human_directions():
    hf, bf = compute_features(human_events()), compute_features(bot_events())

    assert hf["fp_webdriver"] == 0.0 and bf["fp_webdriver"] == 1.0
    assert hf["fp_headless_ua"] == 0.0 and bf["fp_headless_ua"] == 1.0
    assert hf["fp_plugins_zero"] == 0.0 and bf["fp_plugins_zero"] == 1.0
    assert hf["fp_swiftshader"] == 0.0 and bf["fp_swiftshader"] == 1.0

    assert hf["mouse_move_count"] > 0 and bf["mouse_move_count"] == 0.0
    assert hf["mouse_path_len"] > 0 and bf["mouse_path_len"] == -1.0
    assert hf["mouse_speed_cv"] > bf["mouse_speed_cv"]  # -1 for the bot

    assert bf["click_no_premove_ratio"] > hf["click_no_premove_ratio"]
    assert bf["click_center_offset_mean"] < 0.1 <= hf["click_center_offset_mean"]

    assert bf["input_programmatic_ratio"] > hf["input_programmatic_ratio"]
    assert hf["input_programmatic_ratio"] == 0.0

    assert hf["key_interval_cv"] > 0.15 > bf["key_interval_cv"] >= 0.0
    assert hf["key_hold_cv"] >= 0.0

    assert hf["nav_direct_to_sensitive"] == 0.0
    assert bf["nav_direct_to_sensitive"] == 1.0
    assert hf["nav_page_count"] == 3.0 and bf["nav_page_count"] == 2.0
    assert hf["actions_per_sec"] > 0 and hf["time_total_s"] > 0


def test_rules_score_direction():
    human_score, _ = score_rules(compute_features(human_events()))
    bot_score, reasons = score_rules(compute_features(bot_events()))
    assert bot_score > human_score
    assert human_score < 0.50  # allow band
    assert bot_score >= 0.50   # step_up or block
    assert reasons and reasons[0]["feature"].startswith("fp_")


def test_until_seq_truncates():
    evs = human_events()
    cut = evs[2]["seq"]  # only page + fingerprint
    f = compute_features(evs, until_seq=cut)
    assert f["nav_page_count"] == 1.0
    assert f["click_count"] == 0.0
    assert compute_features(evs)["nav_page_count"] == 3.0


def test_missing_groups_are_minus_one():
    evs = [_ev(1, WALL0, "page", "/login", {"path": "/login"})]
    f = compute_features(evs)
    assert f["fp_webdriver"] == -1.0      # no fingerprint event
    assert f["mouse_move_count"] == 0.0   # a real count of zero
    assert f["mouse_speed_mean"] == -1.0  # undefined with no moves
    assert f["click_count"] == 0.0
    assert f["click_no_premove_ratio"] == -1.0  # undefined with no clicks
    assert f["key_count"] == 0.0
    assert f["input_programmatic_ratio"] == -1.0


def test_feature_names_stable_order():
    # the ordered list is the contract for model, BQ schema and console
    assert FEATURE_NAMES[0] == "fp_webdriver"
    assert FEATURE_NAMES[-1] == "visibility_hidden_count"
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    # session ids / labels must never leak in as features
    assert not any("session" in n or "label" in n for n in FEATURE_NAMES)


def test_event_batch_fixture_shapes():
    # fixture events conform to the Event model the collector produces
    for e in bot_events():
        Event.model_validate(e)
