"""사람 반응 모델 — 개입(자동 실행 알림·제안 카드·기기 동작)을 받아 반응(깨어남·자세 복귀·수락/거절/무응답·되돌리기)을
낸다. 확률·지연·재발은 config/reaction.yaml 에서만 온다. 각본의 `reaction_profile` 은 결정적 대본(script)으로
깨우기 계열 개입의 결과를 고정한다(① 첫 개입에 깸 ② 첫 개입 무시 → 격상에 깸 ③ 끝내 안 깸).

반응은 두 갈래로 나간다:
  · hub 로: feedback/user (accept | reject | timeout 은 hub 가 스스로 만료)  → cache.put_feedback
  · 각본으로: Timeline.override(upright …) — 다음 프레임부터 ToF 가 다른 자세를 본다(닫힌 고리)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .scenario import Timeline

SLUMP_KINDS = ("chin_rest", "turtle", "lean_forward", "recline", "face_down", "elbows", "writing")
DEVICE_ARMS = ("light_cool_bright", "light_warm_dim", "air_fan_up", "env_default")
KIND_TO_DEFAULT_ARM = {"break_suggest": "break_short", "posture_suggest": "fsm_default", "env_suggest": "env_default"}


@dataclass
class Intervention:
    t: float
    arm: str                     # personalize arm id 또는 fsm_default / env_default
    channel: str | None
    delivered: str               # auto | suggest
    request_id: str | None = None
    expires_in_s: float | None = None
    cause: str | None = None
    explanation: str | None = None
    while_drowsy: bool = False
    script: str | None = None    # 적용된 대본 항목
    verdict: str | None = None   # accept | reject | timeout | undo | auto_kept
    woke: bool = False
    fixed_posture: bool = False
    effect: str | None = None    # window_open | break | sleep | …


@dataclass
class Person:
    cfg: dict[str, Any]                 # reaction.yaml 전체
    persona: str
    timeline: Timeline
    put_feedback: Callable[[dict[str, Any], float], None]
    rng: np.random.Generator
    profile: str | None = None
    fsm_demo: bool = False
    env: Any = None                     # Environment (창문)
    devices: Any = None                 # DeviceRack (각성 가산·소음)
    utc_offset_hours: float = 9.0
    bedtime_hour: float = 23.5
    start_ts: float = 0.0
    interventions: list[Intervention] = field(default_factory=list)
    _pending: list[tuple[float, Callable[[float], None], str]] = field(default_factory=list)
    _script: list[str] = field(default_factory=list)
    _script_i: int = 0
    drowsy_count: list[float] = field(default_factory=list)
    session_ended: bool = False
    log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        prof = (self.cfg.get("profiles") or {}).get(self.profile or "", {})
        self._script = list(prof.get("script") or [])
        self._script_all = str(prof.get("scope", "drowsy")) == "all"     # 대본을 졸음 중 개입에만(기본) / 모든 개입에
        self._relapse = prof.get("relapse_min") or self.cfg["defaults"]["relapse_min"]

    # ---- 설정 조회 ----
    def _arm_cfg(self, arm: str) -> dict[str, float]:
        d = self.cfg["defaults"]
        base = dict(d["arms"].get(arm) or d["arms"]["fsm_default"])
        base.update((self.cfg.get("personas") or {}).get(self.persona, {}).get(arm, {}))
        return base

    def _u(self, pair: Any) -> float:
        lo, hi = pair
        return float(self.rng.uniform(float(lo), float(hi)))

    def _now_sc(self, now: float) -> float:
        return now - self.start_ts

    def is_drowsy(self, now: float) -> bool:
        kind, _, override, _ = self.timeline.effective(self._now_sc(now))
        return kind == "drowsy" and not override

    def in_slump(self, now: float) -> bool:
        kind, _, _, _ = self.timeline.effective(self._now_sc(now))
        return kind in SLUMP_KINDS

    def after_bedtime(self, now: float) -> bool:
        hour = ((now + self.utc_offset_hours * 3600.0) % 86400.0) / 3600.0
        bed = self.bedtime_hour % 24.0
        if self.bedtime_hour >= 24.0:        # 새벽 취침(25.5 = 01:30): 그 시각 ~ 아침 6시 사이
            return bed <= hour < 6.0
        return hour >= bed or hour < 6.0

    def _wake_prob(self, arm: str, now: float) -> float:
        a = self.cfg["defaults"]["arousal"]
        p = float(self._arm_cfg(arm)["wake_p"])
        if self.devices is not None:
            p += float(self.devices.arousal_bonus())
        if self.env is not None and self.env.state.co2_ppm >= float(a["co2_high_ppm"]):
            p += float(a["co2_high_penalty"])
        if self.after_bedtime(now):
            p += float(a["after_bedtime_penalty"])
        recent = [t for t in self.drowsy_count if now - t <= 1800.0]
        p += float(a["drowsy_count_penalty_each"]) * len(recent)
        return max(0.0, min(1.0, p))

    def _next_script(self) -> str | None:
        if self._script_i < len(self._script):
            s = self._script[self._script_i]
            self._script_i += 1
            return s
        return None

    # ---- 입력: hub 가 낸 것 ----
    def on_request(self, now: float, request: dict[str, Any]) -> Intervention:
        d = request["data"]
        arm = d.get("arm") or KIND_TO_DEFAULT_ARM.get(str(d.get("kind")), "fsm_default")
        iv = Intervention(t=now, arm=str(arm), channel=None, delivered="suggest", request_id=d["request_id"],
                          expires_in_s=d.get("expires_in_s"), cause=d.get("cause"), explanation=d.get("explanation"),
                          while_drowsy=self.is_drowsy(now))
        self.interventions.append(iv)
        acfg = self._arm_cfg(iv.arm)
        d0 = self.cfg["defaults"]
        if iv.while_drowsy or self._script_all:
            iv.script = self._next_script()
        if iv.script == "wake":
            verdict = "accept"
        elif iv.script == "ignore":
            verdict = "timeout"
        elif iv.script == "reject":
            verdict = "reject"
        else:
            if self.rng.random() < float(d0["timeout_p"]):
                verdict = "timeout"
            else:
                p = float(acfg["accept_p"])
                if self.devices is not None and iv.arm in ("air_fan_up", "env_default"):
                    p -= float(self.devices.annoyance())
                if iv.arm in ("sleep_suggest",) and not self.after_bedtime(now):
                    p *= 0.3
                verdict = "accept" if self.rng.random() < p else "reject"
        iv.verdict = verdict
        if verdict == "timeout":
            self._note(now, iv, "card ignored (timeout)")
            return iv
        delay = self._u(d0["respond_delay_s"])
        if iv.expires_in_s:
            delay = min(delay, 0.8 * float(iv.expires_in_s))
        rid = iv.request_id

        def respond(t: float, iv=iv, verdict=verdict, rid=rid, delay=delay) -> None:
            self.put_feedback({"verdict": verdict, "request_id": rid, "response_ms": int(delay * 1000)}, t)
            if verdict == "accept":
                self._apply_effect(t, iv, accepted=True)
            self._note(t, iv, f"card {verdict}")

        self._pending.append((now + delay, respond, f"respond:{verdict}"))
        return iv

    def on_auto(self, now: float, arm: str | None, channel: str | None, *, cause: str | None,
                explanation: str | None) -> Intervention:
        arm = arm or ("env_default" if cause == "environment" else "fsm_default")
        iv = Intervention(t=now, arm=str(arm), channel=channel, delivered="auto", cause=cause, explanation=explanation,
                          while_drowsy=self.is_drowsy(now))
        self.interventions.append(iv)
        acfg = self._arm_cfg(iv.arm)
        d0 = self.cfg["defaults"]
        if iv.while_drowsy or self._script_all:
            iv.script = self._next_script()
        undo = False
        if iv.script == "reject":
            undo = iv.arm in DEVICE_ARMS
        elif iv.script is None:
            p_undo = float(acfg["undo_p"]) + (float(self.devices.annoyance()) if self.devices is not None else 0.0)
            undo = iv.arm in DEVICE_ARMS and self.rng.random() < p_undo
        if undo:
            iv.verdict = "undo"
            delay = min(self._u(d0["undo_delay_s"]), 50.0)

            def undo_it(t: float, iv=iv) -> None:
                self.put_feedback({"verdict": "reject"}, t)      # 자동 실행 되돌리기 = request 없는 reject
                self._note(t, iv, "auto undone")

            self._pending.append((now + delay, undo_it, "undo"))
            return iv
        iv.verdict = "auto_kept"
        if iv.script == "ignore":
            self._note(now, iv, "auto alert ignored")       # 대본: 알림을 못 본 척한다(효과 없음)
            return iv
        self._apply_effect(now, iv, accepted=True)
        return iv

    # ---- 효과 ----
    def _apply_effect(self, now: float, iv: Intervention, *, accepted: bool) -> None:
        d0 = self.cfg["defaults"]
        acfg = self._arm_cfg(iv.arm)
        drowsy = self.is_drowsy(now)
        if iv.arm == "sleep_suggest":
            iv.effect = "sleep"
            self.session_ended = True
            self.timeline.override("away", now=self._now_sc(now) + self._u(d0["wake_delay_s"]), duration_s=10 * 3600.0,
                                   params={"typing": False})
            self._note(now, iv, "sleep accepted → leaves")
            return
        if iv.arm == "ventilate_suggest" and self.env is not None:
            minutes = float(d0.get("ventilate_open_min_default", 15))
            if self.env.open_window(now, minutes):
                iv.effect = f"window_open:{minutes:.0f}min"
            else:
                iv.effect = "window_refused:rain"
        if iv.arm in ("break_short", "break_long"):
            minutes = float(d0.get("break_short_min", 4) if iv.arm == "break_short" else d0.get("break_long_min", 12))
            iv.effect = f"break:{minutes:.0f}min"
            if drowsy:
                minutes = max(minutes, self._u(self._relapse))    # 졸다가 쉬면 깨어 있는 시간은 재발 분포를 따른다
            # 책상에서 쉰다(바른 자세·타이핑 없음). 자리를 비우면 absent_idle_sec 뒤 IDLE 이라 세션이 끊긴다.
            self.timeline.override("upright", now=self._now_sc(now) + self._u(d0["wake_delay_s"]),
                                   duration_s=minutes * 60.0,
                                   params={"typing": False, "transition_s": d0["wake_transition_s"],
                                           "fatigue_scale": float(d0.get("break_refresh_scale", 0.1))})
            iv.woke = drowsy
            iv.fixed_posture = True
            if drowsy:
                self.drowsy_count.append(now)
            return
        if drowsy:
            if iv.script == "wake" or (iv.script is None and self.rng.random() < self._wake_prob(iv.arm, now)):
                iv.woke = True
                self.drowsy_count.append(now)
                self.timeline.override("upright", now=self._now_sc(now) + self._u(d0["wake_delay_s"]),
                                       duration_s=self._u(self._relapse) * 60.0,
                                       params={"typing": True, "transition_s": d0["wake_transition_s"],
                                               "fatigue_scale": float(d0.get("wake_refresh_scale", 0.2))})
                self._note(now, iv, "wakes up → upright")
            else:
                self._note(now, iv, "stays drowsy")
        elif self.in_slump(now):
            if self.rng.random() < float(acfg["fix_p"]):
                iv.fixed_posture = True
                _, seg, _, _ = self.timeline.effective(self._now_sc(now))
                self.timeline.override("upright", now=self._now_sc(now) + self._u(d0["wake_delay_s"]),
                                       duration_s=self._u(d0["hold_min"]) * 60.0,
                                       params={"typing": seg.typing, "transition_s": d0["wake_transition_s"]})
                self._note(now, iv, "fixes posture → upright")
            else:
                self._note(now, iv, "keeps posture")

    # ---- tick ----
    def step(self, now: float) -> None:
        due = [(t, fn, tag) for t, fn, tag in self._pending if t <= now]
        self._pending = [(t, fn, tag) for t, fn, tag in self._pending if t > now]
        for t, fn, _ in sorted(due, key=lambda x: x[0]):
            fn(t)          # 실제 응답 시각으로(hub 는 received 시각으로 카드 만료를 판정한다)

    def _note(self, now: float, iv: Intervention, text: str) -> None:
        self.log.append({"t": now, "arm": iv.arm, "delivered": iv.delivered, "script": iv.script, "note": text})

    def summary(self) -> dict[str, Any]:
        ivs = self.interventions
        return {
            "interventions": len(ivs),
            "auto": sum(1 for i in ivs if i.delivered == "auto"),
            "suggest": sum(1 for i in ivs if i.delivered == "suggest"),
            "accepted": sum(1 for i in ivs if i.verdict == "accept"),
            "rejected": sum(1 for i in ivs if i.verdict == "reject"),
            "timeout": sum(1 for i in ivs if i.verdict == "timeout"),
            "undone": sum(1 for i in ivs if i.verdict == "undo"),
            "woke": sum(1 for i in ivs if i.woke),
            "while_drowsy": sum(1 for i in ivs if i.while_drowsy),
            "posture_fixed": sum(1 for i in ivs if i.fixed_posture),
            "arms": {a: sum(1 for i in ivs if i.arm == a) for a in sorted({i.arm for i in ivs})},
            "effects": [i.effect for i in ivs if i.effect],
            "session_ended_by_sleep": self.session_ended,
        }
