"""CAD04 두 센서 장면 — tofsim 의 세션 무작위화로 책상·사람·기기 배치를 뽑고, 프레임마다 두 센서를 렌더한다.

표준(10-17): ToF 의 단위는 "센서 하나의 8×8". 두 센서(DEVICE_SENSORS, CAD 정본: 좌 (+0.0525, 0.1299, 0.0337) m·위 20°·
바깥 요 8°, 우 대칭)는 따로 렌더하고 따로 추론한다(16×8 스티칭 없음).

센서 보정: 환경변수 TOFSIM_L8_PARAMS 가 가리키는 l8 파라미터(apply_l8_patch 가 들어간 사본에서만 효과)가 있으면 그 값이
sample_session 안에서 적용된다. 어떤 파일을 썼는지는 cfg.meta["l8"] 에 남고 요약에 적는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import tofsim_bridge


@dataclass
class Scene:
    cfg: Any                              # tofsim SessionConfig (sensor_pose = 센서 0)
    poses: list                           # 센서별 SensorPose (인덱스 = 물리 센서 번호 0 A / 1 B)
    backend: str
    sensors: list = field(default_factory=list)
    _desk: Any = None
    _frames: list = field(default_factory=list)   # mujoco: (origin, R) per sensor
    meta: dict = field(default_factory=dict)
    devices: list = field(default_factory=list)   # [{azimuth_deg, sensors}] — 그린 기기(보통 1대)

    @property
    def limits(self) -> dict:
        return dict(self.cfg.meta.get("limits") or {})

    def render(self, pose, walker=None) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """pose(None = 빈 의자) → {센서 번호: (distance_mm int16 [H,W], status uint8 [H,W])}."""
        out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        if self.backend == "mujoco":
            self._desk.set_walker(walker)
            self._desk.set_pose(pose)
            for i, (sensor, (origin, R)) in enumerate(zip(self.sensors, self._frames)):
                out[i] = sensor.measure(self._desk.cast, origin, R)
        else:
            from tofsim.body import build_scene
            if pose is None:
                surfaces = build_scene(self.cfg.room, None, None, seat_person=self.cfg.person)
            else:
                surfaces = build_scene(self.cfg.room, self.cfg.person, pose)
            for i, (sensor, sp) in enumerate(zip(self.sensors, self.poses)):
                out[i] = sensor.measure_surfaces(surfaces, sp)
        return out


def build_scene(seed: int, *, backend: str = "mujoco", placement: str = "desk", clutter: int = 4, scene: str = "rich",
                require_ok: bool = True, l8_params: str | None = None, max_tries: int = 60,
                arc_azimuths: list[float] | None = None, arc_device: int | None = None) -> Scene:
    """시드 하나로 장면 하나. require_ok 면 분류기가 읽을 수 있는 배치(meta.misplaced=False)가 나올 때까지 다시 뽑는다.

    arc_azimuths(placement "arc" 일 때): 사람 둘레 호 위 기기 위치(도, + = 사람 왼쪽). arc_device 를 주면 그 기기(번호 =
    방위각 순서)의 센서 2개만 그린다 — 같은 시드면 방·체형·호 반지름이 같고 기기 위치만 다르다(life_sim learn --devices).

    l8_params: 보정 파일 경로(None = 환경변수 그대로). 상대 이름(v4/v5)은 tofsim 루트의 l8/<이름>.json 으로 푼다.
    """
    tofsim = tofsim_bridge.load()
    if tofsim is None:
        raise RuntimeError("tofsim 을 찾지 못했다 — TOFSIM_ROOT 를 dataset/tof_sim_v5 사본으로 지정")
    from tofsim.session import sample_session
    from tofsim.sensor import Sensor

    if l8_params:
        path = l8_params
        if not os.path.isabs(path) and not os.path.exists(path):
            root = tofsim_bridge.find_root() or ""
            cand = os.path.join(root, "l8", f"{path}.json")
            if os.path.exists(cand):
                path = cand
        os.environ["TOFSIM_L8_PARAMS"] = path
    rng = np.random.default_rng(seed)
    cfg = None
    tries = 0
    import tofsim.session as _ts
    saved_az = _ts.SENSOR_AZIMUTHS_DEG
    if arc_azimuths and placement == "arc":
        _ts.SENSOR_AZIMUTHS_DEG = tuple(float(a) for a in arc_azimuths)     # 호 위 기기 위치(이 장면만)
    try:
        for tries in range(1, max_tries + 1):
            cfg = sample_session(rng, "vl53l8cx", placement=placement, clutter_max=clutter, scene=scene)
            if not require_ok or not cfg.meta.get("misplaced", False):
                break
    finally:
        _ts.SENSOR_AZIMUTHS_DEG = saved_az
    if arc_azimuths and placement == "arc":
        arc = sorted(cfg.meta["arc"], key=lambda t: (float(t[0]), t[1]))     # 기기(방위각)별로 센서 0·1
        all_az = sorted({round(float(a), 1) for a, _i, _p in arc})
        if arc_device is not None:
            keep = all_az[int(arc_device)]
            arc = [e for e in arc if round(float(e[0]), 1) == keep]
    else:
        arc = sorted(cfg.meta["arc"], key=lambda t: t[1])
    poses = [p for (_az, _i, p) in arc]
    sensors = [Sensor(cfg.spec, cfg.model, np.random.default_rng(seed * 7919 + i + 1)) for i in range(len(poses))]
    sc = Scene(cfg=cfg, poses=poses, backend=backend, sensors=sensors)
    devices: dict[float, list[int]] = {}
    for i, (az, _si, _p) in enumerate(arc):
        devices.setdefault(round(float(az), 1), []).append(i)
    sc.devices = [{"azimuth_deg": az, "sensors": idx} for az, idx in sorted(devices.items())]
    if backend == "mujoco":
        from tofsim.mj_scene import MjDesk, sensor_frame
        sc._desk = MjDesk(cfg.room, cfg.person)
        sc._frames = [sensor_frame(p) for p in poses]
    elif backend != "numpy":
        raise ValueError(f"backend must be mujoco|numpy, not {backend!r}")
    pl = cfg.meta.get("placement") or {}
    sc.meta = {
        "seed": seed, "backend": backend, "placement_mode": cfg.meta.get("placement_mode"),
        "misplaced": bool(cfg.meta.get("misplaced", False)), "placement_tries": tries,
        "radius_m": round(float(cfg.meta.get("radius_m", 0.0)), 3),
        "azimuth_deg": round(float(cfg.meta.get("azimuth_deg", 0.0)), 1),
        "aim_deg": round(float(pl.get("aim_deg", 0.0)), 1), "pitch_err_deg": round(float(pl.get("pitch_err_deg", 0.0)), 1),
        "head_dist_m": round(float(pl.get("head_dist_m", 0.0)), 3), "why": pl.get("why", ""),
        "l8": cfg.meta.get("l8"), "l8_file": os.environ.get("TOFSIM_L8_PARAMS") or None,
        "smplx": bool(getattr(cfg.person, "smplx", None)), "sensors": len(poses),
        "sensor_positions_m": [[round(float(v), 4) for v in p.position] for p in poses],
        "scene_mode": cfg.meta.get("scene_mode"), "clutter": cfg.meta.get("clutter"),
        "devices_azimuth_deg": [d["azimuth_deg"] for d in sc.devices],
        "arc_azimuths": [float(a) for a in arc_azimuths] if arc_azimuths else None, "arc_device": arc_device,
        "body_gender": (getattr(cfg.person, "smplx", None) or {}).get("gender"),
        "body_height_m": round(1.72 * float(getattr(cfg.person, "scale", 1.0)), 3),
        "seat_height_m": round(float(getattr(cfg.person, "seat_height", 0.0)), 3),
    }
    return sc
