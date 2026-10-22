"""생활 각본 폐루프 시뮬(tools/life_sim) — 모델·MuJoCo 없이 도는 부분과, tofsim 이 있으면 짧은 각본 한 바퀴."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

HUB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HUB_DIR not in sys.path:
    sys.path.insert(0, HUB_DIR)

from tools.life_sim.ab import verify_policy_rules                                   # noqa: E402
from tools.life_sim.devices import DeviceRack                                        # noqa: E402
from tools.life_sim.environment import Environment                                   # noqa: E402
from tools.life_sim.person import Person                                             # noqa: E402
from tools.life_sim.posture import NodDetector                                       # noqa: E402
from tools.life_sim.scenario import CONFIG_DIR, Scenario, Segment, Timeline, load_scenario, load_yaml, parse_scenario  # noqa: E402
from tools.life_sim.tofgen import find_tofsim_dir                                    # noqa: E402


def _cfg(name: str):
    return load_yaml(os.path.join(CONFIG_DIR, name))


# ---------------------------------------------------------------- 각본·시간표

def test_scenarios_parse_and_segments_known():
    for name in os.listdir(os.path.join(CONFIG_DIR, "scenarios")):
        sc = load_scenario(name)
        assert sc.timeline and sc.total_s > 0
        assert sc.persona in _cfg("personas.yaml")["personas"]


def test_timeline_override_runs_on_scenario_clock():
    tl = Timeline([Segment("upright", 100.0, typing=True), Segment("drowsy", 600.0), Segment("upright", 100.0)])
    assert tl.effective(50.0)[0] == "upright"
    assert tl.effective(150.0)[0] == "drowsy"
    tl.override("upright", now=200.0, duration_s=120.0, params={"typing": True})
    kind, seg, ov, params = tl.effective(250.0)
    assert kind == "upright" and ov and seg.kind == "drowsy" and params["typing"] is True
    assert tl.effective(330.0)[0] == "drowsy"          # 덮어쓰기가 끝나면 각본의 drowsy 가 그대로 이어진다
    assert tl.effective(750.0)[0] == "upright"


def test_scenario_rejects_unknown_kind():
    with pytest.raises(ValueError):
        parse_scenario({"scenario": {"timeline": [{"kind": "handstand", "duration_s": 10}]}})


# ---------------------------------------------------------------- 끄덕임 검출기

def _grid(head_mm: float) -> tuple[np.ndarray, np.ndarray]:
    dist = np.full((8, 8), 2200, dtype=np.int16)
    dist[:3, :4] = int(head_mm)          # 위 3 행 = 머리
    dist[3:, :4] = 560                   # 몸통
    status = np.full((8, 8), 5, dtype=np.uint8)
    return dist, status


def test_nod_detector_counts_head_drops_not_slow_posture_changes():
    cfg = _cfg("posture.yaml")["nod_detector"]
    det = NodDetector(cfg, fps=10.0)
    t = 0.0
    for _ in range(150):                 # 15 s 바른 자세
        det.observe(t, *_grid(630)); t += 0.1
    assert det.events == 0
    for _ in range(3):                   # 끄덕임 3 번: 1.2 s 숙였다가 복귀
        for _ in range(12):
            det.observe(t, *_grid(380)); t += 0.1
        for _ in range(40):
            det.observe(t, *_grid(630)); t += 0.1
    assert det.events == 3
    assert det.nod_rate_hz(t) >= cfg["drowsy_rate_hz"]
    for _ in range(int(cfg["max_s"] * 10) + 50):      # 오래 숙인 채(엎드림·필기)는 끄덕임이 아니다
        det.observe(t, *_grid(380)); t += 0.1
    assert det.events == 3


# ---------------------------------------------------------------- 환경·기기

def test_environment_co2_rises_closed_and_falls_with_window():
    dcfg = _cfg("devices.yaml")
    persona = _cfg("personas.yaml")["personas"]["student"]
    env = Environment(dcfg, persona, {"temp_c": 17.0, "humidity": 50, "wind_ms": 1.0, "condition": "clear"}, month=10, seed=1)
    c0 = env.state.co2_ppm
    for i in range(60):
        env.step(i * 10.0, 10.0, present=True)
    assert env.state.co2_ppm > c0 + 50
    assert env.open_window(600.0, 15.0)
    peak = env.state.co2_ppm
    for i in range(60, 152):
        env.step(i * 10.0, 10.0, present=True)
    assert env.state.co2_ppm < peak - 100
    assert not env.state.window_open                   # 15 분(1500 s)이 지나면 닫힘
    rain = Environment(dcfg, persona, {"temp_c": 15.0, "humidity": 85, "wind_ms": 2.0, "condition": "rain"}, month=10, seed=1)
    assert not rain.open_window(0.0, 15.0)
    w = env.weather_sample(1000.0)
    assert set(w) >= {"temp_c", "humidity", "wind_ms", "condition", "season", "fetched_at", "source"}


def test_device_rack_follows_control_contract_and_reports_result():
    dcfg = _cfg("devices.yaml")
    persona = _cfg("personas.yaml")["personas"]["student"]
    env = Environment(dcfg, persona, None, month=10, seed=1)
    results = []
    rack = DeviceRack(dcfg, env, results.append)
    rack.tick(0.0)
    rack.handle_command({"command_id": "c1", "target_id": "vent_fan", "operation": "set_power", "value": "on",
                         "origin_state": "ACTION_ENV", "cause": "environment", "gate": "auto"})
    rack.handle_command({"command_id": "c2", "target_id": "desk_lamp", "operation": "set_brightness", "value": 200,
                         "origin_state": "ACTION_ENV", "cause": "environment", "gate": "auto"})
    rack.tick(5.0)
    assert rack.fan_level == dcfg["fan"]["on_level"] and env.fan_level == rack.fan_level
    assert rack.lamp == {"power": True, "brightness": 200} and env.lamp_brightness == 200
    assert {r["command_id"] for r in results} == {"c1", "c2"} and all(r["status"] == "succeeded" for r in results)
    assert rack.arousal_bonus() > 0
    rack.handle_command({"command_id": "c3", "target_id": "vent_fan", "operation": "set_power", "value": "off",
                         "origin_state": "ACTION_ENV", "cause": "environment", "gate": "undo"})
    assert rack.counts["undo"] == 1 and rack.fan_level == 0


# ---------------------------------------------------------------- 사람 반응

def _person(profile: str | None, segments=None):
    rcfg = _cfg("reaction.yaml")
    tl = Timeline(segments or [Segment("drowsy", 3600.0)])
    feedback = []
    p = Person(rcfg, "student", tl, lambda payload, t: feedback.append((t, payload)), np.random.default_rng(0),
               profile=profile, start_ts=0.0, bedtime_hour=23.5)
    return p, tl, feedback


def test_scripted_wake_on_auto_alert_overrides_timeline():
    p, tl, feedback = _person("wake_first")
    iv = p.on_auto(100.0, "posture_voice", "voice", cause="posture", explanation="x")
    assert iv.while_drowsy and iv.script == "wake" and iv.woke
    p.step(200.0)
    assert tl.effective(200.0)[0] == "upright" and tl.effective(200.0)[2]
    assert feedback == []                                 # 자동 실행은 feedback 없음(되돌리기만)


def test_scripted_ignore_then_wake_on_suggest_card():
    p, tl, feedback = _person("wake_on_escalate")
    first = p.on_auto(100.0, "sound_cue", "sound", cause="posture", explanation=None)
    assert first.script == "ignore" and not first.woke and tl.effective(150.0)[0] == "drowsy"
    req = {"data": {"request_id": "r1", "kind": "break_suggest", "arm": "break_short", "expires_in_s": 180, "cause": "cognitive"}}
    second = p.on_request(200.0, req)
    assert second.script == "wake" and second.verdict == "accept"
    p.step(400.0)
    assert feedback and feedback[0][1]["verdict"] == "accept" and feedback[0][1]["request_id"] == "r1"
    assert second.woke and tl.effective(400.0)[0] == "upright"


def test_never_wake_script_ignores_everything():
    p, tl, feedback = _person("never_wake")
    p.on_auto(10.0, "posture_card", "display", cause="posture", explanation=None)
    p.on_request(20.0, {"data": {"request_id": "r2", "kind": "env_suggest", "arm": "air_fan_up", "expires_in_s": 180}})
    p.step(500.0)
    assert feedback == [] and tl.effective(500.0)[0] == "drowsy"
    assert p.summary()["woke"] == 0 and p.summary()["timeout"] == 1


def test_sleep_accept_ends_session_by_leaving():
    p, tl, feedback = _person("wake_first")
    p.on_request(10.0, {"data": {"request_id": "r3", "kind": "break_suggest", "arm": "sleep_suggest", "expires_in_s": 180}})
    p.step(300.0)
    assert p.session_ended and tl.effective(400.0)[0] == "away"


# ---------------------------------------------------------------- 규칙 검증기

def _ep(ts, session, arm, gate, delivered, verdict=None, source="bandit", explanation="이유"):
    return {"schema_name": "personalize_episode", "ts_ms": int(ts * 1000), "session_id": session,
            "fsm": {"gate": gate}, "decision": {"arm": arm, "delivered_gate": delivered, "source": source, "explanation": explanation},
            "feedback": {"verdict": verdict} if verdict else None}


def test_verify_policy_rules_counts_violations():
    ok = [_ep(0, "s1", "air_fan_up", "auto", "auto", "undo"), _ep(400, "s1", "air_fan_up", "auto", "suggest", "accept"),
          _ep(800, "s1", "break_short", "suggest", "suggest", "reject"), _ep(1200, "s1", "posture_card", "auto", "auto")]
    r = verify_policy_rules(ok)
    assert r["undo_then_suggest_ok"] == 1 and r["undo_then_suggest_violations"] == 0
    assert r["reject_reproposed_in_session"] == 0 and r["cooldown_violations"] == 0 and r["missing_explanation"] == 0
    bad = [_ep(0, "s1", "air_fan_up", "auto", "auto", "undo"), _ep(100, "s1", "air_fan_up", "auto", "auto", "auto_kept"),
           _ep(200, "s1", "break_short", "suggest", "suggest", "reject"), _ep(300, "s1", "break_short", "suggest", "suggest", explanation="")]
    r = verify_policy_rules(bad)
    assert r["undo_then_suggest_violations"] == 1 and r["cooldown_violations"] == 1
    assert r["reject_reproposed_in_session"] == 1 and r["missing_explanation"] == 1


# ---------------------------------------------------------------- 폐루프 한 바퀴(tofsim 이 있을 때만)

@pytest.mark.skipif(find_tofsim_dir() is None, reason="dataset/tof_sim_v5(tofsim) 없음 — TOFSIM_DIR 로 지정")
def test_short_closed_loop_numpy_oracle(tmp_path):
    from tools.life_sim.runner import run

    sc = parse_scenario({"scenario": {
        "name": "t_short", "seed": 3, "persona": "student", "start_local": "2026-10-22T14:00:00", "fsm_config": "demo",
        "reaction_profile": "wake_first", "weather": {"temp_c": 17.0, "humidity": 50, "wind_ms": 1.0, "condition": "clear"},
        "timeline": [
            {"kind": "upright", "duration_s": 5400, "typing": True, "window_open": True},     # elapsed 1.0 까지(압축)
            {"kind": "drowsy", "duration_s": 420, "typing": False,
             "nods": {"interval_s": [3, 6], "amp_deg": [35, 50], "microsleep_p": 0.3, "first_s": [2, 4]}},
            {"kind": "upright", "duration_s": 120, "typing": True}],
        "compress": {"upright": 2}}})
    s = run(sc, backend="numpy", posture_backend="oracle", out_dir=str(tmp_path / "run"))
    assert s["simulated"] is True
    assert "ACTION_POSTURE" in s["states_visited"], s["states_visited"]
    assert s["routes"].get("posture") == 1 and s["person"]["woke"] == 1
    assert s["drowsy_flag_recall_ticks"] and s["drowsy_flag_recall_ticks"] > 0.5
    i = s["states_visited"].index("ACTION_POSTURE")
    assert any(st.startswith("FOCUS_") for st in s["states_visited"][i:]), "깨어난 뒤 FOCUS 로 돌아와야 한다"
    rows = [json.loads(l) for l in open(tmp_path / "run" / "timeline.jsonl", encoding="utf-8")]
    assert all("state" in r and "c_fatigue" in r and "gt_label" in r for r in rows)
    assert (tmp_path / "run" / "summary.md").exists() and (tmp_path / "run" / "personalize.jsonl").exists()
