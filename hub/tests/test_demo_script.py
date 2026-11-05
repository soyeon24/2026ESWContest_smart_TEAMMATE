"""11-03 결선 대본(8분) — 빠른 시연에서 같은 자세에 사람마다 다른 기기가 나가는가(demo_wake.py, control.yaml demo_wake:).

A(태환, 도움 순서 알림 › 조명 › 선풍기): 뒤로 젖히기 → 음악, 졸기(엎드림) → 음악+조명, 거북목 → 바른 자세 안내, 자리 비움 → 전부 끄기.
B(민경, 조명 › 선풍기 › 알림): 뒤로 젖히기 → 조명, 다시 젖히기 → 조명, 졸기 → 조명+선풍기, 턱 괴기 → 안내, 자리 비움 → 끄기.
B 가 앉을 때 A 의 기기를 되살리지 않는다. 보드처럼 개인화 정책은 끄고(DESKMATE_PERSONALIZE=off = 기록만) 돌린다.
"""
from __future__ import annotations

import io

import pytest

from deskmate_hub.control import MockPlugAdapter, load_control_config
from deskmate_hub.demo_wake import DemoWake
from deskmate_hub.ingest import SensorCache
from deskmate_hub.ingest.cache import Sample
from deskmate_hub.live import LiveHub
from deskmate_hub.personalize import load_personalize_config

from test_ingest_mapping import env, mm
from test_posture_actions import CFG as CONTROL_CFG
from test_tof_service import svc, svc_probs

A = {"profile_id": "pA", "light_pref": "mid", "sound_pref": "low", "wind_pref": "off", "focus_help": ["sound", "light", "wind"]}
B = {"profile_id": "pB", "light_pref": "mid", "sound_pref": "low", "wind_pref": "off", "focus_help": ["light", "wind", "sound"]}
REAL = load_control_config()


# 11-06 실기 설정은 escalate_by_count(첫 깨우기 1개 · 두 번째부터 2개). 아래 자세 깊이(mild 1·deep 2) 시험은 그 규칙을 끈 설정으로.
DEPTH = dict(REAL["demo_wake"], escalate_by_count=False)
RISE = {k: v for k, v in DEPTH.items() if k != "warm_temp_c"}   # 상승 규칙(warm_temp_c 없을 때) 시험용


def _warm(w: DemoWake, rise: float) -> DemoWake:
    """방 온도를 관측: 25.0 °C 에서 rise 만큼 오른 상태로 둔다."""
    w.observe_temp(25.0, 0.0)
    w.observe_temp(25.0 + rise, 60.0)
    return w


def _temp(w: DemoWake, temp_c: float) -> DemoWake:
    """방 온도를 관측: 24.0 °C 였다가 지금 temp_c."""
    w.observe_temp(24.0, 0.0)
    w.observe_temp(temp_c, 60.0)
    return w


def test_fan_only_at_30c():
    """11-05 21:3x 사용자 "상승 보지 말고 30도 기준으로만 판단해" — 보드 설정(warm_temp_c 30): 지금 방 온도 ≥ 30 °C 일 때만 선풍기."""
    assert REAL["demo_wake"]["warm_temp_c"] == 30.0
    assert _temp(DemoWake(DEPTH), 30.0).decide("face_down", B["focus_help"])["helps"] == ["light", "wind"]
    assert _temp(DemoWake(DEPTH), 29.9).decide("face_down", B["focus_help"])["helps"] == ["light", "sound"]
    rose = _warm(DemoWake(DEPTH), 1.0)                      # 25 → 26 °C: 1 °C 올라도 30 °C 아래면 선풍기 없음
    assert rose.decide("recline", A["focus_help"])["helps"] == ["sound"]
    p = _temp(DemoWake(DEPTH), 31.0).decide("recline", A["focus_help"])
    assert p["helps"] == ["sound", "wind"] and p["causes"] == ["posture", "environment"] and p["temp_c"] == 31.0
    assert _temp(DemoWake(DEPTH), 30.5).decide("upright", A["focus_help"])["helps"] == ["wind"]   # 더위만
    assert DemoWake(DEPTH).decide("face_down", B["focus_help"])["helps"] == ["light", "sound"]   # 온도 모름


def test_rule_picks_by_help_order_and_depth():
    w = DemoWake(DEPTH)
    assert w.decide("recline", A["focus_help"])["helps"] == ["sound"]
    assert w.decide("recline", B["focus_help"])["helps"] == ["light"]
    assert w.decide("face_down", B["focus_help"])["helps"] == ["light", "sound"]                # 온도 관측 없음 → 선풍기 안 고름
    assert w.decide("forward_head", A["focus_help"])["kind"] == "notice"
    assert w.decide("upright", A["focus_help"]) is None
    assert w.decide("recline", None)["helps"] == ["light"]                 # 프로필 없음 → default_order
    assert w.decide("recline", ["break", "voice"]) is None                 # 기기 없는 도움만 → 원래 경로
    assert DemoWake({}).decide("recline", A["focus_help"]) is None         # 설정 없으면 꺼짐


def test_fan_only_when_room_temperature_rises():
    """warm_temp_c 가 없을 때의 상승 규칙(11-05 오후 판, 21:3x 에 30 °C 기준으로 바뀜) — 최근 10분 최저 대비 상승(0.5 °C)."""
    assert _warm(DemoWake(RISE), 0.6).decide("face_down", B["focus_help"])["helps"] == ["light", "wind"]
    assert _warm(DemoWake(RISE), 0.2).decide("face_down", B["focus_help"])["helps"] == ["light", "sound"]
    # 원인 자세 + 환경(온도 상승): 자세 몫(도움 순서)에 선풍기를 더한다 — 사용자 "자세 + 환경이면 조명과 선풍기 둘 다"
    assert _warm(DemoWake(RISE), 0.6).decide("face_down", A["focus_help"])["helps"] == ["sound", "light", "wind"]
    assert _warm(DemoWake(RISE), 0.6).decide("recline", B["focus_help"])["helps"] == ["light", "wind"]
    assert _warm(DemoWake(RISE), 0.6).decide("recline", A["focus_help"])["helps"] == ["sound", "wind"]
    p = _warm(DemoWake(RISE), 0.6).decide("forward_head", A["focus_help"])
    assert p["kind"] == "notice" and p["helps"] == ["wind"] and p["causes"] == ["posture", "environment"]
    assert _warm(DemoWake(RISE), 0.6).decide("upright", A["focus_help"])["helps"] == ["wind"]   # 더위만
    assert _warm(DemoWake(RISE), 0.2).decide("upright", A["focus_help"]) is None
    hot = DemoWake(RISE)                                       # 처음부터 30 °C 여도 오르지 않았으면 안 고른다
    hot.observe_temp(30.0, 0.0); hot.observe_temp(30.0, 60.0)
    assert hot.decide("face_down", B["focus_help"])["helps"] == ["light", "sound"]
    old = DemoWake(RISE)                                       # 10분 넘은 낮은 값은 잊는다
    old.observe_temp(24.0, 0.0); old.observe_temp(25.0, 700.0)
    assert old.temp_rise() == 0.0
    w = _warm(DemoWake(RISE), 0.6)
    assert all(s["ignore_cooldown"] for s in w.decide("face_down", B["focus_help"])["specs"])
    assert w.snapshot()["temp_rise_c"] == 0.6


@pytest.fixture
def sent(monkeypatch):
    log: list[dict] = []
    orig = MockPlugAdapter.handle_command

    def record(self, payload):
        log.append(payload)
        return orig(self, payload)

    monkeypatch.setattr(MockPlugAdapter, "handle_command", record)
    return log


def _hub(tmp_path, wake=None):
    cache, reqs = SensorCache(), []
    cfg = dict(CONTROL_CFG, demo_wake=wake or DEPTH, absent_off=REAL["absent_off"], arm_notice=REAL.get("arm_notice"),
               hot_fan=REAL.get("hot_fan"))
    pcfg = dict(load_personalize_config(), enabled=False, log_dir=str(tmp_path))
    hub = LiveHub(cache, control_cfg=cfg, publish=lambda e: None, publish_request=reqs.append, out=io.StringIO(),
                  profile="demo-b", personalize_cfg=pcfg, personalize_log_path=str(tmp_path / "p.jsonl"),
                  personalize_policy_path=str(tmp_path / "policy.json"))
    cache.put("demo_mode", Sample(received=0.0, ts=0.0, seq=None, data={"speed": "fast"}))
    return hub, cache, reqs


class Script:
    def __init__(self, hub, cache, reqs, sent):
        self.hub, self.cache, self.reqs, self.sent, self.t = hub, cache, reqs, sent, 0.0
        self.trace: list[tuple[float, str, str]] = []
        self.temp = 25.0                                                    # 방 온도(°C) — B 졸기 전에 올린다

    def person(self, profile):
        self.cache.put("user_profile", Sample(received=self.t, ts=self.t, seq=1, data=dict(profile)))

    def hold(self, posture: str, seconds: float, *, until=None, probs=None):
        """posture 를 seconds 동안(또는 until(새 명령, 새 카드)이 참일 때까지). 이 구간에 나간 (기기, 동작, 값) 과 카드 arm."""
        n_cmd, n_req, end = len(self.sent), len(self.reqs), self.t + seconds
        away = posture == "away"
        while self.t < end:
            self.cache.put("mmwave", mm(self.t, present=not away, level=5, dist=120 if away else 55))
            self.cache.put("env", env(self.t, co2=700, temp=self.temp))
            self.cache.put("tof_service", svc_probs(self.t, probs, posture=posture) if probs is not None
                           else svc(self.t, posture=posture, conf=1.0, present=not away))
            self.hub.tick_once(self.t)
            self.trace.append((self.t, posture, self.hub.engine.state.value))
            self.t += self.hub.period
            cmds = [(c["target_id"], c["operation"], c["value"]) for c in self.sent[n_cmd:]
                    if c["target_id"] != "speaker"]
            cards = [r["data"].get("arm") for r in self.reqs[n_req:] if (r.get("data") or {}).get("arm")]
            if until is not None and until(cmds, cards):
                break
        return cmds, cards


def _devices(cmds):
    return sorted({t for t, op, _ in cmds})


def test_script_a_then_b_fits_8_minutes(tmp_path, sent):
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    acted = lambda cmds, cards: bool(cmds or cards)                      # noqa: E731

    s.person(A)
    s.hold("upright", 30)                                                 # 바르게 앉기 → 집중
    cmds, _ = s.hold("recline", 60, until=acted)
    assert _devices(cmds) == ["music"] and cmds[0][2] == {"on": True}, cmds
    s.hold("upright", 30)                                                 # 깨기
    cmds, _ = s.hold("face_down", 60, until=acted)
    assert _devices(cmds) == ["desk_lamp", "music"], "\n".join(f"{t:.0f} {p} {st}" for t, p, st in s.trace)   # 두 번째는 음악 + 조명
    s.hold("upright", 30)
    t0 = s.t
    cmds, cards = s.hold("forward_head", 60, until=acted)
    assert cmds == [] and cards == ["posture_card"], (cmds, cards)        # 거북목 → 바른 자세 안내
    # 11-05 사용자 "거북목이 한번이라도 잡히면 5초안에 안내카드": 잡힌 그 판정에 바로(의심 → 확정 → 원인 → 개입 15~20 s 를 기다리지 않음)
    assert s.t - t0 <= 5.0, s.t - t0
    cmds, cards = s.hold("forward_head", 30)
    assert cards == [], cards                                             # 떠 있는 동안 같은 카드를 다시 내지 않는다
    # 11-05 사용자 "카드는 시간을 너무 배속하지 마": 빠른 시연이 집중 저하 관찰을 5 s 로 줄여도 카드는 원래 시간(≥ 60 s) 떠 있다
    assert s.hub.engine.tm["focus_break_poll_sec"] == 5.0
    assert [r["data"]["expires_in_s"] for r in s.reqs if (r.get("data") or {}).get("arm") == "posture_card"][-1] >= 60
    s.hold("upright", 30)
    cmds, _ = s.hold("away", 40, until=lambda c, _: len(c) >= 3)
    assert _devices(cmds) == ["desk_lamp", "music", "vent_fan"] and all(
        v in ("off", {"on": False}) for _, _, v in cmds), cmds          # 자리 비움 → 전부 끄기
    a_end = s.t

    s.person(B)
    cmds, _ = s.hold("upright", 30)
    assert cmds == [], cmds                                               # A 의 기기를 되살리지 않는다
    cmds, _ = s.hold("recline", 60, until=acted)
    assert _devices(cmds) == ["desk_lamp"], cmds                          # B 는 조명 먼저
    s.hold("upright", 30)
    cmds, _ = s.hold("recline", 60, until=acted)
    assert _devices(cmds) == ["desk_lamp"], cmds                          # 다시 조명(쿨다운에 안 막힘)
    s.hold("upright", 30)
    s.temp = 30.2                                                         # 방이 30 °C 를 넘음 → 선풍기(11-05 상승 대신 30 °C 기준)
    cmds, _ = s.hold("upright", 10)
    assert _devices(cmds) == ["vent_fan"], cmds                           # 바른 자세여도 30 °C 면 hot_fan 이 먼저 켠다
    cmds, _ = s.hold("face_down", 60, until=lambda c, _: "desk_lamp" in _devices(c))
    assert _devices(cmds) == ["desk_lamp", "vent_fan"], cmds              # 졸기 → 조명 + 선풍기
    s.hold("upright", 30)
    cmds, cards = s.hold("chin_rest", 60, until=lambda c, k: bool(c and k))
    # 방이 아직 30 °C 위라 원인 자세 + 환경 → 안내 카드(잡힌 판정에 바로) + 개입 때 선풍기(이미 켜져 있으면 그대로)
    assert _devices(cmds) == ["vent_fan"] and cards == ["posture_card"], (cmds, cards)
    s.hold("upright", 30)
    cmds, _ = s.hold("away", 40, until=lambda c, _: len(c) >= 3)
    assert _devices(cmds) == ["desk_lamp", "music", "vent_fan"], cmds

    # 빠른 시연 판정 주기 5 s(fsm.yaml demo_fast.period_sec)·깨운 뒤 바르게 30 s 기준. 센서 tick 시간 — 사람 동작·멘트 시간은 별도
    print(f"[demo_script] A {a_end:.0f}s, 전체 {s.t:.0f}s")
    assert hub.period == 5.0
    assert a_end <= 240 and s.t <= 480, (a_end, s.t)


def test_normal_speed_keeps_old_path(tmp_path, sent):
    """빠른 시연이 아니면 규칙이 끼어들지 않는다 — 뒤로 젖히기는 확정되지 않는다(demo-b 0.48 < 0.60)."""
    hub, cache, reqs = _hub(tmp_path)
    cache.put("demo_mode", Sample(received=0.0, ts=0.0, seq=None, data={"speed": "normal"}))
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 30)
    cmds, _ = s.hold("recline", 180)
    assert cmds == [] and hub.demo_wake.last is None, cmds


def test_fast_absent_turns_devices_off_within_5s_but_ignores_one_tick(tmp_path, sent):
    """11-04 사용자 "자리비움 한번 뜨고 5초 안으로 주변기기 다 꺼지게" — 빠른 시연은 부재 5 s(fsm.yaml demo_fast.absent_off_after_sec).
    한 tick 만 튄 부재(11-04 13:35:10 MLP away)는 다음 tick 이 재실이면 끄지 않는다."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 40)
    cmds, _ = s.hold("away", 5)                                           # 한 tick 부재
    assert cmds == [], cmds
    s.hold("upright", 10)
    first_away = s.t
    cmds, _ = s.hold("away", 30, until=lambda c, _: len(c) >= 3)
    assert _devices(cmds) == ["desk_lamp", "music", "vent_fan"], cmds
    assert s.t - first_away <= 10, (first_away, s.t)                      # 첫 부재 tick + 5 s 뒤 tick 에 끔


def test_notice_card_closes_and_focus_returns_after_sitting_up(tmp_path, sent):
    """11-05 사용자 "5초로 바꿔": 거북목 안내 카드는 바른 자세로 돌아온 첫 판정(5 s)에 닫히고, 깨운 뒤 지켜보기도 5 s 라
    곧 집중으로 돌아간다. 닫기 = 같은 request_id 를 expires_in_s 0.1 로 다시 보내기(앱 알림판이 같은 id 를 바꿔 끼운다)."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 30)
    _, cards = s.hold("forward_head", 60, until=lambda c, k: bool(k))
    assert cards == ["posture_card"]
    card_id = [r for r in reqs if (r.get("data") or {}).get("arm") == "posture_card"][-1]["data"]["request_id"]
    up_at = s.t
    closed_at = focus_at = None
    while s.t < up_at + 60 and (closed_at is None or focus_at is None):
        s.hold("upright", hub.period)
        if closed_at is None and any((r.get("data") or {}).get("request_id") == card_id
                                     and r["data"]["expires_in_s"] < 1 for r in reqs):
            closed_at = s.t
        if focus_at is None and hub.engine.state.value.startswith("FOCUS_"):
            focus_at = s.t
    assert closed_at is not None and closed_at - up_at <= 5.0, (up_at, closed_at)
    print(f"[demo_script] 카드 닫힘 +{closed_at - up_at:.0f}s, 집중 복귀 +{focus_at - up_at:.0f}s")
    assert focus_at is not None and focus_at - up_at <= 20.0, (up_at, focus_at)


def test_posture_and_heat_both_act_even_if_cause_flickers(tmp_path, sent):
    """11-05 실기: 젖힘으로 졸음 확정 → 원인 판단 tick 에 자세가 upright 로 흔들리고 방이 더워 원인이 환경으로 갔다
    → 대본 규칙을 건너뛰어 선풍기 명령이 없었다. 확정 순간의 자세를 기억해 첫 개입은 규칙대로(B: 조명 + 오른 온도면 선풍기)."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(B)
    s.temp = 25.0
    s.hold("upright", 30)
    s.temp = 31.0                                                        # 6 °C 상승 — 환경 점수도 크다
    while hub.engine.state.value != "FATIGUE" and s.t < 200:
        s.hold("recline", hub.period)
    assert hub.engine.state.value == "FATIGUE", s.trace[-5:]
    cmds, _ = s.hold("upright", 30, until=lambda c, k: bool(c))           # 원인 판단 tick 부터 바른 자세로 흔들림
    states = [st for _, _, st in s.trace[-8:]]
    assert _devices(cmds) == ["desk_lamp", "vent_fan"], (cmds, states)   # 젖힘(자세) = 조명 + 더위(환경) = 선풍기


# 11-05 사용자 "엎드림이 99 %에서 조금이라도 턱 괴기로 넘어가면 주변기기 제어를 안 한다 — 턱 괴기도 피로. 엎드림·턱 괴기,
# 엎드림·꾸벅 졸음처럼 자세가 달라도 피로이면 합쳐진 피로를 기준으로" (fsm.yaml demo_fast.fatigue_group)
def _mix(**p):
    rest = 1.0 - sum(p.values())
    return {"upright": rest, "lean_forward": 0.0, "recline": 0.0, "face_down": 0.0, "chin_rest": 0.0, "drowsy": 0.0,
            "away": 0.0, "misplaced": 0.0, "forward_head": 0.0, **p}


def test_face_down_leaking_into_chin_rest_still_wakes(tmp_path, sent):
    """엎드림 0.97·턱 괴기 0.025 — 엎드림 하나로는 하한 0.99 아래(→ unknown, 피로 0)였지만 합 0.995 로 엎드림 깨우기."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 30)
    cmds, cards = s.hold("face_down", 60, until=lambda c, k: bool(c or k), probs=_mix(face_down=0.97, chin_rest=0.025))
    assert _devices(cmds) == ["desk_lamp", "music"] and cards != ["posture_card"], (cmds, cards)
    assert hub.demo_wake.last["label"] == "face_down"


def test_face_down_then_mostly_chin_rest_keeps_deep_wake(tmp_path, sent):
    """엎드림으로 의심·확정되다 개입 tick 에 턱 괴기가 1위가 돼도(같은 피로 묶음) 안내 카드가 아니라 엎드림 깨우기."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(B)
    s.hold("upright", 30)
    s.hold("face_down", 5)
    cmds, cards = s.hold("chin_rest", 60, until=lambda c, k: bool(c or k), probs=_mix(face_down=0.05, chin_rest=0.945))
    assert "posture_card" not in cards and _devices(cmds) == ["desk_lamp", "music"], (cmds, cards)   # B 깊은 깨우기 = 조명 + (선풍기 대신) 음악


def test_face_down_with_drowsy_counts_as_one_fatigue(tmp_path, sent):
    """엎드림 0.6·꾸벅 졸음 0.395 — 둘 다 하한 아래지만 합 0.995 → 엎드림 깨우기."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 30)
    cmds, _ = s.hold("face_down", 60, until=lambda c, k: bool(c or k), probs=_mix(face_down=0.6, drowsy=0.395))
    assert _devices(cmds) == ["desk_lamp", "music"], cmds


def test_fatigue_group_only_in_fast_mode(tmp_path, sent):
    """normal 로 돌아가면 묶음이 빠진다 — 운영 판정(라벨 하나의 하한)은 그대로."""
    hub, cache, reqs = _hub(tmp_path)
    hub.tick_once(0.0)
    assert hub.ingest_cfg["tof"]["fatigue_group"]["labels"] == ["face_down", "chin_rest", "drowsy"]
    assert hub.demo_speed.snapshot(0.0)["fatigue_group"] == ["face_down", "chin_rest", "drowsy"]
    cache.put("demo_mode", Sample(received=1.0, ts=1.0, seq=None, data={"speed": "normal"}))
    hub.tick_once(5.0)
    assert "fatigue_group" not in hub.ingest_cfg["tof"] and hub.demo_speed.fatigue_labels == ()


def test_heat_and_face_down_drifting_to_chin_rest(tmp_path, sent):
    """11-05 온도 문제 + 피로 묶음 함께: 엎드림으로 졸음 확정, 방이 더움, 원인 판단 tick 부터 턱 괴기가 1위로 흔들림
    → 안내 카드가 아니라 엎드림 깨우기(B: 조명 + 음악 … 2개) + 더위 몫 선풍기."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(B)
    s.temp = 25.0
    s.hold("upright", 30)
    s.temp = 31.0
    while hub.engine.state.value != "FATIGUE" and s.t < 200:
        s.hold("face_down", hub.period)
    assert hub.engine.state.value == "FATIGUE", s.trace[-5:]
    cmds, cards = s.hold("chin_rest", 30, until=lambda c, k: bool(c or k), probs=_mix(face_down=0.05, chin_rest=0.945))
    assert "posture_card" not in cards and _devices(cmds) == ["desk_lamp", "vent_fan"], (cmds, cards)
    assert hub.demo_wake.last["label"] == "face_down" and hub.demo_wake.last["causes"] == ["posture", "environment"]


def test_hot_room_turns_fan_on_regardless_of_fatigue(tmp_path, sent):
    """11-05 사용자 "온도 자체가 피로랑 관계없이 30도 이상이면 선풍기 틀어버리자" (control.yaml hot_fan): 바르게 앉아 집중 중에도
    30 °C 가 되면 선풍기 켜기 한 번. 더운 동안 다시 보내지 않고, 29 °C 아래로 식은 뒤 다시 30 °C 면 또 켠다. 자리를 비우면 안 켠다."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.temp = 27.0
    cmds, _ = s.hold("upright", 30)
    assert cmds == []
    s.temp = 30.2
    cmds, _ = s.hold("upright", 30)
    assert cmds == [("vent_fan", "set_level", 3)], cmds                  # 11-05 사용자 "1단 말고 3단"
    assert hub.engine.state.value.startswith("FOCUS")
    s.temp = 28.5
    s.hold("upright", 10)
    s.temp = 30.5
    cmds, _ = s.hold("upright", 10)
    assert cmds == [("vent_fan", "set_level", 3)], cmds


def test_hot_room_does_not_fight_absent_off(tmp_path, sent):
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.temp = 31.0
    s.hold("upright", 30)
    cmds, _ = s.hold("away", 40)
    assert ("vent_fan", "set_level", 3) not in cmds and ("vent_fan", "set_power", "off") in cmds, cmds


def test_fast_keeps_asleep_without_rest(tmp_path, sent):
    """11-05 사용자 "REST 기능 없애버리자": 빠른 시연에서 계속 엎드려 있어도 REST(강제 휴식·쉬라는 알림)로 가지 않는다.
    깨우기(음악 + 조명) → 안 깨면 다른 원인 재시도(이번 점수로는 쉬기 제안 카드 — 사용자가 고르는 제안)에서 기다린다."""
    hub, cache, reqs = _hub(tmp_path)
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 30)
    n_req = len(reqs)
    cmds, _ = s.hold("face_down", 180)
    states = [st for _, _, st in s.trace]
    kinds = [(r.get("data") or {}).get("kind") for r in reqs[n_req:]]
    assert "REST" not in states and "rest_notice" not in kinds, (states, kinds)
    assert _devices(cmds) == ["desk_lamp", "music"], cmds


def test_absent_off_retries_failed_devices_until_they_reconnect(tmp_path, monkeypatch):
    """11-05 18:50 실기: Pi 5 재부팅 직후 기기가 안 붙어 부재 끄기 3건이 모두 실패했고, 부재가 이어져도 다시 보내지 않았다.
    (control.yaml absent_off.retry_sec·retry_max) 실패한 기기만 retry_sec 마다 다시 보내고, 기기가 붙어 성공하면 멈춘다."""
    sent, offline = [], {"on": True}
    orig = MockPlugAdapter.handle_command

    def flaky(self, payload):
        sent.append(payload)
        if offline["on"] and payload["target_id"] != "music":        # 음악(앱 안)은 되고 블루투스 기기만 끊김
            self.on_result({"command_id": payload["command_id"], "status": "failed", "error_code": "not_connected",
                            "completed_ts_ms": 0})
            return
        return orig(self, payload)

    monkeypatch.setattr(MockPlugAdapter, "handle_command", flaky)
    hub, cache, reqs = _hub(tmp_path)
    cache.put("demo_mode", Sample(received=0.0, ts=0.0, seq=None, data={"speed": "normal"}))
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 30)
    s.hold("away", 60)
    offs = lambda: [(p["target_id"], p["operation"]) for p in sent if p.get("value") in ("off", {"on": False})]   # noqa: E731
    first = offs()
    assert sorted(first[:3]) == [("desk_lamp", "set_power"), ("music", "set_music"), ("vent_fan", "set_power")], first
    assert first[3:] and all(t in ("desk_lamp", "vent_fan") for t, _ in first[3:]), first   # 음악은 성공 — 다시 안 보낸다
    offline["on"] = False                                                # 기기가 다시 붙음
    s.hold("away", 20)
    n = len(offs())
    s.hold("away", 40)
    assert len(offs()) == n, offs()                                      # 성공한 뒤로는 더 안 보낸다


# ── 11-06 사용자 "태환은 처음에는 음악을, 두번째에는 음악과 조명" — 기기 수는 횟수로(escalate_by_count) ─────────────

def test_count_escalation_first_one_then_two_per_person():
    assert REAL["demo_wake"]["escalate_by_count"] is True
    w = DemoWake(REAL["demo_wake"])
    assert w.decide("face_down", A["focus_help"], "pA")["helps"] == ["sound"]            # 첫 번째: 음악만(엎드림이어도)
    assert w.decide("recline", A["focus_help"], "pA")["helps"] == ["sound", "light"]     # 두 번째: 음악+조명(젖힘이어도)
    assert w.decide("drowsy", A["focus_help"], "pA")["helps"] == ["sound", "light"]      # 세 번째도 둘
    assert w.decide("face_down", B["focus_help"], "pB")["helps"] == ["light"]            # 다른 사람은 처음부터
    assert w.decide("forward_head", A["focus_help"], "pA")["kind"] == "notice"           # 안내 카드는 세지 않는다
    assert w.snapshot()["wakes"] == {"pA": 3, "pB": 1}
    w.reset()
    assert w.decide("face_down", A["focus_help"], "pA")["helps"] == ["sound"]            # 빠른 시연을 새로 켜면 처음부터


def test_count_escalation_on_the_hub(tmp_path, sent):
    """태환(A: 음악 › 조명 › 바람)이 두 번 엎드리면 첫 번째는 음악만, 두 번째는 음악+조명."""
    hub, cache, reqs = _hub(tmp_path, wake=REAL["demo_wake"])
    s = Script(hub, cache, reqs, sent)
    s.person(A)
    s.hold("upright", 30)
    cmds, _ = s.hold("face_down", 90, until=lambda c, k: bool(c))
    assert _devices(cmds) == ["music"], cmds
    s.hold("upright", 60)
    cmds, _ = s.hold("face_down", 90, until=lambda c, k: len({t for t, _, _ in c}) >= 2)
    assert _devices(cmds) == ["desk_lamp", "music"], cmds
