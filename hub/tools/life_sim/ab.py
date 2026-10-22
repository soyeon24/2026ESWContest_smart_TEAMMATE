"""개인화 효과 실험(§B-4) — 계정 A(합성 30 일로 학습된 프로필) vs 계정 B(전역 기본값)로 같은 하루를 돌린다.

    cd hub
    python -m tools.life_sim.ab --scenario b_student_day --days 30 --backend numpy --posture oracle

A 의 학습: personalize/synth.py 의 SynthGenerator(페르소나 = personas.yaml synth_persona)가 30 일 합성 에피소드를 밴딧에
온라인으로 먹인다(policy.feedback / policy.outcome). 그 posterior(policy.json)를 하루 각본의 시작 상태로 쓴다.
B 는 전역 prior(personalize.yaml)에서 시작한다. 두 실행은 같은 seed·각본·반응 모델을 쓴다.

검증(§B-4): 되돌리기 뒤 같은 arm 이 자동 대신 제안으로 나오는지, 거절한 arm 이 세션 안에서 다시 안 나오는지, 쿨다운·세션 상한,
"왜 이 개입인지" 한 줄이 매 개입에 있는지 — personalize.jsonl 에서 센다(`verify_policy_rules`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import numpy as np

from deskmate_hub.personalize import InterventionPolicy, load_personalize_config, read_records
from deskmate_hub.personalize.synth import PERSONAS, SynthGenerator

from .runner import WEATHER_PRESETS, format_summary, run
from .scenario import CONFIG_DIR, load_scenario, load_yaml


def train_account_a(persona_key: str, *, days: int, seed: int, out_path: str) -> dict[str, Any]:
    personas = load_yaml(os.path.join(CONFIG_DIR, "personas.yaml"))["personas"]
    synth_key = personas[persona_key]["synth_persona"]
    cfg = load_personalize_config()
    policy = InterventionPolicy(cfg, rng=np.random.default_rng(seed))
    gen = SynthGenerator(PERSONAS[synth_key], seed=seed, days=days, cfg=cfg)
    records = gen.generate(policy=policy)
    policy.save(out_path)
    eps = [r for r in records if r.get("schema_name") == "personalize_episode"]
    return {"synth_persona": synth_key, "days": days, "episodes": len(eps), "n_feedback": policy.n_feedback,
            "policy_mode": policy.policy_mode, "arm_stats": policy.arm_stats(), "policy_path": out_path}


def verify_policy_rules(records: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """personalize.jsonl 의 에피소드 줄로 §B-4 규칙을 센다. 위반이 0 이면 지켜진 것."""
    cfg = cfg or load_personalize_config()
    eps = sorted((r for r in records if r.get("schema_name") == "personalize_episode"), key=lambda r: r["ts_ms"])
    cooldown = float(cfg["bandit"]["cooldown_sec"])
    max_per = int(cfg["bandit"]["max_per_session"])
    out = {"episodes": len(eps), "undo_then_suggest_ok": 0, "undo_then_suggest_violations": 0,
           "reject_reproposed_in_session": 0, "cooldown_violations": 0, "session_cap_violations": 0,
           "missing_explanation": 0, "arms": {}, "sessions": {}}
    by_session: dict[str, list[dict[str, Any]]] = {}
    for r in eps:
        by_session.setdefault(r["session_id"], []).append(r)
        arm = r["decision"].get("arm")
        out["arms"][arm] = out["arms"].get(arm, 0) + 1
        if not (r["decision"].get("explanation") or "").strip():
            out["missing_explanation"] += 1
    for sid, rows in by_session.items():
        if len(rows) > max_per:
            out["session_cap_violations"] += 1
        out["sessions"][sid] = len(rows)
        rejected: set[str] = set()
        undone: set[str] = set()
        last_auto: dict[str, float] = {}
        for r in rows:
            d, fb = r["decision"], r.get("feedback") or {}
            arm, ts = d.get("arm"), r["ts_ms"] / 1000.0
            if arm is None:
                continue
            if arm in rejected and d.get("source") == "bandit":
                out["reject_reproposed_in_session"] += 1
            if arm in undone and r["fsm"].get("gate") == "auto":
                if d.get("delivered_gate") == "suggest":
                    out["undo_then_suggest_ok"] += 1
                else:
                    out["undo_then_suggest_violations"] += 1
            if d.get("delivered_gate") == "auto":
                if arm in last_auto and ts - last_auto[arm] < cooldown:
                    out["cooldown_violations"] += 1
                last_auto[arm] = ts
            v = fb.get("verdict")
            if v == "reject":
                rejected.add(arm)
            elif v == "undo":
                undone.add(arm)
    return out


def compare(sa: dict[str, Any], sb: dict[str, Any], ra: list[dict[str, Any]], rb: list[dict[str, Any]]) -> dict[str, Any]:
    def stats(s: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        p = s["person"]
        fat = [r["c_fatigue"] for r in rows if r["state"] not in ("IDLE", "START")]
        answered = p["accepted"] + p["rejected"] + p["timeout"]
        return {"interventions": p["interventions"], "auto": p["auto"], "suggest": p["suggest"],
                "accept_rate": round(p["accepted"] / answered, 3) if answered else None, "undone": p["undone"],
                "woke": p["woke"], "while_drowsy": p["while_drowsy"], "posture_fixed": p["posture_fixed"],
                "arms": p["arms"], "mean_c_fatigue": round(float(np.mean(fat)), 3) if fat else None,
                "fatigue_ticks_ge_0.7": sum(1 for f in fat if f >= 0.7), "drowsy_ticks_gt": s["drowsy_ticks_gt"],
                "sleep_suggested": any(iv["arm"] == "sleep_suggest" for iv in s["interventions"]),
                "ventilate": sum(1 for iv in s["interventions"] if iv["arm"] == "ventilate_suggest"),
                "rest": s["t_rest_s"] is not None}
    return {"A": stats(sa, ra), "B": stats(sb, rb)}


def format_ab(res: dict[str, Any]) -> str:
    a, b = res["compare"]["A"], res["compare"]["B"]
    keys = ["interventions", "auto", "suggest", "accept_rate", "undone", "woke", "while_drowsy", "posture_fixed",
            "mean_c_fatigue", "fatigue_ticks_ge_0.7", "sleep_suggested", "ventilate", "rest"]
    lines = [f"# A/B — {res['scenario']} (시뮬레이션, 실측 아님)", "",
             f"- A: 합성 {res['train']['days']} 일({res['train']['synth_persona']}, 에피소드 {res['train']['episodes']}, 피드백 {res['train']['n_feedback']}건, "
             f"{res['train']['policy_mode']} 정책)에서 시작 · B: 전역 prior", "",
             "| 지표 | A(학습 프로필) | B(전역 기본) |", "|---|---|---|"]
    for k in keys:
        lines.append(f"| {k} | {a[k]} | {b[k]} |")
    lines += ["", f"- A arms: {a['arms']}", f"- B arms: {b['arms']}", "",
              "## 규칙 검증(personalize.jsonl)", "", "| 검사 | A | B |", "|---|---|---|"]
    for k in ("episodes", "undo_then_suggest_ok", "undo_then_suggest_violations", "reject_reproposed_in_session",
              "cooldown_violations", "session_cap_violations", "missing_explanation"):
        lines.append(f"| {k} | {res['rules']['A'][k]} | {res['rules']['B'][k]} |")
    return "\n".join(lines) + "\n"


def plot_ab(ra: list[dict[str, Any]], rb: list[dict[str, Any]], sa: dict[str, Any], sb: dict[str, Any], path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    for ax, rows, s, name in ((axes[0], ra, sa, "A: trained profile"), (axes[1], rb, sb, "B: global prior")):
        t = [r["t_s"] / 3600.0 for r in rows]
        ax.plot(t, [r["c_fatigue"] for r in rows], color="#d62728", lw=1.0, label="C_fatigue")
        ax.fill_between(t, 0, [0.15 if r["gt_label"] == "drowsy" else 0 for r in rows], step="post", color="#9467bd", alpha=0.4, label="drowsy (truth)")
        ax.fill_between(t, 0, [0.08 if r["state"] == "IDLE" else 0 for r in rows], step="post", color="#ccc", alpha=0.6, label="IDLE")
        for iv in s["interventions"]:
            x = iv["t_s"] / 3600.0
            c = "#ff7f0e" if iv["delivered"] == "auto" else "#17becf"
            ax.axvline(x, color=c, lw=0.9, alpha=0.8)
            ax.text(x, 1.0, f"{iv['arm']}\n{iv['verdict']}", fontsize=6, color=c, va="bottom")
        ax.set_ylim(0, 1)
        ax.set_title(f"{name} · {s['scenario']} · SIMULATION", fontsize=9)
        ax.legend(loc="upper left", fontsize=7, ncol=3)
    axes[1].set_xlabel("hours since scenario start")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="개인화 A/B — 학습 프로필 vs 전역 기본값")
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--backend", default="numpy", choices=["numpy", "mujoco"])
    ap.add_argument("--posture", default="oracle", choices=["oracle", "mlp", "gru"])
    ap.add_argument("--ckpt")
    ap.add_argument("--tofsim-dir")
    ap.add_argument("--weather", choices=sorted(WEATHER_PRESETS))
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out")
    ap.add_argument("--max-ticks", type=int)
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    overrides: dict[str, Any] = {"seed": args.seed}
    if args.weather:
        overrides["weather"] = dict(WEATHER_PRESETS[args.weather])
    sc = load_scenario(args.scenario, overrides=overrides)
    out = args.out or os.path.join("runs", "lifesim", f"{sc.name}_ab" + (f"_{args.weather}" if args.weather else ""))
    os.makedirs(out, exist_ok=True)
    train = train_account_a(sc.persona, days=args.days, seed=sc.seed, out_path=os.path.join(out, "A", "policy_trained.json"))
    common = dict(backend=args.backend, posture_backend=args.posture, tofsim_dir=args.tofsim_dir, ckpt=args.ckpt,
                  max_ticks=args.max_ticks)
    sa = run(sc, out_dir=os.path.join(out, "A"), policy_path=train["policy_path"], profile_id=f"{sc.persona}-A", **common)
    sb = run(sc, out_dir=os.path.join(out, "B"), policy_path=None, profile_id=f"{sc.persona}-B", **common)
    ra = [json.loads(l) for l in open(os.path.join(out, "A", "timeline.jsonl"), encoding="utf-8")]
    rb = [json.loads(l) for l in open(os.path.join(out, "B", "timeline.jsonl"), encoding="utf-8")]
    rules = {"A": verify_policy_rules(read_records(os.path.join(out, "A", "personalize.jsonl"))),
             "B": verify_policy_rules(read_records(os.path.join(out, "B", "personalize.jsonl")))}
    res = {"simulated": True, "scenario": sc.name, "train": train, "compare": compare(sa, sb, ra, rb), "rules": rules}
    with open(os.path.join(out, "ab_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    text = format_ab(res)
    with open(os.path.join(out, "ab_summary.md"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n## A\n\n" + format_summary(sa) + "\n## B\n\n" + format_summary(sb))
    try:
        plot_ab(ra, rb, sa, sb, os.path.join(out, "ab_fatigue.png"))
    except Exception as exc:
        print(f"(그림 생략: {exc})")
    print(text)
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
