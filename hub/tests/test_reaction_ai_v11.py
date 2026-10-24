"""반응학습 v11 — 심박·체동 입력, 사람 고유 심박, 개입 방식 정책 이어 배우기(화면 밝기·공기청정기 선택지)."""
from __future__ import annotations

import os

from deskmate_hub.inference import State
from deskmate_hub.ingest import Sample, SensorCache, SessionTracker, build_frame, load_ingest_config
from deskmate_hub.learning import ReactionLearner


def _mm(now, *, bpm, level):
    return Sample(received=now, ts=now, seq=None, data={
        "present": True, "motion_state": "still" if level <= 10 else "active", "motion_level": level, "distance_cm": 55,
        "resp_bpm": 15, "resp_valid": True, "heart_bpm": bpm, "heart_valid": True, "drowsy_state": "AWAKE", "valid": True})


def test_hr_drop_against_presence_baseline_reaches_frame_and_learner():
    cfg = load_ingest_config()
    cache, tr = SensorCache(), SessionTracker()
    t = 1000.0
    for i in range(30):                                   # 깨어 움직일 때 심박 72 → 기준선
        cache.put("mmwave", _mm(t, bpm=72, level=40))
        f = build_frame(cache.snapshot(), t, cfg, tr, fsm_state=State.FOCUS_PC)
        t += 10.0
    assert f.mm_motion == 40.0
    for i in range(20):                                   # 가만히, 심박 64 → 기준선은 얼고 지금은 내려감
        cache.put("mmwave", _mm(t, bpm=64, level=2))
        f = build_frame(cache.snapshot(), t, cfg, tr, fsm_state=State.FOCUS_PC)
        t += 10.0
    assert f.hr_drop_bpm == 8.0
    lr = ReactionLearner({"enabled": True})
    x = lr.features(f, 0.4, 0.1)
    names = lr.feature_names()
    assert x[names.index("hr_drop")] == 0.8 and x[names.index("hr_avail")] == 1.0
    assert x[names.index("mm_motion")] == 0.02 and x[names.index("mm_avail")] == 1.0
    assert build_frame(SensorCache().snapshot(), t, cfg, SessionTracker(), fsm_state=State.IDLE).hr_drop_bpm is None


def test_heart_model_person_traits_fixed_across_days():
    from tools.posture_sim.mmwave import MmwaveSensor
    cfg = {"hr_model": {"enabled": True}}
    rest = [MmwaveSensor(cfg, seed=s, person_seed=7).heart.rest for s in (7001, 7002, 7003)]
    assert len(set(rest)) == 1
    assert MmwaveSensor(cfg, seed=7001, person_seed=8).heart.rest != rest[0]
    assert MmwaveSensor(cfg, seed=7001).heart.rest != MmwaveSensor(cfg, seed=7002).heart.rest   # person_seed 없으면 이전처럼 날마다


def test_persist_policy_adds_extra_arms_and_keeps_state(tmp_path):
    from tools.life_sim.harness import _setup_hub_policy
    from tools.life_sim.scenario import load_defaults
    devices = load_defaults()[1]
    state = str(tmp_path / "policy.json")
    open(state, "w").write("{}")
    sc = {"persona": "writer", "policy": {"engine": "hub", "profile": "persist", "state_path": state},
          "devices_resolved": devices}
    cfg, path, log, info = _setup_hub_policy(sc, "persist", str(tmp_path), seed=1)
    ids = [a["id"] for a in cfg["arms"]]
    assert path == state and os.path.exists(state) and info["resumed"] is True
    assert {"screen_bright", "purifier_boost", "music_upbeat"} <= set(ids) and "music_upbeat" in cfg["prior"]
    from deskmate_hub.personalize import load_personalize_config
    assert "screen_bright" not in [a["id"] for a in load_personalize_config()["arms"]]   # hub 기본 설정은 그대로


def test_heat_and_dim_sensitivity_per_person_only_when_ranged():
    from tools.life_sim.fatigue import FatigueModel
    base = {"enabled": True}
    a = FatigueModel(base, seed=3, t0=0.0)
    assert (a.hot_c, a.hot_gain, a.dim_lux, a.dim_gain) == (27.0, 0.3, 200.0, 0.3)          # 기본은 이전처럼 고정
    ranged = dict(base, hot={"above_c": [25.0, 29.0], "gain": [0.1, 0.6]}, dim={"below_lux": [150, 300], "gain": [0.1, 0.5]})
    p3, p3b, p4 = (FatigueModel(ranged, seed=s, t0=0.0) for s in (3, 3, 4))
    assert p3.params() == p3b.params() and p3.params()["hot_c"] != p4.params()["hot_c"]
    assert 25.0 <= p3.hot_c <= 29.0 and 0.1 <= p3.dim_gain <= 0.5
    assert {k: v for k, v in p3.params().items() if not k.startswith(("hot", "dim"))} == \
        {k: v for k, v in a.params().items() if not k.startswith(("hot", "dim"))}         # 다른 계수 뽑기는 그대로


def test_disliked_output_wakes_less_and_gets_turned_off():
    """기기 호불호: 싫어하는 출력(예: 음악)은 깨움 효과가 줄고, 자동으로 나오면 되돌린다(정책 벌점). 비어 있으면 이전과 같다."""
    import random
    from tools.life_sim.reaction import ReactionModel
    from tools.life_sim.scenario import load_defaults, resolve_reaction
    cfg = resolve_reaction(load_defaults()[0], "default", None)
    m = ReactionModel(cfg, {}, seed=1)
    base = m._combined("wake", ["music_upbeat"])
    assert m.set_prefs({"enabled": True, "dislike_p": {"music_upbeat": 1.0, "tts": 0.0}, "dislike_wake_mult": 0.5, "undo_p": 1.0},
                       random.Random(0)) == ["music_upbeat"]
    assert m._combined("wake", ["music_upbeat"]) == base * 0.5 and m._combined("wake", ["tts"]) == cfg["wake"]["tts"]
    _, out = m.on_event({"kind": "posture_auto", "gate": "auto"}, 100.0, person_kind="upright", focus=False,
                        channels=["music_upbeat"])
    undo = [r for r in out if r.kind == "feedback"]
    assert len(undo) == 1 and undo[0].payload["why"] == "undo" and undo[0].payload["disliked"] == ["music_upbeat"]
    _, out = m.on_event({"kind": "posture_auto", "gate": "auto"}, 200.0, person_kind="upright", focus=False, channels=["tts"])
    assert not [r for r in out if r.kind == "feedback"]


def test_undo_label_can_be_left_to_the_output_policy():
    from deskmate_hub.learning import ReactionLearner
    from deskmate_hub.inference import SensorFrame, Signal
    from deskmate_hub.inference.types import Scores
    f = SensorFrame(now=1000.0, present=True, pc_ratio=0.9, signals={"posture": Signal(phi=0.1, delta=0.5)})
    for w, n in ((1.0, 1), (0.0, 0)):
        lr = ReactionLearner({"enabled": True, "undo_weight": w})
        lr.adjust(Scores(c_focus=0.1, c_fatigue=0.8, focus_weights={}, fatigue_weights={}), f)
        res = type("R", (), {"state": State.ACTION_POSTURE, "gate": type("G", (), {"value": "auto"})()})()
        lr.after_tick(res, State.CAUSE_ANALYSIS, f, 1000.0)
        lr.on_feedback("reject", None, 1030.0)                  # 자동 실행 뒤 되돌리기
        assert lr.n_labels == n


def test_glaring_light_at_night_gets_turned_off_so_lamp_colour_is_learned():
    """밤(22~6시)에는 청백색 무드등·화면 밝게를 누구나 끈다고 본다 — 정책이 때에 맞는 색을 배우게. 낮에는 그대로."""
    import random
    import time as _t
    from tools.life_sim.reaction import ReactionModel
    from tools.life_sim.scenario import load_defaults, resolve_reaction
    cfg = resolve_reaction(load_defaults()[0], "default", None)
    m = ReactionModel(cfg, {}, seed=2)
    m.set_prefs(dict(cfg["prefs"], enabled=True, dislike_p={}, undo_p=1.0), random.Random(0))
    night = _t.mktime((2026, 10, 24, 23, 30, 0, 0, 0, -1))
    day = _t.mktime((2026, 10, 24, 14, 0, 0, 0, 0, -1))
    _, out = m.on_event({"kind": "posture_auto", "gate": "auto"}, night, person_kind="upright", focus=False, channels=["lamp_cool"])
    assert [r.payload.get("disliked") for r in out if r.kind == "feedback"] == [["lamp_cool"]]
    _, out = m.on_event({"kind": "posture_auto", "gate": "auto"}, night, person_kind="upright", focus=False, channels=["lamp_warm"])
    assert not [r for r in out if r.kind == "feedback"]
    _, out = m.on_event({"kind": "posture_auto", "gate": "auto"}, day, person_kind="upright", focus=False, channels=["lamp_cool"])
    assert not [r for r in out if r.kind == "feedback"]


def test_book_examinee_profile_is_lenient_on_writing_posture():
    from tools.life_sim.daygen import ROLE_INGEST_SET
    assert "tof.posture_delta.lean_forward=0.0" in ROLE_INGEST_SET["book_examinee"]
    assert "tof.posture_delta.forward_head=0.05" in ROLE_INGEST_SET["book_examinee"]     # 책 읽기 → forward_head 오판 대비


def test_pos_weight_scales_drowsy_labels_only():
    from deskmate_hub.inference import SensorFrame, Signal
    f = SensorFrame(now=1000.0, present=True, pc_ratio=0.9, signals={"posture": Signal(phi=0.1, delta=0.5)})
    a, b = ReactionLearner({"enabled": True}), ReactionLearner({"enabled": True, "pos_weight": 3.0})
    x = a.features(f, 0.4, 0.1)
    a._label(x, 1, 0.4, 1000.0, "kss")
    b._label(x, 1, 0.4, 1000.0, "kss")
    assert abs(b.model.w[-1]) > abs(a.model.w[-1])            # 졸림 라벨이 더 세게 움직인다
    a2, b2 = ReactionLearner({"enabled": True}), ReactionLearner({"enabled": True, "pos_weight": 3.0})
    a2._label(x, 0, 0.4, 1000.0, "kss")
    b2._label(x, 0, 0.4, 1000.0, "kss")
    assert a2.model.w == b2.model.w                            # 괜찮음 라벨은 그대로


def test_policy_set_overrides_bandit_weights(tmp_path):
    from tools.life_sim.harness import _setup_hub_policy
    from tools.life_sim.scenario import load_defaults
    sc = {"persona": "neutral", "devices_resolved": load_defaults()[1],
          "policy": {"engine": "hub", "profile": "persist", "state_path": str(tmp_path / "p.json"),
                     "set": ["bandit.weight_effect=0.8", "bandit.weight_accept=0.2"]}}
    cfg, *_ = _setup_hub_policy(sc, "persist", str(tmp_path), seed=1)
    assert cfg["bandit"]["weight_effect"] == 0.8 and cfg["bandit"]["weight_accept"] == 0.2
