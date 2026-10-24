"""피로 기록 앱 KSS 질문 모사(tools/life_sim/self_report.py)와 hub 경로(deskmate/fatigue/label → cache → SensorFrame.self_kss)."""
from __future__ import annotations

import json
import os

from tools.life_sim.self_report import SelfReportApp, kss_from_s

CFG = {"enabled": True, "period_s": 900, "noise_p": 0.0, "delay_s": [5, 60]}


def _run(app, t0, t1, *, S=0.7, kind="upright"):
    out = []
    for t in range(t0, t1):
        lab = app.step(float(t), S=S, kind=kind)
        if lab is not None:
            out.append(lab)
    return out


def test_disabled_by_default():
    app = SelfReportApp({}, seed=1, t0=0.0)
    assert _run(app, 0, 4000) == [] and app.summary() is None


def test_asks_every_period_and_answers_late_with_s_mapping():
    app = SelfReportApp(CFG, seed=3, t0=0.0, profile_id="sim0003")
    labs = _run(app, 0, 2000)
    assert [lab["prompt_ts"] for lab in labs] == [900.0, 1800.0]
    assert all(lab["event"] == "kss" and lab["kss"] == kss_from_s(0.7) == 8 for lab in labs)
    assert all(5.0 <= lab["ts"] - lab["prompt_ts"] <= 61.0 and lab["profile_id"] == "sim0003" for lab in labs)


def test_misses_prompt_while_drowsy_or_away_and_reports_it_later():
    for kind in ("drowsy", "face_down", "away"):
        app = SelfReportApp(CFG, seed=3, t0=0.0)
        labs = _run(app, 0, 1100, kind=kind)
        assert [lab["event"] for lab in labs] == ["prompt_missed"]
        assert labs[0]["prompt_ts"] == 900.0 and labs[0]["ts"] == 1020.0      # miss_after_s 120
        s = app.summary()
        assert s["prompts"] == 1 and s["missed"] == 1 and s["answered"] == 0


def test_bridge_routes_label_to_cache_and_fsm_set_reaches_engine():
    from tools.life_sim.hub_bridge import HubBridge

    hub = HubBridge(fsm_set=["timers.fatigue_hold_min_frac=0.8"], t0=1000.0)
    assert hub.hub.engine.cfg["timers"]["fatigue_hold_min_frac"] == 0.8
    hub.feed_fatigue_label({"event": "kss", "kss": 8, "ts": 1000.0, "prompt_ts": 990.0}, 1000.0)
    assert hub.cache.fatigue_label is not None and hub.cache.fatigue_label.data["kss"] == 8
    assert "self_report" not in HubBridge(t0=0.0).hub.engine.cfg      # 앱 응답은 FSM 규칙에 들어가지 않는다(반응 학습 라벨)


def test_harness_feeds_answers_into_hub_frames(tmp_path):
    from tools.life_sim.harness import run_scenario
    from tools.life_sim.scenario import SCENARIO_DEFAULTS, deep_merge, load_defaults, resolve_reaction, start_epoch
    from tools.posture_sim.synthetic import SyntheticPerson
    from test_life_sim_fatigue import FIXED

    reaction_cfg, devices_cfg, policy_cfg = load_defaults()
    segs = [{"kind": "away", "seconds": 6}, {"kind": "upright", "seconds": 1300, "typing": False},
            {"kind": "away", "seconds": 30, "no_return": True}]
    sc = deep_merge(SCENARIO_DEFAULTS, {"name": "sr", "seed": 5, "segments": segs})
    sc["reaction_resolved"] = resolve_reaction(reaction_cfg, "default", {"fatigue": dict(FIXED, f0=0.6)})
    sc["devices_resolved"] = deep_merge(devices_cfg, {"self_report": {"enabled": True, "period_s": 300, "noise_p": 0.0}})
    sc["policy_resolved"] = policy_cfg
    sc["t0"], sc["path"] = start_epoch("2026-10-22", "14:00"), "<test>"
    res = run_scenario(sc, out_dir=str(tmp_path), source=SyntheticPerson(sc["segments"], seed=5, fps=10.0), progress=False)
    sr = res["self_report"]
    assert sr["prompts"] == 4 and sr["answered"] >= 1 and sr["answered"] + sr["missed"] == sr["prompts"]
    frames = [json.loads(line) for line in open(os.path.join(res["run_dir"], "frames-hub.jsonl"), encoding="utf-8")]
    assert any(f.get("self_kss") is not None for f in frames)
    events = [json.loads(line) for line in open(os.path.join(res["run_dir"], "events.jsonl"), encoding="utf-8")]
    assert sum(1 for e in events if e.get("kind") == "self_report" and e.get("event") == "kss") == sr["answered"]


def _sr_scenario(learning):
    from tools.life_sim.scenario import SCENARIO_DEFAULTS, deep_merge, load_defaults, resolve_reaction, start_epoch
    from test_life_sim_fatigue import FIXED

    reaction_cfg, devices_cfg, policy_cfg = load_defaults()
    segs = [{"kind": "away", "seconds": 6}, {"kind": "upright", "seconds": 2400, "typing": True},
            {"kind": "away", "seconds": 30, "no_return": True}]
    sc = deep_merge(SCENARIO_DEFAULTS, {"name": "sr", "seed": 7, "segments": segs})
    sc["reaction_resolved"] = resolve_reaction(reaction_cfg, "default", {"fatigue": dict(FIXED, f0=0.5)})
    sc["devices_resolved"] = deep_merge(devices_cfg, {"self_report": {"enabled": True, "period_s": 600}})
    sc["policy_resolved"] = policy_cfg
    sc["t0"], sc["path"] = start_epoch("2026-10-22", "14:00"), "<test>"
    sc["hub"]["learning"] = learning
    return sc


def test_checkins_do_not_shift_the_person_when_model_has_no_say(tmp_path):
    """α 를 0 으로 묶고 확인 카드만 띄우면 사람·FSM 은 학습 없는 arm 과 똑같이 흘러야 한다(카드 난수 분리, 10-23 learn14)."""
    from deskmate_hub.learning import load_learning_config
    from tools.life_sim.harness import run_scenario
    from tools.posture_sim.synthetic import SyntheticPerson

    runs = {}
    for arm, lcfg in (("fsm", None), ("ai", dict(load_learning_config(), enabled=True, alpha_max=0.0, probe_band=1.0,
                                                 probe_gap_s=300, n_min=0))):
        sc = _sr_scenario(lcfg)
        res = run_scenario(sc, out_dir=str(tmp_path / arm), source=SyntheticPerson(sc["segments"], seed=7, fps=10.0),
                           progress=False)
        ticks = [json.loads(line) for line in open(os.path.join(res["run_dir"], "ticks.jsonl"), encoding="utf-8")]
        events = [json.loads(line) for line in open(os.path.join(res["run_dir"], "events.jsonl"), encoding="utf-8")]
        runs[arm] = (res, [(tk["state"], round(tk["c_fatigue"], 4)) for tk in ticks],
                     [(e["t"], e.get("what")) for e in events if e.get("kind") == "reaction"])
    assert runs["ai"][0]["reaction_ai"]["checkins"] >= 1
    assert runs["ai"][1] == runs["fsm"][1] and runs["ai"][2] == runs["fsm"][2]
    learning = runs["ai"][0]["reaction_ai"]["learning"]
    assert learning["labels_kss"] >= 1                       # 앱 응답이 라벨로 들어갔다
