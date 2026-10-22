"""방 환경 모델(CO₂·온도·습도·조도·PM2.5) + 날씨 + 주변기기 효과. 계수는 config/devices.yaml 에서만 온다.

tick(10 s)마다 한 번 적분한다. hub 에 주는 `env` 표본(data-spec env 계약: co2_ppm·temp_c·humidity_pct·lux + *_valid)과
`deskmate/sensor/weather` 표본을 만든다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

SEASON_BY_MONTH = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
                   6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}


@dataclass
class EnvState:
    co2_ppm: float
    temp_c: float
    humidity_pct: float
    lux: float
    pm25: float
    window_open: bool = False
    window_open_until: float | None = None
    felt_temp_c: float = 0.0
    history: list = field(default_factory=list)


class Environment:
    def __init__(self, dev_cfg: dict[str, Any], persona: dict[str, Any], weather: dict[str, Any] | None,
                 *, month: int, seed: int):
        self.cfg = dev_cfg
        self.persona = persona
        self.rng = np.random.default_rng(seed + 100)
        e = dev_cfg["environment"]
        self.weather = dict(weather or {})
        self.weather.setdefault("season", SEASON_BY_MONTH[month])
        self.weather.setdefault("condition", "clear")
        self.weather.setdefault("wind_ms", 0.0)
        self.weather.setdefault("temp_c", persona["temp_c"])
        self.weather.setdefault("humidity", persona["humidity_pct"])
        self.state = EnvState(co2_ppm=float(e["co2_start_ppm"]), temp_c=float(persona["temp_c"]),
                              humidity_pct=float(persona["humidity_pct"]), lux=float(persona["lux_ambient"]),
                              pm25=float(e["pm25_start"]))
        self.lamp_brightness: int | None = None     # None = 램프 꺼짐(주변광만)
        self.fan_level = 0

    # ---- 창문 ----
    def open_window(self, now: float, minutes: float) -> bool:
        w = self.cfg["window"]
        if w.get("rain_blocks_open") and str(self.weather.get("condition")) in ("rain", "snow"):
            return False
        self.state.window_open = True
        self.state.window_open_until = now + minutes * 60.0
        return True

    def close_window(self) -> None:
        self.state.window_open = False
        self.state.window_open_until = None

    # ---- 적분 ----
    def step(self, now: float, dt_s: float, *, present: bool) -> None:
        s, e, w = self.state, self.cfg["environment"], self.cfg["window"]
        dt_min = dt_s / 60.0
        if s.window_open and s.window_open_until is not None and now >= s.window_open_until:
            self.close_window()
        windy = float(self.weather.get("wind_ms") or 0.0) >= 4.0
        vent = float(w["vent_per_min_open"]) * (float(w["windy_multiplier"]) if windy else 1.0) if s.window_open \
            else float(w["leak_per_min_closed"])
        gen = float(self.persona["co2_gen_ppm_per_min"]) if present else 0.0
        outdoor = float(e["co2_outdoor_ppm"])
        s.co2_ppm += dt_min * (gen - vent * (s.co2_ppm - outdoor))
        s.co2_ppm = max(outdoor, s.co2_ppm)
        # 온도: 창문 열면 바깥 쪽으로, 닫으면 페르소나 기본값으로
        if s.window_open:
            s.temp_c += dt_min * float(e["temp_outdoor_pull_per_min_open"]) * (float(self.weather["temp_c"]) - s.temp_c)
            s.pm25 += dt_min * float(e["pm25_rise_per_min_open"]) * (1.0 if self.weather.get("pm_bad") else 0.2)
        else:
            s.temp_c += dt_min * float(e["temp_relax_per_min"]) * (float(self.persona["temp_c"]) - s.temp_c)
        # 공기청정기(명령 경로가 hub 에 없어 지금은 늘 꺼짐) — 자리만 둔다
        s.felt_temp_c = s.temp_c - self.fan_level * float(self.cfg["fan"]["felt_temp_drop_c_per_level"])
        # 조도: 주변광 + 램프
        lamp = 0.0 if self.lamp_brightness is None else self.lamp_brightness * float(self.cfg["lamp"]["lux_per_brightness"])
        s.lux = float(self.persona["lux_ambient"]) + lamp

    # ---- hub 표본 ----
    def env_sample(self) -> dict[str, Any]:
        s, e = self.state, self.cfg["environment"]
        return {
            "co2_ppm": round(s.co2_ppm + float(self.rng.normal(0, e["co2_noise"]))), "co2_valid": True,
            "temp_c": round(s.temp_c + float(self.rng.normal(0, 0.1)), 2), "temp_valid": True,
            "humidity_pct": int(round(s.humidity_pct + float(self.rng.normal(0, 1.0)))), "humidity_valid": True,
            "lux": max(0, round(s.lux + float(self.rng.normal(0, e["lux_noise"])))), "lux_valid": True,
        }

    def weather_sample(self, now: float) -> dict[str, Any]:
        """deskmate/sensor/weather data 7 필드(2026-10-21 계약) + 선택 pm_bad."""
        w = self.weather
        out = {"temp_c": float(w["temp_c"]), "humidity": int(w["humidity"]), "wind_ms": float(w["wind_ms"]),
               "condition": str(w["condition"]), "season": str(w["season"]), "fetched_at": int(now), "source": "sim"}
        if w.get("pm_bad"):
            out["pm_bad"] = True
        return out

    def snapshot(self) -> dict[str, Any]:
        s = self.state
        return {"co2_ppm": round(s.co2_ppm), "temp_c": round(s.temp_c, 2), "felt_temp_c": round(s.felt_temp_c, 2),
                "lux": round(s.lux), "pm25": round(s.pm25, 1), "window_open": s.window_open,
                "lamp_brightness": self.lamp_brightness, "fan_level": self.fan_level}
