"""보드 경로의 라인 프로토콜: C++ 서비스 ↔ Python bridge.

stdin  `MQTT\\t<topic>\\t<payload>` → SensorCache (센서·피드백·제어 결과)
stdout `STATE\\t` / `REQUEST\\t` / `REPORT\\t` / `CMD\\t` + JSON  (C++ 가 토픽으로 발행)
paho 없이 돈다 — 보드 제한 Python 과 같은 조건.
"""
from __future__ import annotations

import json

from deskmate_hub.ingest import SensorCache
from deskmate_hub.ingest.mqtt_lines import MqttLineSource, control_envelope, route_mqtt_message


def test_line_source_routes_sensor_feedback_and_result():
    cache = SensorCache()
    src = MqttLineSource(cache)
    env = json.dumps({"schema_version": "1.0", "ts": 100.0, "node": "esp32-desk1", "seq": 3,
                      "data": {"present": True, "motion_state": "active", "motion_level": 40, "distance_cm": 55,
                               "resp_bpm": None, "resp_valid": False, "heart_bpm": None, "heart_valid": False,
                               "drowsy_state": "AWAKE", "valid": True}})
    assert src.feed_line(f"MQTT\tdeskmate/sensor/mmwave/esp32-desk1\t{env}\n", now=100.5) == "mmwave"
    assert cache.mmwave is not None and cache.mmwave.data["present"] is True and cache.mmwave.seq == 3
    # collector 의 평면 payload
    flat = json.dumps({"ts": 101.0, "kpm": 180, "idle_ratio": 0.1})
    assert src.feed_line(f"MQTT\tdeskmate/sensor/keystroke\t{flat}") == "keystroke"
    assert cache.keystroke is not None and cache.keystroke.data["kpm"] == 180
    # 피드백 (envelope 또는 평면 둘 다)
    assert src.feed_line('MQTT\tdeskmate/feedback/user\t{"data":{"verdict":"accept","request_id":"r1"}}') == "feedback"
    assert cache.pop_feedback() == {"verdict": "accept", "request_id": "r1"}
    assert src.feed_line('MQTT\tdeskmate/control/result\t{"command_id":"c1","status":"succeeded"}') == "control_result"
    assert cache.control_results[0]["command_id"] == "c1"
    assert src.stats.routed == 4 and src.stats.rejected == 0


def test_line_source_rejects_garbage_without_raising():
    cache = SensorCache()
    src = MqttLineSource(cache)
    assert src.feed_line("UART\t{}") is None                        # 다른 프리픽스
    assert src.feed_line("MQTT\tdeskmate/sensor/mmwave/x") is None   # payload 없음
    assert src.feed_line("MQTT\tdeskmate/sensor/mmwave/x\tnot json") is None
    assert src.feed_line("MQTT\tdeskmate/other/topic\t{}") is None  # 계약 밖 토픽
    assert src.feed_line("MQTT\tdeskmate/feedback/user\t[1,2]") is None
    assert src.stats.rejected == 5 and src.stats.routed == 0
    assert route_mqtt_message(cache, "deskmate/feedback/user", b"\xff\xfe") is None


def test_control_envelope_matches_data_spec_shape():
    env = control_envelope({"command_id": "abc", "target_id": "vent_fan", "operation": "set_power", "value": "on"},
                           now=1234.5678)
    assert env["schema_version"] == "1.0" and env["node"] == "hub" and env["ts"] == 1234.568
    assert env["data"]["target_id"] == "vent_fan"


def test_bridge_emits_lines_for_every_hub_output(capsys, monkeypatch):
    """service_bridge 의 배선을 그대로 흉내: LiveHub 콜백 → 라인. CMD 는 envelope 로 감싼다."""
    from deskmate_hub import service_bridge as sb

    store = sb.BridgeStateStore()

    def emit(prefix, envelope):
        store.write_message(prefix + "\t" + json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))

    store.publish({"data": {"fsm_state": "IDLE"}})
    emit("REQUEST", {"data": {"request_id": "q1"}})
    emit("REPORT", {"data": {"session_id": "s1"}})
    emit("CMD", control_envelope({"command_id": "c9"}, now=1.0))
    out = capsys.readouterr().out.splitlines()
    prefixes = [line.split("\t", 1)[0] for line in out]
    assert prefixes == ["STATE", "REQUEST", "REPORT", "CMD"]
    for line in out:
        payload = json.loads(line.split("\t", 1)[1])   # 한 줄 JSON 이어야 C++ 가 그대로 발행할 수 있다
        assert "\n" not in line.split("\t", 1)[1] and isinstance(payload, dict)
    assert json.loads(out[3].split("\t", 1)[1])["data"]["command_id"] == "c9"


def test_fatigue_label_kss_answer_is_cached_by_answer_time():
    cache = SensorCache()
    def label(ts, kss=8, event="kss"):
        return json.dumps({"schema_version": "1.0", "ts": ts, "node": "display-fatigue", "seq": 1,
                           "data": {"event": event, "session_id": "A-1", "profile_id": "A", "ts": ts,
                                    "kss": kss, "prompt_ts": ts - 8, "response_ms": 8000}}).encode()
    topic = "deskmate/fatigue/label"
    assert route_mqtt_message(cache, topic, label(1000.0, 7), now=1000.5) == "fatigue_label"
    assert cache.fatigue_label.data["kss"] == 7.0 and cache.fatigue_label.received == 1000.0
    # 끊긴 동안 쌓였다 다시 온 옛 응답: 더 최신 응답을 덮지 않는다
    assert route_mqtt_message(cache, topic, label(400.0, 9), now=1001.0) == "fatigue_label"
    assert cache.fatigue_label.data["kss"] == 7.0
    # 늦게 도착해도 신선도는 응답 시각 기준
    assert route_mqtt_message(cache, topic, label(1100.0, 8), now=1500.0) == "fatigue_label"
    assert cache.fatigue_label.received == 1100.0
    for bad in (label(1200.0, 0), label(1200.0, True), label(1200.0, 8, "session_end"), b"{not json"):
        assert route_mqtt_message(cache, topic, bad, now=1200.0) is None
    assert cache.fatigue_label.data["kss"] == 8.0
    # 무응답은 따로 둔다(KSS 응답을 지우지 않음), 같은·더 옛 질문은 무시
    assert route_mqtt_message(cache, topic, label(1300.0, None, "prompt_missed"), now=1300.0) == "fatigue_missed"
    assert cache.fatigue_missed.data["prompt_ts"] == 1292.0 and cache.fatigue_label.data["kss"] == 8.0
    assert route_mqtt_message(cache, topic, label(1250.0, None, "prompt_missed"), now=1301.0) == "fatigue_missed"
    assert cache.fatigue_missed.data["prompt_ts"] == 1292.0
