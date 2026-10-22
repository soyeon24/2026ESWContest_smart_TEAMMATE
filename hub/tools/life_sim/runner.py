"""폐루프 실행기 — 각본 하나를 끝까지 돌리고 runs/<name>/ 에 JSONL·summary.md·PNG 를 남긴다.

    cd hub
    python -m tools.life_sim.runner --scenario a1_wake_first --backend numpy --posture oracle
    python -m tools.life_sim.runner --scenario a1_wake_first --backend mujoco --posture gru --ckpt runs/<run>/ckpt_best.pt
    python -m tools.life_sim.runner --scenario b_student_day --weather windy --policy-path logs/profiles/A/policy.json

한 tick(score_period_sec = 10 s)의 순서:
  프레임(센서별 8×8, 압축 구간은 tick 당 몇 장) → 자세·졸음 판정 → 환경 적분 → SensorCache 표본(tof·tof_mlp·env·keystroke·weather)
  → 사람의 지연된 응답(feedback/user) → LiveHub.tick_once → 발행물(state/phase·request·control/cmd) → 기기·사람 반응
  → 사람 반응이 Timeline 을 덮어쓰면 다음 tick 프레임부터 자세가 바뀐다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import numpy as np

from .devices import DeviceRack
from .environment import Environment
from .hubio import HubHarness
from .person import Person
from .posture import PostureStage
from .scenario import CONFIG_DIR, Scenario, Timeline, load_scenario, load_yaml
from .tofgen import FLAG_NOD, TofGenerator

WEATHER_PRESETS = {
    "calm": {"temp_c": 17.0, "humidity": 50, "wind_ms": 1.0, "condition": "clear"},
    "windy": {"temp_c": 16.0, "humidity": 45, "wind_ms": 6.5, "condition": "cloudy"},
    "rain": {"temp_c": 15.0, "humidity": 85, "wind_ms": 2.0, "condition": "rain"},
    "winter": {"temp_c": -2.0, "humidity": 35, "wind_ms": 2.5, "condition": "clear", "season": "winter"},
    "hot": {"temp_c": 31.0, "humidity": 60, "wind_ms": 1.0, "condition": "clear"},
}


def run(scenario: Scenario, *, backend: str, posture_backend: str, out_dir: str, tofsim_dir: str | None = None,
        ckpt: str | None = None, policy_path: str | None = None, profile_id: str | None = None,
        personalize_enabled: bool = True, max_ticks: int | None = None, verbose: bool = False) -> dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    pcfg = load_yaml(os.path.join(CONFIG_DIR, "posture.yaml"))
    dcfg = load_yaml(os.path.join(CONFIG_DIR, "devices.yaml"))
    rcfg = load_yaml(os.path.join(CONFIG_DIR, "reaction.yaml"))
    personas = load_yaml(os.path.join(CONFIG_DIR, "personas.yaml"))["personas"]
    persona = personas[scenario.persona]
    month = int(time.strftime("%m", time.gmtime(scenario.start_ts + scenario.utc_offset_hours * 3600)))

    timeline = Timeline(scenario.timeline)
    gen = TofGenerator(scenario, timeline, backend=backend, tofsim_dir=tofsim_dir)
    hub = HubHarness(fsm_config=scenario.fsm_config, out_dir=out_dir, policy_path=policy_path,
                     profile_id=profile_id or scenario.persona, publish_control=lambda p: rack.handle_command(p),
                     seed=scenario.seed, personalize_enabled=personalize_enabled, quiet=True)
    stage = PostureStage(pcfg, backend=posture_backend, fps=gen.cfg.fps, seed=scenario.seed, ingest_cfg=hub.ingest_cfg,
                         ckpt=ckpt)
    env = Environment(dcfg, persona, scenario.weather, month=month, seed=scenario.seed)
    rack = DeviceRack(dcfg, env, hub.put_control_result)
    person = Person(rcfg, scenario.persona, timeline, hub.put_feedback, np.random.default_rng(scenario.seed + 55),
                    profile=scenario.reaction_profile, fsm_demo=scenario.fsm_config == "demo", env=env, devices=rack,
                    utc_offset_hours=scenario.utc_offset_hours, bedtime_hour=float(persona["bedtime_hour"]),
                    start_ts=scenario.start_ts)
    krng = np.random.default_rng(scenario.seed + 99)

    period = hub.period
    fps = gen.cfg.fps
    full = int(round(fps * period))
    n_ticks = int(np.ceil(scenario.total_s / period))
    if max_ticks:
        n_ticks = min(n_ticks, max_ticks)
    rows: list[dict[str, Any]] = []
    t_wall = time.time()
    frames_total = 0
    weather_ts = scenario.start_ts
    prev_state = "IDLE"
    seg_idx_seen = -1
    with open(os.path.join(out_dir, "timeline.jsonl"), "w", encoding="utf-8") as fh:
        for k in range(n_ticks):
            t_sc = k * period
            now = scenario.start_ts + t_sc
            seg_idx, seg0, _ = timeline.scenario_segment(t_sc)
            if seg_idx != seg_idx_seen:                       # 각본 구간 시작: 창문 상태 지시
                seg_idx_seen = seg_idx
                if seg0.window_open is True:
                    env.open_window(now, seg0.duration_s / 60.0 + 1.0)
                elif seg0.window_open is False:
                    env.close_window()
            kind, seg, override, params = timeline.effective(t_sc)
            fpt = full if kind == "drowsy" else min(full, scenario.frames_per_tick(seg, full))
            fpt = max(1, fpt)
            nod_frames = 0
            labels: dict[str, int] = {}
            for i in range(fpt):
                tf = t_sc + i * (period / fpt)
                fr = gen.next_frame(tf)
                stage.observe(tf, fr.grids, fr.label)
                nod_frames += 1 if fr.flags & FLAG_NOD else 0
                labels[fr.label] = labels.get(fr.label, 0) + 1
            frames_total += fpt
            kind, seg, override, params = timeline.effective(t_sc + period - 1e-6)
            gt_label = max(labels.items(), key=lambda kv: kv[1])[0]
            present = kind != "away"
            env.step(now, period, present=present)
            # ---- hub 표본 ----
            hub.put("tof", stage.tof_sample(), now)
            hub.put("tof_mlp", stage.tof_mlp_sample(), now)
            hub.put("env", env.env_sample(), now)
            typing = bool(params.get("typing", seg.typing)) and present
            fat_lo, fat_hi = seg.fatigue
            _, _, seg_elapsed = timeline.scenario_segment(t_sc)
            fat = fat_lo + (fat_hi - fat_lo) * min(1.0, seg_elapsed / max(1.0, seg.duration_s))
            fat *= float(params.get("fatigue_scale", 1.0))       # 깨어남·휴식 뒤에는 정신이 든다
            ks, kf = persona["keystroke"], persona["keystroke_fatigue"]
            active = typing and krng.random() < float(persona["pc_ratio"])
            hub.put("keystroke", {
                "typing_active": typing, "input_active": active, "window_s": 60,
                "idle_ratio": round(float(ks["idle_ratio"]) + fat * float(kf["idle_ratio"]) + krng.normal(0, 0.01), 3),
                "flight_cv": round(float(ks["flight_cv"]) + fat * float(kf["flight_cv"]) + krng.normal(0, 0.01), 3),
                "correction_rate": round(max(0.0, float(ks["correction_rate"]) + fat * float(kf["correction_rate"])
                                             + krng.normal(0, 0.003)), 4),
                "dwell_mean_ms": float(ks["dwell_mean_ms"]), "flight_mean_ms": float(ks["flight_mean_ms"]),
                "valid": True}, now)
            if now - weather_ts >= 1800.0 or k == 0:
                weather_ts = now
            hub.put("weather", env.weather_sample(weather_ts), now)
            # ---- 사람의 지연된 응답 → feedback/user ----
            person.step(now)
            rack.tick(now)
            # ---- FSM tick ----
            envelope, new_requests, auto = hub.tick(now)
            data = envelope["data"]
            for req in new_requests:
                rack.on_request(now, req)
                person.on_request(now, req)
            auto_arm = None
            if auto is not None:
                auto_arm = auto.get("arm")
                channel = hub.arm_channel(auto_arm)
                if channel in ("voice", "sound", "display") or auto_arm is None:
                    rack.on_auto_alert(now, auto_arm, channel, auto.get("explanation"))
                person.on_auto(now, auto_arm, channel, cause=data.get("cause"), explanation=auto.get("explanation"))
            rack.tick(now)
            v = stage.last
            row = {
                "k": k, "t_s": t_sc, "ts": now, "local": time.strftime("%H:%M:%S", time.gmtime(now + scenario.utc_offset_hours * 3600)),
                "kind": kind, "override": override, "gt_label": gt_label, "gt_nod_frames": nod_frames, "frames": fpt,
                "pred": v.posture if v else None, "pred_conf": v.confidence if v else None, "pred_drowsy": bool(v.drowsy) if v else None,
                "nod_rate_hz": v.nod_rate_hz if v else None, "present": present,
                "state": data["fsm_state"], "gate": data["gate"], "cause": data.get("cause"), "c_fatigue": data["c_fatigue"],
                "c_focus": data["c_focus"], "context": data["context"], "actions": data["reasons"],
                "request": [r["data"]["request_id"] for r in new_requests] or None,
                "request_arm": [r["data"].get("arm") for r in new_requests] or None,
                "auto_arm": auto_arm if auto is not None else None,
                "explanation": (auto or {}).get("explanation") or (new_requests[0]["data"].get("explanation") if new_requests else None),
                "env": env.snapshot(), "devices": rack.snapshot(), "typing": typing,
                "person": [n["note"] for n in person.log if abs(n["t"] - now) < 1e-6] or None,
            }
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if verbose and (data["fsm_state"] != prev_state or new_requests or auto or row["person"]):
                print(f"[{row['local']}] {data['fsm_state']:<16} fat={data['c_fatigue']:.2f} gt={gt_label:<12} pred={row['pred']} "
                      f"drowsy={row['pred_drowsy']} arm={auto_arm or row['request_arm']} {row['person'] or ''}")
            prev_state = data["fsm_state"]
    hub.close(scenario.start_ts + n_ticks * period)
    summary = summarize(scenario, rows, person, rack, stage, gen, hub, wall_s=time.time() - t_wall, frames=frames_total)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(format_summary(summary))
    with open(os.path.join(out_dir, "interventions.jsonl"), "w", encoding="utf-8") as fh:
        for iv in person.interventions:
            fh.write(json.dumps(iv.__dict__, ensure_ascii=False, default=str) + "\n")
    try:
        from .plot import plot_run
        plot_run(rows, summary, os.path.join(out_dir, "timeline.png"))
        summary["png"] = os.path.join(out_dir, "timeline.png")
    except Exception as exc:  # 그림은 부가물 — matplotlib 이 없어도 결과는 남긴다
        summary["png_error"] = str(exc)
    return summary


def summarize(scenario: Scenario, rows: list[dict[str, Any]], person: Person, rack: DeviceRack, stage: PostureStage,
              gen: TofGenerator, hub: HubHarness, *, wall_s: float, frames: int) -> dict[str, Any]:
    states = [r["state"] for r in rows]
    visited: list[str] = []
    for s in states:
        if not visited or visited[-1] != s:
            visited.append(s)
    drowsy_gt = [r for r in rows if r["gt_label"] == "drowsy"]
    drowsy_hit = sum(1 for r in drowsy_gt if r["pred_drowsy"])
    label_rows = [r for r in rows if r["present"] and r["pred"] not in (None, "unknown")]
    acc = sum(1 for r in label_rows if r["pred"] == r["gt_label"]) / len(label_rows) if label_rows else None
    per_label: dict[str, dict[str, float]] = {}
    for lbl in sorted({r["gt_label"] for r in rows}):
        sub = [r for r in rows if r["gt_label"] == lbl and r["pred"] not in (None,)]
        per_label[lbl] = {"ticks": len(sub), "recall": round(sum(1 for r in sub if r["pred"] == lbl) / len(sub), 3) if sub else None}
    first_drowsy = next((r["t_s"] for r in rows if r["gt_label"] == "drowsy"), None)
    first_flag = next((r["t_s"] for r in rows if r["pred_drowsy"]), None)
    first_action = next((r["t_s"] for r in rows if r["state"].startswith("ACTION_")), None)
    first_wake = next((iv.t - scenario.start_ts for iv in person.interventions if iv.woke), None)
    recovered = next((r["t_s"] for r in rows if first_action is not None and r["t_s"] > first_action
                      and r["state"] in ("FOCUS_PC", "FOCUS_MIXED", "FOCUS_NPC")), None)
    rest = next((r["t_s"] for r in rows if r["state"] == "REST"), None)
    ivs = [{"t_s": round(iv.t - scenario.start_ts), "local": time.strftime("%H:%M", time.gmtime(iv.t + scenario.utc_offset_hours * 3600)),
            "arm": iv.arm, "delivered": iv.delivered, "cause": iv.cause, "verdict": iv.verdict, "script": iv.script,
            "while_drowsy": iv.while_drowsy, "woke": iv.woke, "fixed_posture": iv.fixed_posture, "effect": iv.effect,
            "explanation": iv.explanation} for iv in person.interventions]
    causes = {}
    for r in rows:
        for a in r["actions"]:
            if isinstance(a, str) and a.startswith("route:"):
                causes[a[6:]] = causes.get(a[6:], 0) + 1
    return {
        "simulated": True, "scenario": scenario.name, "description": scenario.description, "persona": scenario.persona,
        "seed": scenario.seed, "fsm_config": scenario.fsm_config, "reaction_profile": scenario.reaction_profile,
        "weather": scenario.weather, "backend": gen.backend, "posture": stage.info(), "tof": gen.info(),
        "ticks": len(rows), "frames": frames, "wall_s": round(wall_s, 1), "sim_minutes": round(len(rows) * hub.period / 60.0, 1),
        "states_visited": visited, "routes": causes,
        "posture_accuracy_ticks": None if acc is None else round(acc, 3), "per_label": per_label,
        "drowsy_ticks_gt": len(drowsy_gt), "drowsy_flag_recall_ticks": round(drowsy_hit / len(drowsy_gt), 3) if drowsy_gt else None,
        "drowsy_flag_false_ticks": sum(1 for r in rows if r["pred_drowsy"] and r["gt_label"] != "drowsy"),
        "nod_events_detected": {str(si): d.events for si, d in stage.nods.items()},
        "t_first_drowsy_gt_s": first_drowsy, "t_first_drowsy_flag_s": first_flag, "t_first_action_s": first_action,
        "t_first_wake_s": None if first_wake is None else round(first_wake), "t_focus_recovered_s": recovered, "t_rest_s": rest,
        "person": person.summary(), "interventions": ivs, "devices": rack.counts,
        "device_events": [e.__dict__ for e in rack.events],
        "final_env": rows[-1]["env"] if rows else None,
    }


def format_summary(s: dict[str, Any]) -> str:
    lines = [f"# {s['scenario']} — 시뮬레이션 결과 (실측 아님)", "",
             f"{s['description']}", "",
             f"- 페르소나 {s['persona']} · seed {s['seed']} · FSM {s['fsm_config']} · 반응 대본 {s['reaction_profile']} · 날씨 {s['weather']}",
             f"- ToF {s['backend']} 백엔드 · 자세 판정 {s['posture'].get('backend')}"
             + (f" ({s['posture'].get('ckpt')})" if s['posture'].get('ckpt') else "")
             + f" · {s['ticks']} tick({s['sim_minutes']} 분) · 프레임 {s['frames']} · 벽시계 {s['wall_s']} s",
             f"- 상태 경로: {' → '.join(s['states_visited'])}",
             f"- 라우팅(route:cause 횟수): {s['routes']}",
             f"- 자세 tick 정확도 {s['posture_accuracy_ticks']} · drowsy tick 재현율 {s['drowsy_flag_recall_ticks']} "
             f"(정답 drowsy tick {s['drowsy_ticks_gt']}, 오탐 tick {s['drowsy_flag_false_ticks']}) · 끄덕임 검출 {s['nod_events_detected']}",
             f"- 첫 졸음(정답) {s['t_first_drowsy_gt_s']} s → 졸음 플래그 {s['t_first_drowsy_flag_s']} s → 첫 ACTION {s['t_first_action_s']} s "
             f"→ 깨어남 {s['t_first_wake_s']} s → FOCUS 복귀 {s['t_focus_recovered_s']} s · REST {s['t_rest_s']} s",
             f"- 사람: {s['person']}", f"- 기기 명령: {s['devices']}", "",
             "| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for iv in s["interventions"]:
        lines.append(f"| {iv['t_s']} | {iv['local']} | {iv['arm']} | {iv['delivered']} | {iv['cause']} | {iv['script']} | {iv['verdict']} | "
                     f"{'Y' if iv['while_drowsy'] else ''} | {'Y' if iv['woke'] else ''} | {'Y' if iv['fixed_posture'] else ''} | "
                     f"{iv['effect'] or ''} | {(iv['explanation'] or '')[:80]} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="생활 각본 폐루프 시뮬")
    ap.add_argument("--scenario", required=True, help="각본 yaml 경로 또는 config/scenarios/ 안의 이름")
    ap.add_argument("--backend", default="numpy", choices=["numpy", "mujoco"])
    ap.add_argument("--posture", default="oracle", choices=["oracle", "mlp", "gru"])
    ap.add_argument("--ckpt", help="gru: PostureNet 체크포인트(.pt)")
    ap.add_argument("--tofsim-dir", help="dataset/tof_sim_v5 경로(기본 TOFSIM_DIR)")
    ap.add_argument("--out", help="결과 폴더(기본 runs/lifesim/<scenario>)")
    ap.add_argument("--weather", choices=sorted(WEATHER_PRESETS), help="각본의 날씨를 프리셋으로 덮어쓴다")
    ap.add_argument("--fsm", choices=["demo", "production"], help="각본의 fsm_config 를 덮어쓴다")
    ap.add_argument("--profile", help="각본의 reaction_profile 을 덮어쓴다")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--start-local", help="각본의 시작 시각(지역시 ISO, 예 2026-01-22T10:00:00)을 덮어쓴다 — 계절 규칙 확인용")
    ap.add_argument("--policy-path", help="개인화 정책 상태(policy.json). 없으면 전역 prior 에서 시작(계정 B)")
    ap.add_argument("--profile-id", help="personalize profile_id(기본 페르소나 이름)")
    ap.add_argument("--no-personalize", action="store_true", help="3층 정책 끄기(기록만)")
    ap.add_argument("--max-ticks", type=int)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):      # Windows 콘솔(cp949)에서도 한글·기호가 깨지지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    overrides = {"fsm_config": args.fsm, "reaction_profile": args.profile, "seed": args.seed, "start_local": args.start_local}
    if args.weather:
        overrides["weather"] = dict(WEATHER_PRESETS[args.weather])
    sc = load_scenario(args.scenario, overrides=overrides)
    name = sc.name + (f"_{args.weather}" if args.weather else "") + ("_" + args.start_local[:7] if args.start_local else "")
    out = args.out or os.path.join("runs", "lifesim", name)
    s = run(sc, backend=args.backend, posture_backend=args.posture, out_dir=out, tofsim_dir=args.tofsim_dir, ckpt=args.ckpt,
            policy_path=args.policy_path, profile_id=args.profile_id, personalize_enabled=not args.no_personalize,
            max_ticks=args.max_ticks, verbose=args.verbose)
    print(format_summary(s))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
