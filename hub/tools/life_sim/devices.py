"""주변기기 mock — hub 의 실제 명령 계약을 받고, 방 환경·사람 반응에 영향을 준다. 계수는 config/devices.yaml.

    hub ControlDispatcher ──publish_cmd(payload)──▶ DeviceRack.handle_command ──▶ cache.put_control_result(result)
    hub state/phase(sensor_summary.personalize) ─▶ DeviceRack.on_state   (자동 실행된 화면·음성·소리 arm → 스피커/화면)
    hub interaction/request ───────────────────▶ DeviceRack.on_request (제안 카드 → person 에 전달)

기기별 실물·경로는 devices.yaml 머리말에 적었다. 시뮬에서 명령은 즉시(또는 result_delay_s 뒤) 성공한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .environment import Environment


@dataclass
class DeviceEvent:
    t: float
    device: str
    what: str                 # cmd | undo | alert | card
    detail: dict[str, Any] = field(default_factory=dict)


class DeviceRack:
    def __init__(self, cfg: dict[str, Any], env: Environment, put_result: Callable[[dict[str, Any]], None]):
        self.cfg = cfg
        self.env = env
        self.put_result = put_result
        self.fan_level = 0
        self.lamp: dict[str, Any] = {"power": False, "brightness": None}
        self.purifier_mode = "off"
        self.speaker_last: dict[str, Any] | None = None
        self.display_card: dict[str, Any] | None = None
        self.events: list[DeviceEvent] = []
        self._pending: list[tuple[float, dict[str, Any]]] = []
        self.now = 0.0
        self.counts = {"cmd": 0, "undo": 0, "alert": 0, "card": 0}

    # ---- hub control/cmd ----
    def handle_command(self, payload: dict[str, Any]) -> None:
        target, op, value = payload["target_id"], payload["operation"], payload.get("value")
        kind = "undo" if payload.get("gate") == "undo" else "cmd"
        self.counts[kind] += 1
        delay = 0.0
        if target == "vent_fan":
            if op == "set_power":
                self.fan_level = int(self.cfg["fan"]["on_level"]) if str(value).lower() == "on" else 0
            elif op == "set_level":
                self.fan_level = max(0, min(3, int(value)))
            self.env.fan_level = self.fan_level
            delay = float(self.cfg["fan"].get("result_delay_s", 0))
        elif target == "desk_lamp":
            if op == "set_brightness":
                self.lamp = {"power": int(value) > 0, "brightness": int(value)}
                self.env.lamp_brightness = int(value) if int(value) > 0 else None
            elif op == "set_power":
                self.lamp["power"] = str(value).lower() == "on"
                self.env.lamp_brightness = (self.lamp.get("brightness") or self.cfg["lamp"]["default_brightness"]) \
                    if self.lamp["power"] else None
            delay = float(self.cfg["lamp"].get("result_delay_s", 0))
        elif target == "air_purifier":
            self.purifier_mode = str(value)
        self.events.append(DeviceEvent(self.now, target, kind, {"operation": op, "value": value,
                                                                 "origin_state": payload.get("origin_state"),
                                                                 "cause": payload.get("cause"), "gate": payload.get("gate")}))
        result = {"command_id": payload["command_id"], "status": "succeeded", "actual_value": value,
                  "completed_ts_ms": int((self.now + delay) * 1000)}
        self._pending.append((self.now + delay, result))

    def tick(self, now: float) -> None:
        self.now = now
        due = [r for t, r in self._pending if t <= now]
        self._pending = [(t, r) for t, r in self._pending if t > now]
        for r in due:
            self.put_result(r)

    # ---- state/phase 의 개인화 요약: 자동 실행된 비기기 arm 은 Pi 5 앱이 음성·소리·카드로 낸다 ----
    def on_auto_alert(self, now: float, arm: str | None, channel: str | None, explanation: str | None) -> None:
        self.counts["alert"] += 1
        if channel in ("voice", "sound"):
            self.speaker_last = {"t": now, "arm": arm, "channel": channel}
            self.events.append(DeviceEvent(now, "speaker", "alert", {"arm": arm, "channel": channel, "text": explanation}))
        else:
            self.display_card = {"t": now, "arm": arm, "kind": "auto_notice", "explanation": explanation}
            self.events.append(DeviceEvent(now, "display", "alert", {"arm": arm, "channel": channel, "text": explanation}))

    def on_request(self, now: float, request: dict[str, Any]) -> None:
        d = request["data"]
        self.counts["card"] += 1
        self.display_card = {"t": now, "request_id": d["request_id"], "kind": d["kind"], "arm": d.get("arm"),
                             "explanation": d.get("explanation"), "expires_in_s": d.get("expires_in_s")}
        self.events.append(DeviceEvent(now, "display", "card", {"request_id": d["request_id"], "kind": d["kind"],
                                                                "arm": d.get("arm"), "text": d.get("explanation")}))

    def snapshot(self) -> dict[str, Any]:
        return {"fan_level": self.fan_level, "lamp": dict(self.lamp), "purifier": self.purifier_mode,
                "window_open": self.env.state.window_open}

    # ---- 사람 반응 계수(깨우기 확률 가산) ----
    def arousal_bonus(self) -> float:
        bonus = self.fan_level * float(self.cfg["fan"]["arousal_per_level"])
        b = self.lamp.get("brightness")
        if self.lamp.get("power") and b is not None:
            if b >= int(self.cfg["lamp"]["cool_bright_threshold"]):
                bonus += float(self.cfg["lamp"]["arousal_cool_bright"])
            elif b <= 60:
                bonus -= float(self.cfg["lamp"]["relax_warm_dim"])
        return bonus

    def annoyance(self) -> float:
        return self.fan_level * float(self.cfg["fan"]["noise_annoy_per_level"])
