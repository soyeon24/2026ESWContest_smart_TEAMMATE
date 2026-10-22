"""각본(yaml) → 구간 목록 + 사람·방·배치 seed + 날씨 + 페르소나.

각본은 "사람이 무엇을 하는가" 의 시간표다. 개입이 오면 `person.py` 가 그 위에 덮어쓰기(override) 구간을 얹는다
(깨어남 → upright, 환기 수락 → 창문 열림 …). 시뮬 프레임은 `tofgen.py` 가 이 시간표를 읽어 만든다.

    scenario:
      name: a1_wake_first
      seed: 7                       # 사람·방·센서 배치·노이즈 seed (고정)
      persona: student              # config/personas.yaml
      start_local: "2026-10-22T14:00:00"
      fsm_config: demo | production | <path>
      weather: {temp_c: 18, humidity: 50, wind_ms: 1.0, condition: clear}   # deskmate/sensor/weather 모사
      reaction_profile: wake_first  # config/reaction.yaml profiles
      timeline:
        - {kind: upright, duration_s: 420, typing: true}
        - {kind: drowsy, duration_s: 1200, typing: false, nods: {interval_s: [4, 12], amp_deg: [30, 50], microsleep_p: 0.4}}
      compress: {upright: 10}       # 구간 종류별 tick 당 프레임 수 (기본 = 10 Hz × 10 s = 100)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(HERE, "config")
SCENARIO_DIR = os.path.join(CONFIG_DIR, "scenarios")

# 시뮬이 아는 구간 종류. tofsim.session.SEGMENTS 의 이름과 같다(여기서 쓰는 것만).
KINDS = ("upright", "lean_forward", "recline", "face_down", "chin_rest", "drowsy", "away",
         "turtle", "writing", "reading", "mouse_work", "armrest", "look_aside", "elbows", "stretch")


def load_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def config_path(name: str) -> str:
    return os.path.join(CONFIG_DIR, name)


@dataclass
class Segment:
    kind: str
    duration_s: float
    typing: bool = False
    nods: dict[str, Any] = field(default_factory=dict)      # drowsy: interval_s [lo,hi], amp_deg [lo,hi], microsleep_p
    fatigue: tuple[float, float] = (0.0, 0.0)               # 키스트로크 피로 지표 램프(구간 시작→끝)
    label: str | None = None                                 # 사람이 읽을 메모
    window_open: bool | None = None                          # 구간 시작에 창문 상태를 바꾼다(None = 그대로)
    frames_per_tick: int | None = None                       # 압축(None = compress 표 또는 100)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Segment":
        kind = str(d["kind"])
        if kind not in KINDS:
            raise ValueError(f"모르는 구간 종류 {kind!r} (가능: {KINDS})")
        fat = d.get("fatigue", 0.0)
        if isinstance(fat, (int, float)):
            fat = (float(fat), float(fat))
        return cls(kind=kind, duration_s=float(d["duration_s"]), typing=bool(d.get("typing", False)),
                   nods=dict(d.get("nods") or {}), fatigue=(float(fat[0]), float(fat[1])),
                   label=d.get("label"), window_open=d.get("window_open"),
                   frames_per_tick=d.get("frames_per_tick"))


@dataclass
class Scenario:
    name: str
    seed: int
    persona: str
    start_ts: float                         # epoch s
    utc_offset_hours: float
    fsm_config: str                         # "demo" | "production" | path
    weather: dict[str, Any] | None
    reaction_profile: str | None
    timeline: list[Segment]
    compress: dict[str, int] = field(default_factory=dict)
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_s(self) -> float:
        return sum(s.duration_s for s in self.timeline)

    def frames_per_tick(self, seg: Segment, default: int) -> int:
        if seg.frames_per_tick:
            return int(seg.frames_per_tick)
        return int(self.compress.get(seg.kind, default))


def parse_scenario(doc: dict[str, Any], *, utc_offset_hours: float = 9.0) -> Scenario:
    sc = doc.get("scenario", doc)
    start_local = str(sc.get("start_local", "2026-10-22T14:00:00"))
    tz = timezone(timedelta(hours=utc_offset_hours))
    start_ts = datetime.fromisoformat(start_local).replace(tzinfo=tz).timestamp()
    timeline = [Segment.from_dict(d) for d in sc.get("timeline") or []]
    if not timeline:
        raise ValueError("timeline 이 비어 있다")
    return Scenario(
        name=str(sc.get("name", "scenario")), seed=int(sc.get("seed", 0)), persona=str(sc.get("persona", "student")),
        start_ts=start_ts, utc_offset_hours=utc_offset_hours, fsm_config=str(sc.get("fsm_config", "demo")),
        weather=sc.get("weather"), reaction_profile=sc.get("reaction_profile"), timeline=timeline,
        compress={str(k): int(v) for k, v in (sc.get("compress") or {}).items()},
        description=str(sc.get("description", "")), extra={k: v for k, v in sc.items() if k not in (
            "name", "seed", "persona", "start_local", "fsm_config", "weather", "reaction_profile", "timeline",
            "compress", "description")},
    )


def load_scenario(path: str, *, utc_offset_hours: float = 9.0, overrides: dict[str, Any] | None = None) -> Scenario:
    if not os.path.exists(path) and os.path.exists(os.path.join(SCENARIO_DIR, path)):
        path = os.path.join(SCENARIO_DIR, path)
    elif not os.path.exists(path) and os.path.exists(os.path.join(SCENARIO_DIR, path + ".yaml")):
        path = os.path.join(SCENARIO_DIR, path + ".yaml")
    doc = load_yaml(path)
    sc = doc.get("scenario", doc)
    for k, v in (overrides or {}).items():
        if v is not None:
            sc[k] = v
    return parse_scenario({"scenario": sc}, utc_offset_hours=utc_offset_hours)


class Timeline:
    """각본 구간 위에 사람 반응의 덮어쓰기 구간을 얹은 '지금 무엇을 하는가'.

    각본 시계는 덮어쓰기와 무관하게 흐른다: 20 분 drowsy 구간의 5 분에 깨어 8 분 upright 로 덮어쓰면 13 분부터 다시
    (구간이 남아 있으니) drowsy 다. 덮어쓰기가 각본 구간보다 길면 다음 각본 구간이 그대로 이어진다.
    """

    def __init__(self, segments: list[Segment]):
        self.segments = list(segments)
        self._starts: list[float] = []
        t = 0.0
        for s in self.segments:
            self._starts.append(t)
            t += s.duration_s
        self.total_s = t
        self._override: tuple[str, float, float, dict[str, Any]] | None = None   # kind, from_s, until_s, params

    def scenario_segment(self, t: float) -> tuple[int, Segment, float]:
        """(index, segment, 구간 안 경과 s). 끝을 넘으면 마지막 구간."""
        idx = len(self.segments) - 1
        for i, start in enumerate(self._starts):
            if t < start + self.segments[i].duration_s:
                idx = i
                break
        return idx, self.segments[idx], max(0.0, t - self._starts[idx])

    def override(self, kind: str, *, now: float, duration_s: float, params: dict[str, Any] | None = None) -> None:
        self._override = (kind, now, now + duration_s, dict(params or {}))

    def clear_override(self) -> None:
        self._override = None

    @property
    def override_active(self) -> tuple[str, float, float, dict[str, Any]] | None:
        return self._override

    def effective(self, t: float) -> tuple[str, Segment, bool, dict[str, Any]]:
        """(지금 구간 종류, 바탕 각본 구간, 덮어쓰기 중인지, 덮어쓰기 파라미터)."""
        _, seg, _ = self.scenario_segment(t)
        ov = self._override
        if ov is not None:
            kind, start, until, params = ov
            if start <= t < until:
                return kind, seg, True, params
            if t >= until:
                self._override = None
        return seg.kind, seg, False, {}
