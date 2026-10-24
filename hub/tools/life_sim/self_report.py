"""Pi 5 피로 기록 앱(PR #58, display/atlas/fatigue_app)의 15 분 KSS 질문 모사 — 실험, 기본 꺼짐.

앱은 period_s 마다 KSS(1~9)를 묻는다. 시뮬 사람은 그 순간의 졸림 S(잠재 피로 fatigue.py)로 답한다.
ml/training/fatigue_lifesim.py 의 앱 응답 모델과 같은 가정이다: KSS = round(1 + 10·S)(S 0.6 → 7, 0.8 이상 → 9),
noise_p 확률로 ±1 흔들림, 5~60 s 늦게 답함. 질문 순간에 자리를 비웠거나(away) 졸고 있으면(drowsy·face_down) 놓치고,
miss_after_s 뒤 앱이 prompt_missed 를 보낸다(docs/mqtt-topics.md event prompt_missed).
**KSS 는 각본값이다** — 실제 사람이 졸릴 때 얼마나 정확히 답하는지는 모른다. 질문이 사람을 깨우는 효과도 넣지 않았다.

응답은 hub 에 실기와 같은 토픽·모양(deskmate/fatigue/label, docs/mqtt-topics.md)으로 넘긴다(hub_bridge.feed_fatigue_label).
"""
from __future__ import annotations

import random
from typing import Any

MISS_KINDS = {"away", "drowsy", "face_down"}


def kss_from_s(s: float) -> int:
    """졸림 S(0~1) → KSS 1~9 (ml/training/fatigue_lifesim.kss_from_s 와 같은 사상)."""
    return int(min(9, max(1, round(1.0 + 10.0 * float(s)))))


class SelfReportApp:
    def __init__(self, cfg: dict[str, Any] | None, *, seed: int, t0: float, profile_id: str = "sim"):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.period_s = float(cfg.get("period_s", 900))
        self.noise_p = float(cfg.get("noise_p", 0.3))
        lo, hi = cfg.get("delay_s", [5, 60])
        self.delay_s = (float(lo), float(hi))
        self.rnd = random.Random(seed * 131 + 61)        # 다른 각본 난수와 섞이지 않게 따로
        self.next_prompt = t0 + self.period_s
        self.profile_id = profile_id
        self.session_id = f"{profile_id}-{int(t0)}"
        self.pending: dict[str, Any] | None = None
        self.miss_after_s = float(cfg.get("miss_after_s", 120))
        self.pending_miss: float | None = None           # 놓친 질문 시각 — miss_after_s 뒤 prompt_missed 를 보낸다
        self.log: list[dict[str, Any]] = []

    def step(self, t: float, *, S: float | None, kind: str) -> dict[str, Any] | None:
        """1 초마다. 이번 초에 보낼 응답(deskmate/fatigue/label data)이 있으면 돌려준다."""
        if not self.enabled:
            return None
        if t >= self.next_prompt:
            prompt = self.next_prompt
            self.next_prompt += self.period_s
            if S is None or kind in MISS_KINDS:
                self.log.append({"prompt_ts": prompt, "missed": True, "kind": kind, "S": None if S is None else round(S, 3)})
                self.pending_miss = prompt
            else:
                k = kss_from_s(S)
                if self.rnd.random() < self.noise_p:
                    k = min(9, max(1, k + self.rnd.choice((-1, 1))))
                self.pending = {"prompt_ts": prompt, "answer_at": t + self.rnd.uniform(*self.delay_s), "kss": k, "S": round(S, 3)}
        if self.pending is not None and t >= self.pending["answer_at"]:
            p, self.pending = self.pending, None
            data = {"event": "kss", "session_id": self.session_id, "profile_id": self.profile_id, "ts": round(t, 3),
                    "kss": p["kss"], "prompt_ts": round(p["prompt_ts"], 3), "response_ms": int(round((t - p["prompt_ts"]) * 1000))}
            self.log.append({"prompt_ts": p["prompt_ts"], "missed": False, "ts": t, "kss": p["kss"], "S": p["S"]})
            return data
        if self.pending_miss is not None and t >= self.pending_miss + self.miss_after_s:
            prompt, self.pending_miss = self.pending_miss, None
            return {"event": "prompt_missed", "session_id": self.session_id, "profile_id": self.profile_id, "ts": round(t, 3),
                    "prompt_ts": round(prompt, 3)}
        return None

    def summary(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        answered = [r for r in self.log if not r["missed"]]
        hist = {k: sum(1 for r in answered if r["kss"] == k) for k in range(1, 10)}
        return {"prompts": len(self.log), "answered": len(answered), "missed": len(self.log) - len(answered),
                "kss_hist": {k: v for k, v in hist.items() if v}, "ge8": sum(1 for r in answered if r["kss"] >= 8),
                "log": self.log}
