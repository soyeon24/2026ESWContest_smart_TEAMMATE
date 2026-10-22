"""자세·졸음 판정 단계 — 센서별 8×8 프레임 → (센서별 추론 → log-softmax 융합 → 1 s 다수결) + 끄덕임 검출기
→ hub 가 먹는 두 표본: `tof`(ESP32 0x03 tof_feature 모사: present·posture·nod_rate_hz·drowsy) 와 `tof_mlp`(Pi 4 모델 판정).

backend 는 config/posture.yaml 의 설명대로 oracle | mlp | gru. 졸음(drowsy)은 한 프레임 현상이 아니라 시간 현상이라
hub 의 ingest 는 0x03 의 drowsy·nod_rate 를 쓴다(posture_delta drowsy 1.0, nod_rate_hz / nod_rate_full_hz). 여기서는
끄덕임 검출기(격자 기반)가 그 값을 내고, gru/oracle 처럼 모델이 drowsy 클래스를 내면 OR 로 합친다.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

LABELS = ["upright", "lean_forward", "recline", "face_down", "chin_rest", "drowsy", "away", "misplaced", "forward_head"]
VALID_STATUS = (5, 6, 9, 10)


def log_softmax_fuse(probs: list[np.ndarray]) -> np.ndarray:
    logs = sum(np.log(np.maximum(p, 1e-12)) for p in probs)
    logs = logs - logs.max()
    e = np.exp(logs)
    return e / e.sum()


# ---------------------------------------------------------------- 끄덕임 검출기

class NodDetector:
    """센서 한 개의 격자에서 '머리 거리'(위쪽 head_rows 행의 사람 zone 평균 거리, 펌웨어 0x03 의 head_delta_mm 와 같은 뜻)를
    추적해 끄덕임을 센다. 고개가 떨어지면 머리가 센서 쪽으로 다가와 거리가 수십~수백 mm 준다. 라벨은 보지 않는다."""

    def __init__(self, cfg: dict[str, Any], fps: float):
        self.cfg = cfg
        self.fps = fps
        self._hist: deque[tuple[float, float]] = deque()           # (t, head_mm) 기준선용
        self._drop_since: float | None = None
        self._drop_base: float = 0.0
        self._nod_ts: deque[float] = deque()
        self.last_head_mm: float | None = None
        self.last_base: float | None = None
        self.events = 0

    def head_mm(self, dist: np.ndarray, status: np.ndarray) -> float | None:
        c = self.cfg
        valid = np.isin(status, VALID_STATUS) & (dist >= 0)
        person = valid & (dist >= c["min_person_mm"]) & (dist <= c["max_person_mm"])
        top = person[: int(c["head_rows"])]
        if top.sum() < int(c["head_min_zones"]):
            return None
        return float(dist[: int(c["head_rows"])][top].mean())

    def observe(self, t: float, dist: np.ndarray, status: np.ndarray) -> None:
        c = self.cfg
        hm = self.head_mm(dist, status)
        self.last_head_mm = hm
        while self._nod_ts and t - self._nod_ts[0] > float(c["window_s"]):
            self._nod_ts.popleft()
        if hm is None:
            self._drop_since = None
            return
        base_window = float(c["baseline_sec"])
        while self._hist and t - self._hist[0][0] > base_window:
            self._hist.popleft()
        base = float(np.median([v for _, v in self._hist])) if len(self._hist) >= int(self.fps * 2) else None
        self.last_base = base
        if self._drop_since is not None:
            # 숙인 동안은 기준선이 안 쌓인다(마이크로 수면이 baseline_sec 보다 길 수 있다) — 숙이기 시작할 때의 기준선과 비교한다
            ref = self._drop_base
            if t - self._drop_since > float(c["max_s"]):
                # 너무 오래 숙이고 있다: 자세가 바뀐 것이다(엎드림·필기 등). 끄덕임으로 세지 않고 기준선을 따라가게 둔다.
                self._drop_since = None
                self._hist.append((t, hm))
            elif (ref - hm) < 0.5 * float(c["drop_mm"]):            # 고개를 들었다
                dur = t - self._drop_since
                if dur >= float(c["min_s"]):
                    self._nod_ts.append(t)
                    self.events += 1
                self._drop_since = None
                self._hist.append((t, hm))
            return
        if base is not None and (base - hm) >= float(c["drop_mm"]):
            self._drop_since, self._drop_base = t, base
        else:
            self._hist.append((t, hm))

    def nod_rate_hz(self, t: float) -> float:
        return len(self._nod_ts) / float(self.cfg["window_s"])

    def nods_in_window(self) -> int:
        return len(self._nod_ts)

    def last_nod_t(self) -> float | None:
        return self._nod_ts[-1] if self._nod_ts else None


# ---------------------------------------------------------------- 추론 백엔드

class OracleEstimator:
    """정답 라벨을 confusion 표로 흐려서 센서별 확률을 낸다(모델 없이 폐루프를 시험할 때)."""

    def __init__(self, cfg: dict[str, Any], seed: int):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.labels = LABELS
        self.has_drowsy = True

    def reset(self) -> None:
        pass

    def step(self, si: int, dist: np.ndarray, status: np.ndarray, truth: str | None) -> np.ndarray | None:
        p = np.full(len(LABELS), 0.01)
        acc = float(self.cfg["accuracy"])
        truth = truth or "upright"
        if self.rng.random() < acc:
            p[LABELS.index(truth)] = 1.0
        else:
            alts = self.cfg["confusion"].get(truth, ["upright"])
            p[LABELS.index(str(self.rng.choice(alts)))] = 1.0
        return p / p.sum()


class MlpEstimator:
    """hub posture/tof_mlp.py 의 순수 Python MLP. 기준선(앉은 뒤 조용한 10 s)이 잡혀야 판정이 나온다. drowsy 클래스 없음."""

    def __init__(self, ingest_tof_cfg: dict[str, Any]):
        from deskmate_hub.posture.tof_mlp import load_model, TofMlpPosture, _SensorState

        mcfg = dict(ingest_tof_cfg.get("mlp") or {})
        self.model = load_model(mcfg.get("weights"))
        self.owner = TofMlpPosture(self.model, mcfg)
        self._state_cls = _SensorState
        self.labels = list(self.model.classes)
        self.has_drowsy = "drowsy" in self.labels

    def reset(self) -> None:
        self.owner.reset_baseline()

    def step(self, si: int, dist: np.ndarray, status: np.ndarray, truth: str | None) -> np.ndarray | None:
        state = self.owner.sensors.setdefault(int(si), self._state_cls(self.owner))
        p = state.observe([int(v) for v in dist.ravel()], [int(v) for v in status.ravel()], 0.0)
        return None if p is None else np.asarray(p, dtype=float)

    @property
    def baseline_ready(self) -> bool:
        return self.owner.baseline_ready


class GruEstimator:
    """tof_sim_v5 PostureNet(CNN+GRU, torch). 센서마다 은닉 상태를 따로 이어 간다. 체크포인트 라벨 순서를 쓴다."""

    def __init__(self, ckpt_path: str, cfg: dict[str, Any]):
        import torch
        from tofsim.model import PostureNet       # tofgen.import_tofsim 이 sys.path 를 올려 둔다

        self.torch = torch
        ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        sd = ck["model"] if "model" in ck else ck["state_dict"]
        self.labels = [str(s) for s in ck.get("labels", LABELS)]
        hidden = int(sd["gru.weight_hh_l0"].shape[1])
        sensor = ck.get("sensor") or {"height": 8, "width": 8}
        self.net = PostureNet(int(sensor.get("height", 8)), int(sensor.get("width", 8)), len(self.labels), hidden=hidden)
        self.net.load_state_dict(sd)
        self.net.eval()
        self.ckpt = ckpt_path
        self.h: dict[int, Any] = {}
        self.has_drowsy = str(cfg.get("drowsy_label", "drowsy")) in self.labels
        self.max_mm = 4000.0

    def reset(self) -> None:
        self.h = {}

    def step(self, si: int, dist: np.ndarray, status: np.ndarray, truth: str | None) -> np.ndarray | None:
        torch = self.torch
        valid = np.isin(status, VALID_STATUS) & (dist >= 0)
        x0 = np.where(valid, dist.astype(np.float32) / self.max_mm, 0.0).astype(np.float32)
        x = np.stack([x0, valid.astype(np.float32)], axis=0)[None, None]       # (1,1,2,H,W)
        with torch.no_grad():
            logits, h = self.net(torch.from_numpy(x), self.h.get(si))
        self.h[si] = h
        p = torch.softmax(logits[0, 0], -1).numpy()
        return p


# ---------------------------------------------------------------- 단계

@dataclass
class PostureVerdict:
    posture: str
    confidence: float
    raw: str
    present: bool
    drowsy: bool
    nod_rate_hz: float
    nods_in_window: int
    baseline_ready: bool
    probs: dict[str, float]


class PostureStage:
    def __init__(self, cfg: dict[str, Any], *, backend: str, fps: float, seed: int, ingest_cfg: dict[str, Any],
                 ckpt: str | None = None, sensors: tuple[int, ...] = (0, 1)):
        self.cfg = cfg
        self.backend = backend
        self.fps = fps
        if backend == "oracle":
            self.est = OracleEstimator(cfg["oracle"], seed)
        elif backend == "mlp":
            self.est = MlpEstimator(ingest_cfg["tof"])
        elif backend == "gru":
            if not ckpt:
                raise ValueError("gru 백엔드는 --ckpt 가 필요하다")
            self.est = GruEstimator(ckpt, cfg.get("gru") or {})
        else:
            raise ValueError(f"posture backend 는 oracle | mlp | gru: {backend!r}")
        self.labels = self.est.labels
        self.nods = {si: NodDetector(cfg["nod_detector"], fps) for si in sensors}
        self._votes: deque[tuple[int, float]] = deque(maxlen=int(cfg.get("vote_frames", 10)))
        self.min_conf = float(cfg.get("min_confidence", 0.3))
        self._present_mm = (float(cfg["nod_detector"]["min_person_mm"]), float(cfg["nod_detector"]["max_person_mm"]))
        self.last: PostureVerdict | None = None
        self.frames = 0
        self._model_drowsy_until: float | None = None

    def info(self) -> dict[str, Any]:
        out = {"backend": self.backend, "labels": list(self.labels), "fusion": self.cfg.get("fusion"),
               "vote_frames": self._votes.maxlen}
        if self.backend == "gru":
            out["ckpt"] = self.est.ckpt
        if self.backend == "mlp":
            out["weights_source"] = self.est.model.source
        return out

    def _present(self, grids: dict[int, tuple[np.ndarray, np.ndarray]]) -> bool:
        lo, hi = self._present_mm
        for dist, status in grids.values():
            valid = np.isin(status, VALID_STATUS) & (dist >= 0)
            person = valid & (dist >= lo) & (dist <= hi)
            if person.mean() >= 0.06:
                return True
        return False

    def observe(self, t: float, grids: dict[int, tuple[np.ndarray, np.ndarray]], truth: str | None) -> PostureVerdict:
        self.frames += 1
        probs = []
        for si, (dist, status) in grids.items():
            self.nods[si].observe(t, dist, status)
            p = self.est.step(si, dist, status, truth)
            if p is not None:
                probs.append(np.asarray(p, dtype=float))
        present = self._present(grids)
        if probs:
            fused = log_softmax_fuse(probs)
            idx = int(fused.argmax())
            self._votes.append((idx, float(fused[idx])))
        counts: dict[int, int] = {}
        for i, _ in self._votes:
            counts[i] = counts.get(i, 0) + 1
        if counts:
            best = max(counts.items(), key=lambda kv: kv[1])[0]
            conf = sum(p for i, p in self._votes if i == best) / len(self._votes)
            posture, raw = self.labels[best], (self.labels[idx] if probs else self.labels[best])
        else:
            posture, raw, conf = "unknown", "unknown", 0.0
        if not present:
            posture, raw = "away", "away"
        # 졸음: 끄덕임 검출기(센서 OR 또는 AND) + 모델 drowsy 클래스
        nd = self.cfg["nod_detector"]
        rates = [d.nod_rate_hz(t) for d in self.nods.values()]
        recent = [d.last_nod_t() for d in self.nods.values()]
        rate = min(rates) if nd.get("require_both_sensors") else max(rates)
        nods_n = max(d.nods_in_window() for d in self.nods.values())
        last_nod = max((r for r in recent if r is not None), default=None)
        drowsy = rate >= float(nd["drowsy_rate_hz"]) or (last_nod is not None and t - last_nod <= float(nd["drowsy_hold_s"])
                                                        and nods_n >= 2)
        quiet = float(nd.get("clear_after_quiet_s", 0))
        if quiet and last_nod is not None and t - last_nod >= quiet and posture != "drowsy":
            drowsy = False               # 끄덕임이 한동안 없고 자세도 졸음이 아니면 깬 것으로 본다
        if posture == "drowsy" and conf >= self.min_conf and present:
            self._model_drowsy_until = t + (quiet or float(nd["drowsy_hold_s"]))
        if self._model_drowsy_until is not None and t <= self._model_drowsy_until and present:
            drowsy = True
        self.last = PostureVerdict(
            posture=posture, confidence=round(conf, 4), raw=raw, present=present, drowsy=bool(drowsy) and present,
            nod_rate_hz=round(rate, 4), nods_in_window=nods_n,
            baseline_ready=bool(probs) if self.backend != "mlp" else bool(self.est.baseline_ready),
            probs={self.labels[i]: round(float(v), 4) for i, v in enumerate(fused)} if probs else {})
        return self.last

    # ---- hub 표본 ----
    def tof_sample(self) -> dict[str, Any]:
        """ESP32 0x03 tof_feature 모사(ingest.mapping._tof_posture_signal 이 읽는 키만)."""
        v = self.last
        if v is None:
            return {"present": False, "posture": "unknown", "posture_confidence": 0.0, "drowsy": False,
                    "nod_rate_hz": 0.0, "nods_in_window": 0, "motion_score": 0.0, "baseline_ready": False,
                    "sensors_ok": 3, "grid_width": 8, "grid_height": 8}
        return {"present": v.present, "posture": v.posture if v.posture in ("away", "unknown") else v.posture,
                "posture_confidence": v.confidence, "drowsy": v.drowsy, "nod_rate_hz": v.nod_rate_hz,
                "nods_in_window": v.nods_in_window, "motion_score": 0.0, "baseline_ready": v.baseline_ready,
                "sensors_ok": 3, "grid_width": 8, "grid_height": 8, "posture_source": "sim"}

    def tof_mlp_sample(self) -> dict[str, Any]:
        """Pi 4 모델 판정 표본(ingest.mapping._tof_with_mlp 가 덮어쓰는 키)."""
        v = self.last
        if v is None or not v.present:
            return {"posture": "unknown", "posture_confidence": 0.0, "present": False, "baseline_ready": False,
                    "raw_posture": "unknown", "source": self.backend, "sensors_used": 0, "frames": self.frames}
        return {"posture": v.posture, "posture_confidence": v.confidence, "present": v.present,
                "baseline_ready": v.baseline_ready, "raw_posture": v.raw, "source": self.backend,
                "sensors_used": 2, "frames": self.frames}
