"""각본을 따라가는 가상 ToF 프레임 생성기 — 두 센서(VL53L8CX 8×8, 10 Hz), 사람·방·배치 seed 고정.

tof_sim_v5(`tofsim`)의 helper(_target_pose·_plan_nods·_lerp_pose·_nod_offset·Sensor·MjDesk·sensor_frame)를 재사용하고,
`generate_frames()` 의 무작위 timeline 대신 `scenario.Timeline` 이 주는 "지금 구간" 을 프레임 단위로 따른다. 개입이 오면
Timeline 의 덮어쓰기(upright 등)로 다음 프레임부터 자세가 바뀐다 — 닫힌 고리의 "사람 쪽" 끝이다.

tofsim 은 이 저장소 밖(dataset/tof_sim_v5 워크트리 또는 UBAI ~/tof-sim-v5-lifesim)에 있을 수 있어 `TOFSIM_DIR` 환경변수
또는 `--tofsim-dir` 로 찾는다. 센서 배치는 그 session.py 의 DEVICE_SENSORS(CAD 정본 cad04: 좌 (+0.0524, 0.1299) m·위 20°·요 8°,
우 대칭)를 그대로 쓴다. 센서 모델 보정값은 `TOFSIM_L8_PARAMS`(apply_l8_patch.py) 가 걸려 있으면 그것이 적용된다 —
어느 것을 썼는지는 `info()` 에 남긴다.
"""
from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .scenario import Scenario, Segment, Timeline

FLAG_TRANSITION = 1
FLAG_NOD = 2


def find_tofsim_dir(explicit: str | None = None) -> str | None:
    """tofsim 패키지가 든 폴더. 인자 → TOFSIM_DIR → 이 저장소 dataset/tof_sim_v5 → 홈의 tof-sim-v5-* 순."""
    cands = [explicit, os.environ.get("TOFSIM_DIR")]
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    cands.append(os.path.join(repo, "dataset", "tof_sim_v5"))
    home = os.path.expanduser("~")
    for name in ("tof-sim-v5-lifesim", "tof-sim-v5-cad04"):
        cands.append(os.path.join(home, name))
        cands.append(os.path.join(home, name, "dataset", "tof_sim_v5"))
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "tofsim")):
            return os.path.abspath(c)
    return None


def import_tofsim(explicit: str | None = None):
    d = find_tofsim_dir(explicit)
    if d is None:
        raise ImportError("tofsim 을 못 찾았다 — --tofsim-dir 또는 TOFSIM_DIR 로 dataset/tof_sim_v5 를 가리켜라")
    if d not in sys.path:
        sys.path.insert(0, d)
    session = importlib.import_module("tofsim.session")
    sensor = importlib.import_module("tofsim.sensor")
    body = importlib.import_module("tofsim.body")
    return d, session, sensor, body


@dataclass
class FrameOut:
    t: float                               # 각본 시각(초, 0 = 각본 시작)
    label: str                             # 정답 라벨(tofsim LABELS 이름)
    flags: int
    kind: str                              # 지금 구간 종류(덮어쓰기 반영)
    override: bool
    grids: dict[int, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)   # 센서 index → (dist mm, status)


class TofGenerator:
    """각본 → 프레임. `next_frame(t)` 를 10 Hz 로 부른다(압축 구간은 tick 당 몇 프레임만)."""

    def __init__(self, scenario: Scenario, timeline: Timeline, *, backend: str = "numpy",
                 tofsim_dir: str | None = None, azimuth_deg: float = 0.0, sensors: tuple[int, ...] = (0, 1)):
        self.scenario = scenario
        self.timeline = timeline
        self.backend = backend
        self.tofsim_dir, self.S, self.SE, self.B = import_tofsim(tofsim_dir)
        self.rng = np.random.default_rng(scenario.seed)
        self.pose_rng = np.random.default_rng(scenario.seed + 1)
        S = self.S
        # 배치: arc 의 정면(azimuth 0) 장치, 두 센서 모두. rich 장면은 numpy 백엔드가 못 그리므로 plain.
        self.cfg = S.sample_session(self.rng, "vl53l8cx", azimuth_deg=azimuth_deg, sensor_index=sensors[0],
                                    placement="arc", clutter_max=0, scene="plain")
        self.cfg.fps = 10.0
        arc = {(az, si): pose for az, si, pose in self.cfg.meta["arc"]}
        self.sensor_poses = {si: arc[(int(azimuth_deg), si)] for si in sensors}
        self.sensors = {si: self.SE.Sensor(self.cfg.spec, self.cfg.model, np.random.default_rng(scenario.seed + 10 + si))
                        for si in sensors}
        self.desk = None
        self._mj_frames: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        if backend == "mujoco":
            mj = importlib.import_module("tofsim.mj_scene")
            self.desk = mj.MjDesk(self.cfg.room, self.cfg.person)
            self._mj_frames = {si: mj.sensor_frame(p) for si, p in self.sensor_poses.items()}
        elif backend != "numpy":
            raise ValueError(f"backend 는 numpy | mujoco: {backend!r}")
        self.limits = self.cfg.meta.get("limits")
        # 자세 상태
        self._cur_kind: str | None = None
        self._target = None            # Pose
        self._from = None              # Pose | None (away 에서 돌아오면 None)
        self._seg_start = 0.0
        self._trans = 0.0
        self._nods: list = []
        self._nod_side = 0.0
        self._first_nod_t = None
        self._breath_f = float(self.rng.uniform(0.2, 0.33))
        self._sway_f = float(self.rng.uniform(0.03, 0.08))
        self._prev_pose = None
        self.frames = 0

    # ---------------------------------------------------------------- 정보
    def info(self) -> dict[str, Any]:
        p = self.cfg.person
        return {
            "tofsim_dir": self.tofsim_dir, "backend": self.backend, "seed": self.scenario.seed,
            "sensor_params_env": os.environ.get("TOFSIM_L8_PARAMS"),
            "device_sensors": [list(map(float, c)) + [float(up), float(yaw)] for c, up, yaw in self.S.DEVICE_SENSORS],
            "sensor_poses": {si: {"position": [float(v) for v in pose.position], "pitch_down_deg": float(pose.pitch_down_deg),
                                  "yaw_deg": float(pose.yaw_deg)} for si, pose in self.sensor_poses.items()},
            "person": {"scale": p.scale, "hip_z": p.hip_z, "seat_height": p.seat_height, "x_offset": p.x_offset,
                       "smplx": bool(p.smplx)},
            "room": {"desk_height": self.cfg.room.desk_height, "desk_depth": self.cfg.room.desk_depth},
            "sensor_model": {k: float(v) for k, v in self.cfg.model.__dict__.items()},
            "fps": self.cfg.fps,
        }

    # ---------------------------------------------------------------- 자세 계획
    def _enter(self, kind: str, t: float, params: dict[str, Any], seg: Segment) -> None:
        S = self.S
        self._cur_kind = kind
        self._seg_start = t
        self._from = self._prev_pose
        self._trans = float(self.pose_rng.uniform(*params.get("transition_s", (0.5, 2.0)))) if self._prev_pose is not None else 0.0
        self._nods, self._nod_side, self._first_nod_t = [], 0.0, None
        if kind == "away":
            self._target = None
            return
        self._target = S._target_pose(kind, self.pose_rng, self.limits)
        if kind == "drowsy":
            nods_cfg = dict(seg.nods or {})
            nods_cfg.update(params.get("nods") or {})
            self._nods = self._plan_nods(nods_cfg)
            if self._nods:
                self._first_nod_t = self._nods[0][0]
            self._nod_side = 0.0 if self.pose_rng.random() < float(nods_cfg.get("side_p_forward", 0.65)) else (
                1.0 if self.pose_rng.random() < 0.5 else -1.0)

    def _plan_nods(self, cfg: dict[str, Any]) -> list:
        """tofsim._plan_nods 와 같은 모양(start, fall, pause, recover, amp, hold)이되 각본 값을 쓴다."""
        r = self.pose_rng
        lo, hi = cfg.get("interval_s", (3.0, 15.0))
        alo, ahi = cfg.get("amp_deg", (25.0, 55.0))
        micro_p = float(cfg.get("microsleep_p", 0.45))
        hold_lo, hold_hi = cfg.get("hold_s", (4.0, 20.0))
        first = cfg.get("first_s", (1.0, 8.0))
        horizon = float(cfg.get("horizon_s", 3600.0))
        nods, t = [], float(r.uniform(*first))
        while t < horizon:
            fall = float(r.uniform(0.5, 1.5))
            pause = float(r.uniform(0.0, 0.4))
            recover = float(r.uniform(0.3, 1.0))
            amp = float(np.radians(r.uniform(alo, ahi)))
            hold = float(r.uniform(hold_lo, hold_hi)) if r.random() < micro_p else 0.0
            nods.append((t, fall, pause, recover, amp, hold))
            t += fall + pause + hold + recover + float(r.uniform(lo, hi))
        return nods

    # ---------------------------------------------------------------- 프레임
    def next_frame(self, t: float) -> FrameOut:
        S, B = self.S, self.B
        kind, seg, override, params = self.timeline.effective(t)
        if kind != self._cur_kind or (override and params.get("_restart") and params.pop("_restart", None)):
            self._enter(kind, t, params, seg)
        ts = t - self._seg_start
        flags = 0
        label = S.SEGMENT_LABEL.get(kind, kind)
        if kind == "drowsy" and (self._first_nod_t is None or ts < self._first_nod_t):
            label = "upright"            # 첫 끄덕임 전의 조는 사람은 센서에는 바른 자세다(tofsim 과 같은 규칙)
        if kind == "away":
            pose = None
            self._prev_pose = None
        else:
            w = 1.0 if self._trans <= 0 else min(1.0, ts / self._trans)
            if w < 1.0:
                flags |= FLAG_TRANSITION
            start = self._from if self._from is not None else self._target
            pose = S._lerp_pose(start, self._target, w)
            if self._from is None and ts < 2.0:        # 자리에 앉는 중: 앞으로 걸터앉았다가 자리 잡는다
                k = 1.0 - ts / 2.0
                pose.hip_shift = self._target.hip_shift + 0.08 * k
                pose.trunk_pitch += np.radians(12.0) * k
                flags |= FLAG_TRANSITION
            tg = t
            pose.breath = 0.004 * np.sin(2 * np.pi * self._breath_f * tg)
            pose.trunk_roll += np.radians(1.5) * np.sin(2 * np.pi * self._sway_f * tg)
            pose.head_yaw += np.radians(self.pose_rng.normal(0, 0.6))
            if pose.arms == "typing":
                pose.arm_jitter = 0.01 * np.sin(2 * np.pi * 3.0 * tg + self.pose_rng.normal(0, 0.3))
            elif pose.arms == "writing":
                pose.arm_jitter = 0.015 * np.sin(2 * np.pi * 1.5 * tg + self.pose_rng.normal(0, 0.3))
            for nod in self._nods:
                off, active = S._nod_offset(nod, ts)
                if active:
                    if self._nod_side:
                        pose.head_roll += off * 0.9 * self._nod_side
                        pose.neck_pitch += off * 0.25
                        pose.trunk_roll += off * 0.3 * self._nod_side
                    else:
                        pose.neck_pitch += off
                        pose.trunk_pitch += off * 0.25
                    flags |= FLAG_NOD
            self._prev_pose = pose
        grids = {si: self._measure(si, pose) for si in self.sensors}
        self.frames += 1
        return FrameOut(t=t, label=label, flags=flags, kind=kind, override=override, grids=grids)

    def _measure(self, si: int, pose) -> tuple[np.ndarray, np.ndarray]:
        sensor = self.sensors[si]
        if self.backend == "mujoco":
            origin, R = self._mj_frames[si]
            self.desk.set_walker(None)
            self.desk.set_pose(pose)
            return sensor.measure(self.desk.cast, origin, R)
        if pose is None:
            surfaces = self.B.build_scene(self.cfg.room, None, None, seat_person=self.cfg.person)
        else:
            surfaces = self.B.build_scene(self.cfg.room, self.cfg.person, pose)
        return sensor.measure_surfaces(surfaces, self.sensor_poses[si])
