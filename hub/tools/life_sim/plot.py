"""시간축 그림 한 장 — 정답/판정 자세, 졸음 플래그, C_fatigue/C_focus, FSM 상태, 개입·반응, CO₂·창문·기기."""
from __future__ import annotations

from typing import Any

LABEL_ORDER = ["away", "upright", "forward_head", "lean_forward", "chin_rest", "recline", "face_down", "drowsy", "unknown"]
STATE_ORDER = ["IDLE", "START", "CONTEXT_DETECT", "FOCUS_PC", "FOCUS_MIXED", "FOCUS_NPC", "FOCUS_BREAK", "FATIGUE_SUSPECT",
               "FATIGUE", "CAUSE_ANALYSIS", "ACTION_ENV", "ACTION_POSTURE", "ACTION_BREAK", "MONITOR", "RECOVERY",
               "ESCALATE", "REST", "END"]


def plot_run(rows: list[dict[str, Any]], summary: dict[str, Any], path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = [r["t_s"] / 60.0 for r in rows]
    fig, axes = plt.subplots(5, 1, figsize=(14, 11), sharex=True, gridspec_kw={"height_ratios": [1.3, 1, 1.4, 1, 1]})
    li = {l: i for i, l in enumerate(LABEL_ORDER)}
    ax = axes[0]
    ax.step(t, [li.get(r["gt_label"], li["unknown"]) for r in rows], where="post", lw=2.2, color="#888", label="ground truth")
    ax.step(t, [li.get(r["pred"] or "unknown", li["unknown"]) for r in rows], where="post", lw=1.1, color="#1f77b4", label="model (vote)")
    ax.set_yticks(range(len(LABEL_ORDER)))
    ax.set_yticklabels(LABEL_ORDER, fontsize=8)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title(f"{summary['scenario']} · persona {summary['persona']} · {summary['posture'].get('backend')} posture · "
                 f"{summary['backend']} ToF · SIMULATION (not measured)", fontsize=10)
    ax2 = axes[1]
    ax2.fill_between(t, 0, [1 if r["pred_drowsy"] else 0 for r in rows], step="post", alpha=0.4, color="#d62728", label="drowsy flag")
    ax2.plot(t, [r["nod_rate_hz"] * 20 if r["nod_rate_hz"] is not None else 0 for r in rows], color="#9467bd", lw=1, label="nod_rate×20")
    ax2.set_ylim(0, 1.2)
    ax2.legend(loc="upper right", fontsize=8)
    ax3 = axes[2]
    ax3.plot(t, [r["c_fatigue"] for r in rows], color="#d62728", lw=1.5, label="C_fatigue")
    ax3.plot(t, [r["c_focus"] for r in rows], color="#2ca02c", lw=1.0, label="C_focus")
    for y, lbl in ((0.70, "confirm"), (0.75, "auto"), (0.45, "suggest"), (0.30, "recover")):
        ax3.axhline(y, color="#bbb", lw=0.6, ls="--")
        ax3.text(t[-1], y, lbl, fontsize=7, color="#999", va="bottom", ha="right")
    for iv in summary["interventions"]:
        x = iv["t_s"] / 60.0
        color = "#ff7f0e" if iv["delivered"] == "auto" else "#17becf"
        ax3.axvline(x, color=color, lw=1.0, alpha=0.8)
        txt = f"{iv['arm']}\n{iv['verdict']}" + ("\n↑wake" if iv["woke"] else "")
        ax3.text(x, 1.02, txt, fontsize=6.5, rotation=0, ha="left", va="bottom", color=color)
    ax3.set_ylim(0, 1.0)
    ax3.legend(loc="upper left", fontsize=8)
    ax4 = axes[3]
    si = {s: i for i, s in enumerate(STATE_ORDER)}
    ax4.step(t, [si.get(r["state"], 0) for r in rows], where="post", color="#333", lw=1.4)
    ax4.set_yticks(range(len(STATE_ORDER)))
    ax4.set_yticklabels(STATE_ORDER, fontsize=6.5)
    ax5 = axes[4]
    ax5.plot(t, [r["env"]["co2_ppm"] for r in rows], color="#8c564b", lw=1.2, label="CO₂ ppm")
    ax5.fill_between(t, 0, [2000 if r["env"]["window_open"] else 0 for r in rows], step="post", alpha=0.15, color="#17becf", label="window open")
    ax5.fill_between(t, 0, [500 * r["devices"]["fan_level"] for r in rows], step="post", alpha=0.15, color="#1f77b4", label="fan level×500")
    ax5.plot(t, [(r["devices"]["lamp"].get("brightness") or 0) * 5 for r in rows], color="#bcbd22", lw=1, label="lamp×5")
    ax5.legend(loc="upper left", fontsize=7, ncol=4)
    ax5.set_xlabel("minutes since scenario start")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
