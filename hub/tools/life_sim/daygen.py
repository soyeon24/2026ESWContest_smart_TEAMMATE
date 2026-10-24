"""자유 생활 하루 각본 생성기 — 2단계 피로 모델 학습 데이터용. 시드 하나 = 사람 하나 × 하루.

각본에는 기본 활동(타이핑·마우스·필기·읽기)과 쉬는 시간·식사·외출만 넣는다. 졸음·엎드림·자세 무너짐·키 입력 저하는
넣지 않는다 — 잠재 피로(fatigue.py, reaction.fatigue.enabled)가 작업 시간·CO₂·시각·자세·조명·더위에서 만든다.
CO₂ 는 방 물리만(co2_to 없음), 방은 시드마다 무작위(devices.room.randomize), 날짜는 시드마다 달라
(한 해에 고르게) 계절·바깥 날씨도 따라 바뀐다. 절반은 CO₂ 환기 규칙을 켠다(환기 → 피로 효과를 데이터에 담으려고).

    python -m tools.life_sim daygen --seeds 1-120 --out <폴더>        # day_0001.yaml … 와 index.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import random
from typing import Any

import yaml

PERSONAS = {   # 확률, 활동(종류, 타이핑, 비중)
    "student": (0.40, [("upright", True, 0.55), ("mouse_work", True, 0.25), ("reading", False, 0.10), ("writing", False, 0.10)]),
    "developer": (0.35, [("upright", True, 0.60), ("mouse_work", True, 0.30), ("reading", False, 0.10)]),
    "examinee": (0.25, [("writing", False, 0.50), ("reading", False, 0.35), ("upright", True, 0.15)]),
}
# 무작위 뽑기(v9 각본)는 위 세 유형만 — 뽑기 순서·결과를 그대로 두려고 아래 역할은 persona= 로만 고른다(life_sim learn --roles cycle).
EXTRA_ROLES = {  # 활동, 시작 시각대(없으면 START_BANDS)
    "designer": ([("mouse_work", True, 0.60), ("writing", False, 0.15), ("upright", True, 0.15), ("reading", False, 0.10)], None),
    "writer": ([("upright", True, 0.75), ("reading", False, 0.15), ("writing", False, 0.10)],
               [((20, 0), (23, 0), 0.70), ((14, 0), (17, 0), 0.30)]),          # 밤에 몰아 쓰는 작가·문서 작업
    "researcher": ([("reading", False, 0.50), ("upright", True, 0.30), ("writing", False, 0.20)],
                   [((8, 0), (10, 30), 0.60), ((13, 0), (15, 0), 0.40)]),       # 아침형 논문 읽기·메모
}
ROLES = ("student", "developer", "examinee", "designer", "writer", "researcher")
# 공통모델용 '선호가 별로 없는 사람'(10-24 사용자) — 활동은 고르게, 반응은 기본값(reaction.yaml personas.neutral = {})
EXTRA_ROLES["neutral"] = ([("upright", True, 0.40), ("mouse_work", True, 0.20), ("reading", False, 0.20), ("writing", False, 0.20)],
                          None)
# 시연용 개인화 프로필(10-24 사용자): 책으로 공부하는 수험생(늘 피곤) · 컴퓨터를 주로 쓰는 대학생(휴대폰·딴짓, 자세가 가장 나쁨)
EXTRA_ROLES["book_examinee"] = ([("writing", False, 0.50), ("reading", False, 0.40), ("chin_rest", False, 0.10)],
                                [((8, 0), (10, 0), 0.35), ((13, 0), (15, 0), 0.25), ((19, 0), (22, 0), 0.40)])
# 역할마다 hub 설정(프로필): 책으로 문제 푸는 수험생은 앞으로 숙인 필기 자세가 평소 자세라 자세 증거로 덜 본다(10-24 사용자).
# 키 입력은 PC 를 안 쓰니 비PC 맥락에서 FSM 가중치가 이미 0 이다(fsm.yaml weights npc keystroke 0).
# 10-24 책 공부 ToF 점검(tof-sim_ubai_results_1024/book_study, 시뮬 1회분): 지금 GRU 는 책 읽기를 forward_head 로(91 %), 책 위
# 필기를 chin_rest 로(99 %) 잘못 읽는다 → 책 공부 보강 학습 전까지 수험생 프로필에선 둘의 증거도 낮춘다(진짜 턱괴기는 반응 학습이 다시 올린다).
ROLE_INGEST_SET = {"book_examinee": ["tof.posture_phi.lean_forward=0.0", "tof.posture_delta.lean_forward=0.0",
                                     "tof.posture_phi.forward_head=0.1", "tof.posture_delta.forward_head=0.05",
                                     "tof.posture_phi.chin_rest=0.3", "tof.posture_delta.chin_rest=0.3"]}
EXTRA_ROLES["pc_student"] = ([("upright", True, 0.22), ("turtle", True, 0.20), ("mouse_work", True, 0.15), ("chin_rest", False, 0.10),
                              ("elbows", True, 0.08), ("recline", False, 0.10), ("look_aside", False, 0.08), ("phone_call", False, 0.07)],
                             [((13, 0), (16, 0), 0.40), ((20, 0), (23, 30), 0.60)])
START_BANDS = [((9, 0), (11, 0), 0.25), ((13, 0), (15, 30), 0.40), ((19, 0), (22, 30), 0.35)]
SEASON_OF_MONTH = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
                   6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
OUT_TEMP = {"winter": (-8.0, 6.0), "spring": (8.0, 20.0), "summer": (24.0, 33.0), "autumn": (8.0, 22.0)}
IN_TEMP = {"winter": (19.0, 24.0), "spring": (20.0, 25.0), "summer": (24.0, 29.0), "autumn": (20.0, 25.0)}


def _choice(rnd: random.Random, items: list[tuple]) -> tuple:
    r, acc = rnd.random() * sum(it[-1] for it in items), 0.0
    for it in items:
        acc += it[-1]
        if r <= acc:
            return it
    return items[-1]


def make_day(seed: int, *, desk_hours: tuple[float, float] = (2.0, 3.5), vent_rule_p: float = 0.5,
             persona: str | None = None) -> dict[str, Any]:
    rnd = random.Random(seed * 7919 + 17)
    drawn = _choice(rnd, [(name, p) for name, (p, _) in PERSONAS.items()])[0]
    persona = persona or drawn                        # learn: 같은 사람이면 날마다 같은 유형(뽑기 순서는 그대로)
    acts, bands = (PERSONAS[persona][1], None) if persona in PERSONAS else EXTRA_ROLES[persona]
    (h0, m0), (h1, m1), _ = _choice(rnd, bands or START_BANDS)                # 난수 한 번 — 시작 시각대만 역할마다
    start_min = rnd.randint(h0 * 60 + m0, h1 * 60 + m1)
    # 시드마다 다른 날(97 은 365 와 서로소 → 시드 1~365 가 한 해에 고르게 퍼지고 겹치지 않음)
    date = _dt.date(2026 + seed // 365, 1, 1) + _dt.timedelta(days=(seed * 97) % 365)
    season = SEASON_OF_MONTH[date.month]
    t_out = round(rnd.uniform(*OUT_TEMP[season]), 1)
    condition = _choice(rnd, [("clear", 0.55), ("cloudy", 0.25), ("snow" if season == "winter" else "rain", 0.20)])[0]
    weather = {"temp_c": t_out, "humidity": rnd.randint(30, 90), "wind_ms": round(rnd.uniform(0.0, 7.0), 1),
               "condition": condition, "season": season, "pm25": rnd.choice([8, 12, 18, 25, 35, 55, 80])}
    night = start_min >= 19 * 60
    env = {"co2_ppm": rnd.randint(450, 800), "temp_c": round(rnd.uniform(*IN_TEMP[season]), 1),
           "humidity_pct": rnd.randint(30, 60), "lux": rnd.randint(120, 300) if night else rnd.randint(200, 550),
           "pm25": rnd.randint(5, 40)}
    target_s = 3600.0 * rnd.uniform(*desk_hours)
    segments: list[dict[str, Any]] = [{"kind": "away", "seconds": 10}]
    desk_s, clock, had_meal = 0.0, float(start_min * 60), False
    while desk_s < target_s:
        block = min(target_s - desk_s, 60.0 * rnd.uniform(25, 90))
        left = block
        while left > 30:
            kind, typing, _ = _choice(rnd, acts)
            sub = min(left, 60.0 * rnd.uniform(5, 20))
            segments.append({"kind": kind, "seconds": round(sub), "typing": typing})
            left -= sub
        desk_s += block
        clock += block
        if desk_s >= target_s:
            break
        hour = (clock / 3600.0) % 24
        meal_time = (11.8 <= hour <= 13.2) or (17.8 <= hour <= 19.5)
        r = rnd.random()
        if meal_time and not had_meal:
            away, where, had_meal = 60.0 * rnd.uniform(20, 40), "room", True
        elif r < 0.10:
            away, where = 60.0 * rnd.uniform(15, 45), "out"          # 외출 — 10 분 넘으면 IDLE
        elif r < 0.80:
            away, where = 60.0 * rnd.uniform(3, 12), rnd.choice(["room", "out"])
        else:
            continue                                                 # 쉬지 않고 이어서
        segments.append({"kind": "away", "seconds": round(away), "where": where})
        clock += away
    segments.append({"kind": "away", "seconds": 30, "no_return": True})
    vent = rnd.random() < vent_rule_p
    return {
        "name": f"day_{seed:04d}", "persona": persona, "seed": seed, "date": date.isoformat(),
        "start_clock": f"{start_min // 60:02d}:{start_min % 60:02d}", "l8_params": "v5",
        "env": env, "weather": weather, "segments": segments, "policy": {"profile": "none"},
        "reaction": {"fatigue": {"enabled": True}},
        "devices": {"room": {"randomize": True}, "vent_control": {"enabled": vent}},
        "notes": f"daygen seed {seed}: {persona}, {season}, desk {desk_s / 3600:.1f} h, vent_rule {vent}",
    }


def write_days(seeds: list[int], out_dir: str, **kw: Any) -> list[dict[str, Any]]:
    os.makedirs(out_dir, exist_ok=True)
    index = []
    for s in seeds:
        day = make_day(s, **kw)
        path = os.path.join(out_dir, f"{day['name']}.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# {day['notes']}\n")
            yaml.safe_dump(day, fh, allow_unicode=True, sort_keys=False)
        index.append({"seed": s, "path": path, "persona": day["persona"], "date": day["date"], "start": day["start_clock"],
                      "season": day["weather"]["season"], "vent_rule": day["devices"]["vent_control"]["enabled"],
                      "desk_min": round(sum(g["seconds"] for g in day["segments"] if g["kind"] != "away") / 60),
                      "total_min": round(sum(g["seconds"] for g in day["segments"]) / 60)})
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    return index
