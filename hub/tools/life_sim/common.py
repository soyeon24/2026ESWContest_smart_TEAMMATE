"""공통모델 — 선호가 별로 없는 사람(neutral) 여럿이 learn 으로 배운 상태를 하나로 합친다(10-24 사용자: 2번 방향, "공통모델은
선호도가 별로 없는 사람으로"). 개인화는 이 공통모델에서 출발한다(learn --init-from).

- 피로 판단(learner.json): 잔차 가중치 w 를 사람끼리 평균(FedAvg). AdaGrad 누적 g2 는 kappa 배로 줄여, 새 사람의 라벨로 빨리 움직인다.
  라벨 수·맞힘 기록은 비운다(개인 것). "common": true — 학습기는 라벨이 쌓이기 전에도 common_alpha 만큼 공통모델을 쓴다.
- 개입 방식(policy.json): arm·축마다 베이지안 선형 회귀 사후분포를 모은다. A = λI + κ·Σ(A_p − λI), b = λθ⁰ + κ·Σ(b_p − λθ⁰).
  κ 가 공통모델의 무게(작을수록 개인 피드백이 빨리 이긴다). 피드백 수·통계·되돌리기 벌점은 비운다(개인 것).

    python -m tools.life_sim common --runs "runs/common/p*_ai*" --out runs/common/model --kappa 0.2
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any

import numpy as np


def merge_learners(paths: list[str], *, kappa: float) -> dict[str, Any]:
    states = [json.load(open(p, encoding="utf-8")) for p in paths]
    feats = states[0].get("features")
    states = [s for s in states if s.get("features") == feats and (s.get("model") or {}).get("w")]
    if not states:
        raise ValueError("합칠 learner.json 이 없다(특징이 다르거나 비었음)")
    w = np.mean([s["model"]["w"] for s in states], axis=0)
    g2 = np.mean([s["model"]["g2"] for s in states], axis=0) * float(kappa)
    n = int(states[0]["model"]["n"])
    return {"model": {"n": n, "w": w.tolist(), "g2": np.maximum(g2, 1e-6).tolist()}, "n_labels": 0, "hist": [],
            "features": feats, "common": True, "common_from": len(states),
            "common_labels": int(sum(int(s.get("n_labels", 0)) for s in states))}


def merge_policies(paths: list[str], cfg: dict[str, Any], *, kappa: float) -> dict[str, Any]:
    from deskmate_hub.personalize import InterventionPolicy
    base = InterventionPolicy(cfg)
    out = InterventionPolicy(cfg)
    used = 0
    for p in paths:
        try:
            data = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pol = InterventionPolicy(cfg)
        pol.load_dict(data)
        used += 1
        for arm, axes in pol.models.items():
            for axis, m in axes.items():
                b0 = base.models[arm][axis]
                o = out.models[arm][axis]
                o.A = o.A + float(kappa) * (m.A - b0.A)
                o.b = o.b + float(kappa) * (m.b - b0.b)
                o.n += m.n
                o._inv = None
    d = out.to_dict()
    d.update(n_feedback=0, common=True, common_from=used)
    return d


def build_common(run_dirs: list[str], out_dir: str, *, kappa: float = 0.2,
                 policy_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    lpaths = [os.path.join(d, "learner.json") for d in run_dirs if os.path.exists(os.path.join(d, "learner.json"))]
    ppaths = [os.path.join(d, "policy.json") for d in run_dirs if os.path.exists(os.path.join(d, "policy.json"))]
    meta: dict[str, Any] = {"runs": len(run_dirs), "kappa": kappa}
    if lpaths:
        lr = merge_learners(lpaths, kappa=kappa)
        json.dump(lr, open(os.path.join(out_dir, "learner.json"), "w", encoding="utf-8"))
        meta.update(learners=lr["common_from"], labels=lr["common_labels"])
    if ppaths and policy_cfg is not None:
        pol = merge_policies(ppaths, policy_cfg, kappa=kappa)
        json.dump(pol, open(os.path.join(out_dir, "policy.json"), "w", encoding="utf-8"), ensure_ascii=False)
        meta.update(policies=pol["common_from"])
    json.dump(meta, open(os.path.join(out_dir, "common_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return meta


def add_extra_arms(cfg: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    """hub personalize 설정에 life_sim 에서만 쓰는 선택지(devices.yaml policy_extra_arms — 화면 밝기·공기청정기·음악)를 더한다."""
    extra = extra or {}
    have = {a["id"] for a in cfg["arms"]}
    cfg["arms"] = list(cfg["arms"]) + [a for a in extra.get("arms") or [] if a["id"] not in have]
    cfg["prior"] = dict(cfg.get("prior") or {}, **(extra.get("prior") or {}))
    return cfg


def policy_config_for_learn() -> dict[str, Any]:
    """learn --learn-outputs 와 같은 arm 묶음(hub 기본 + life_sim 에서만 더한 선택지)."""
    from deskmate_hub.personalize import load_personalize_config

    from .scenario import load_defaults
    return add_extra_arms(dict(load_personalize_config(), enabled=True), load_defaults()[1].get("policy_extra_arms"))


def expand(patterns: list[str]) -> list[str]:
    return sorted({d for pat in patterns for d in glob.glob(pat) if os.path.isdir(d)})
