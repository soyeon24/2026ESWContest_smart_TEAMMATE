"""공통모델(선호 없는 사람들) 합치기와 공통에서 출발하는 개인화 — tools/life_sim/common.py, learner common_alpha."""
from __future__ import annotations

import json
import random

import numpy as np

from deskmate_hub.learning import ReactionLearner
from tools.life_sim.common import build_common, merge_policies, policy_config_for_learn


def _learner_file(path, w, n_labels=10):
    names = ReactionLearner.feature_names()
    json.dump({"model": {"n": len(names), "w": w, "g2": [4.0] * (len(names) + 1)}, "n_labels": n_labels,
               "hist": [[1, 1, 0]] * 5, "features": names}, open(path, "w"))


def test_common_learner_is_average_and_starts_personal_learning_with_a_floor(tmp_path):
    n = len(ReactionLearner.feature_names()) + 1
    dirs = []
    for i, v in enumerate((0.2, 0.4)):
        d = tmp_path / f"p{i}"
        d.mkdir()
        _learner_file(str(d / "learner.json"), [v] * n)
        dirs.append(str(d))
    meta = build_common(dirs, str(tmp_path / "common"), kappa=0.25)
    c = json.load(open(tmp_path / "common" / "learner.json"))
    assert meta["learners"] == 2 and meta["labels"] == 20
    assert np.allclose(c["model"]["w"], 0.3) and np.allclose(c["model"]["g2"], 1.0) and c["n_labels"] == 0 and c["common"]
    lr = ReactionLearner({"enabled": True, "common_alpha": 0.5, "n_min": 3}, state_path=str(tmp_path / "common" / "learner.json"))
    assert lr.common and lr.alpha() == 0.5                       # 개인 라벨 전에도 공통모델을 반쯤 쓴다
    for i in range(3):                                             # 이 사람에겐 공통모델이 FSM 보다 못함
        lr.hist.append((0, 1, 0))
    assert lr.alpha() < 0.5


def test_common_policy_pools_posteriors_with_kappa(tmp_path):
    from deskmate_hub.personalize import InterventionPolicy
    cfg = policy_config_for_learn()
    paths = []
    for i in range(2):
        pol = InterventionPolicy(cfg)
        m = pol.models["music_upbeat"]["effect"]
        x = np.zeros_like(m.b)
        x[0] = 1.0
        for _ in range(10):
            m.update(x, 1.0)
        pol.n_feedback = 10
        p = tmp_path / f"policy{i}.json"
        pol.save(str(p))
        paths.append(str(p))
    d = merge_policies(paths, cfg, kappa=0.5)
    base = InterventionPolicy(cfg).models["music_upbeat"]["effect"]
    A = np.array(d["models"]["music_upbeat"]["effect"]["A"])
    assert d["n_feedback"] == 0 and d["common"] and d["common_from"] == 2
    assert np.isclose(A[0, 0] - base.A[0, 0], 0.5 * 20)            # κ · 두 사람 합
    pol = InterventionPolicy(cfg)
    pol.load_dict(d)
    assert pol.policy_mode == "global"                             # 개인 피드백 전에는 공통(전역)으로


def test_demo_persona_has_fixed_dislikes():
    from tools.life_sim.reaction import ReactionModel
    from tools.life_sim.scenario import load_defaults, resolve_reaction
    cfg = resolve_reaction(load_defaults()[0], "book_examinee", None)
    m = ReactionModel(cfg, {}, seed=1)
    assert m.set_prefs(cfg["prefs"], random.Random(0)) == ["fan_high", "music_upbeat"]
