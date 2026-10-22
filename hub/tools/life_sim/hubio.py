"""hub 하네스 — LiveHub 를 SensorFrame 경로 그대로(SensorCache → build_frame → FSM → 발행) 프로세스 안에서 돌린다.

MQTT 대신 SensorCache 에 표본을 직접 넣고(ingest.mqtt_lines 와 같은 data 모양), 발행물(state/phase·interaction/request·
control/cmd)은 콜백으로 받는다. engine.py·live.py 는 수정하지 않는다.
"""
from __future__ import annotations

import io
import os
from typing import Any, Callable

import numpy as np

from deskmate_hub.control import load_control_config
from deskmate_hub.inference import load_config
from deskmate_hub.ingest import Sample, SensorCache, load_ingest_config
from deskmate_hub.live import LiveHub
from deskmate_hub.personalize import load_personalize_config

HUB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_DIR = os.path.join(HUB_DIR, "deskmate_hub", "config")


def fsm_config_path(name: str) -> str:
    if name == "demo":
        return os.path.join(CONFIG_DIR, "fsm.demo.yaml")
    if name == "production":
        return os.path.join(CONFIG_DIR, "fsm.yaml")
    return name


class HubHarness:
    def __init__(self, *, fsm_config: str, out_dir: str, policy_path: str | None, profile_id: str,
                 publish_control: Callable[[dict[str, Any]], None], seed: int,
                 personalize_enabled: bool = True, quiet: bool = True) -> None:
        self.cache = SensorCache()
        self.states: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.fsm_cfg = load_config(fsm_config_path(fsm_config))
        self.ingest_cfg = load_ingest_config()
        self.control_cfg = dict(load_control_config(), adapter="mqtt", esm_log_path=os.path.join(out_dir, "esm.jsonl"))
        pcfg = dict(load_personalize_config(), enabled=personalize_enabled, record=True, log_dir=out_dir,
                    profile_id=profile_id)
        self.out = io.StringIO() if quiet else None
        if policy_path is None:
            # 계정 B(전역 기본값): 지난 실행이 같은 폴더에 남긴 학습 상태를 이어받지 않는다
            stale = os.path.join(out_dir, "policy.json")
            if os.path.exists(stale):
                os.remove(stale)
        self.hub = LiveHub(
            self.cache, fsm_cfg=self.fsm_cfg, ingest_cfg=self.ingest_cfg,
            publish=self.states.append, publish_request=self.requests.append, publish_control=publish_control,
            control_cfg=self.control_cfg, personalize_cfg=pcfg,
            personalize_log_path=os.path.join(out_dir, "personalize.jsonl"),
            personalize_policy_path=policy_path or os.path.join(out_dir, "policy.json"),
            out=self.out if self.out is not None else __import__("sys").stdout,
        )
        if self.hub.personalize_policy is not None:
            self.hub.personalize_policy.rng = np.random.default_rng(seed + 777)      # Thompson 표본 재현
        if self.hub.personalize_recorder is not None:
            # 시뮬 로그는 실기 로그와 섞이면 안 된다(personalization-log.md: simulated=true, persona)
            self.hub.personalize_recorder.logger.simulated = True
            self.hub.personalize_recorder.logger.persona = profile_id
        self.period = float(self.fsm_cfg["timers"]["score_period_sec"])
        self._seq = 0
        self._last_episode: str | None = None
        self._req_seen = 0

    # ---- 표본 ----
    def put(self, kind: str, data: dict[str, Any], now: float) -> None:
        self._seq += 1
        self.cache.put(kind, Sample(received=now, ts=now, seq=self._seq, data=data))

    def put_feedback(self, payload: dict[str, Any], now: float) -> None:
        self.cache.put_feedback(payload, received=now)

    def put_control_result(self, payload: dict[str, Any]) -> None:
        self.cache.put_control_result(payload)

    # ---- tick ----
    def tick(self, now: float) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
        """(state envelope, 이번 tick 의 새 request 들, 새로 열린 자동 실행 에피소드 view 또는 None)."""
        env = self.hub.tick_once(now)
        new_requests = self.requests[self._req_seen:]
        self._req_seen = len(self.requests)
        view = (env["data"].get("sensor_summary") or {}).get("personalize")
        auto = None
        if view and view.get("episode_id") and view["episode_id"] != self._last_episode and not view.get("closed"):
            self._last_episode = view["episode_id"]
            if view.get("delivered_gate") == "auto":
                auto = view
        return env, new_requests, auto

    @property
    def state(self) -> str:
        return self.hub.engine.state.value

    def close(self, now: float) -> None:
        if self.hub.personalize_recorder is not None:
            self.hub.personalize_recorder.close_all(now)

    def arm_channel(self, arm: str | None) -> str | None:
        pol = self.hub.personalize_policy
        if pol is None or arm is None or arm not in pol.arms:
            return None
        return pol.arms[arm].channel
