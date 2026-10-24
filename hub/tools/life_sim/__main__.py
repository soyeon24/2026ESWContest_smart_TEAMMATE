"""life_sim CLI.

    python -m tools.life_sim run <scenario.yaml> [...] --out runs/lifesim --model models/opt_l8v5_c256_best.pt [--tofsim DIR]
    python -m tools.life_sim run <scenario.yaml> --posture oracle --synthetic        # tofsim·torch 없이 하네스만
    python -m tools.life_sim table runs/lifesim/*/summary.json                      # 요약 표
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HUB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if HUB not in sys.path:
    sys.path.insert(0, HUB)


def cmd_run(args: argparse.Namespace) -> int:
    from tools.life_sim.harness import run_scenario
    from tools.life_sim.scenario import load_scenario
    if args.tofsim:
        os.environ["TOFSIM_ROOT"] = args.tofsim
    rc = 0
    for path in args.scenario:
        sc = load_scenario(path)
        if args.seed is not None:
            sc["seed"] = int(args.seed)
        if args.fsm_config:
            sc["hub"]["fsm_config"] = args.fsm_config
        if args.presence:
            sc["hub"]["presence_priority"] = args.presence
        if args.room_random:
            sc["devices_resolved"].setdefault("room", {})["randomize"] = True
        if args.desk_max_cm is not None:
            sc["hub"]["desk_max_cm"] = args.desk_max_cm
        if args.ingest_set:
            sc["hub"]["ingest_set"] = list(args.ingest_set)
        if args.fsm_set:
            sc["hub"]["fsm_set"] = list(args.fsm_set)
        if args.self_report:
            sc["devices_resolved"].setdefault("self_report", {})["enabled"] = True
        if args.vent_rule:
            sc["devices_resolved"].setdefault("vent_control", {})["enabled"] = True
        if args.fatigue:
            sc["reaction_resolved"].setdefault("fatigue", {})["enabled"] = True
        if args.stage2:
            sc["hub"]["stage2"] = os.path.abspath(args.stage2)
        if args.policy_engine:
            sc["policy"]["engine"] = args.policy_engine
        if args.policy_profile:
            sc["policy"]["profile"] = args.policy_profile
        src = None
        if args.synthetic:
            from tools.posture_sim.synthetic import SyntheticPerson
            src = SyntheticPerson(sc["segments"], seed=sc["seed"], fps=float(sc["fps"]))
        label = args.label or (f"{sc['persona']}_{sc['name']}" + ("_rr" if args.room_random else "")
                               + (f"_pres-{args.presence}" if args.presence else "")
                               + (f"_s{args.seed}" if args.seed is not None else ""))
        try:
            res = run_scenario(sc, out_dir=args.out, model_path=args.model, posture=args.posture, source=src,
                               backend=args.backend, tofsim_root=args.tofsim, label=label, replay=bool(args.replay))
        except Exception as exc:  # noqa: BLE001
            print(f"[life_sim] {path}: 실패 — {exc}", file=sys.stderr)
            if args.raise_errors:
                raise
            rc = 1
            continue
        print(f"[life_sim] {res['run_dir']}: states {' → '.join(res['fsm']['states_seq'])}")
        print(f"           interventions {res['n_interventions']}, wakes {len(res['wakes'])}, posture acc {res['posture']['acc_sec']:.3f}, "
              f"wall {res['wall_s']} s")
    return rc


def cmd_ab(args: argparse.Namespace) -> int:
    from tools.life_sim.ab import run_ab
    from tools.life_sim.scenario import load_scenario
    if args.tofsim:
        os.environ["TOFSIM_ROOT"] = args.tofsim
    rc = 0
    for path in args.scenario:
        sc = load_scenario(path)
        if args.seed is not None:
            sc["seed"] = int(args.seed)
        factory = None
        if args.synthetic:
            from tools.posture_sim.synthetic import SyntheticPerson
            factory = lambda s: SyntheticPerson(s["segments"], seed=s["seed"], fps=float(s["fps"]))  # noqa: E731
        try:
            cmp = run_ab(sc, out_dir=args.out, model_path=args.model, posture=args.posture, backend=args.backend,
                         tofsim_root=args.tofsim, source_factory=factory, seeds=args.seeds)
        except Exception as exc:  # noqa: BLE001
            print(f"[life_sim] ab {path}: 실패 — {exc}", file=sys.stderr)
            if args.raise_errors:
                raise
            rc = 1
            continue
        print(f"[life_sim] {cmp['dir']}")
        for r in cmp["rows"]:
            print(f"  {r['account']} {r['policy']}: 개입 {r['interventions']} 카드 {r['cards']} 수락률 {r['accept_rate']} "
                  f"깨어남 {r['wakes']} 평균 C_fat {r['mean_c_fatigue']:.3f} 취침권유 {r['bedtime']} 환기 {r['vent']}")
    return rc


def cmd_replot(args: argparse.Namespace) -> int:
    """저장된 frames/ticks/events.jsonl 로 timeline.png 를 다시 그린다."""
    from tools.life_sim.plots import plot_timeline
    rc = 0
    for d in [p for pat in args.run_dir for p in sorted(glob.glob(pat))]:
        try:
            load = lambda f: [json.loads(l) for l in open(os.path.join(d, f), encoding="utf-8")]  # noqa: E731
            rows, ticks, events = load("frames.jsonl"), load("ticks.jsonl"), load("events.jsonl")
            plot_timeline(rows, ticks, events, os.path.join(d, "timeline.png"), title=os.path.basename(d.rstrip("/\\")),
                          thresholds={"fatigue_confirm": 0.70, "fatigue_focus_low": 0.40, "recovery_success": 0.30})
            print(f"[life_sim] {d}/timeline.png")
        except Exception as exc:  # noqa: BLE001
            print(f"[life_sim] replot {d}: 실패 — {type(exc).__name__}: {exc}", file=sys.stderr)
            rc = 1
    return rc


def cmd_video(args: argparse.Namespace) -> int:
    from tools.life_sim.video import make_video
    out = args.out or os.path.join(args.run_dir, "video.mp4")
    cam = {k: getattr(args, k) for k in ("azimuth", "elevation", "distance") if getattr(args, k) is not None}
    res = make_video(args.run_dir, out, speed=args.speed, fps=args.fps, tofsim_root=args.tofsim, max_seconds=args.seconds,
                     start_s=args.start, camera=cam)
    print(f"[life_sim] {res['out']}: {res['frames']} frames, x{res['speed']:.0f}, smplx={res.get('smplx')}")
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    from tools.life_sim.video import make_video
    cam = {k: getattr(args, k) for k in ("azimuth", "elevation", "distance") if getattr(args, k) is not None}
    res = make_video(args.run_dir, None, speed=args.speed, fps=args.fps, tofsim_root=args.tofsim, max_seconds=args.seconds,
                     start_s=args.start, camera=cam, live=True, loop=not args.once)
    print(f"[life_sim] play 끝: {res['frames']} frames")
    return 0


def cmd_viewer(args: argparse.Namespace) -> int:
    from tools.life_sim.viewer import run_viewer
    run_viewer(args.run_dir, speed=args.speed, start_s=args.start, loop=not args.once, tofsim_root=args.tofsim)
    return 0


def cmd_daygen(args: argparse.Namespace) -> int:
    from tools.life_sim.daygen import write_days
    seeds: list[int] = []
    for part in args.seeds.split(","):
        lo, _, hi = part.partition("-")
        seeds.extend(range(int(lo), int(hi or lo) + 1))
    index = write_days(seeds, args.out, desk_hours=(args.desk_min_h, args.desk_max_h), vent_rule_p=args.vent_rule_p)
    by = lambda k: {v: sum(1 for d in index if d[k] == v) for v in sorted({d[k] for d in index}, key=str)}  # noqa: E731
    print(f"[life_sim] daygen {len(index)} 각본 → {args.out}  페르소나 {by('persona')} 계절 {by('season')} 환기규칙 {by('vent_rule')}")
    return 0


def _compact_day(run_dir: str) -> None:
    """learn --compact-logs / LIFESIM_COMPACT_LOGS=1: 하루가 끝나면 그날 jsonl 을 gzip — 10-24 UBAI 계정1 홈이 learn 로그(하루 20~25 MB)로
    디스크 한도에 걸려 학습·시뮬이 같이 죽었다. 지표는 메모리의 결과에서 이미 뽑았으니 압축해도 된다."""
    import gzip
    import shutil
    for fn in sorted(os.listdir(run_dir)):
        if fn.endswith(".jsonl"):
            path = os.path.join(run_dir, fn)
            with open(path, "rb") as src, gzip.open(path + ".gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.remove(path)


def cmd_learn(args: argparse.Namespace) -> int:
    """한 사람이 여러 날을 산다 — 날마다 자유 생활 각본(daygen, 잠재 피로 켬)을 돌리고, arm ai 면 반응 학습 상태(learner.json)를
    다음 날로 넘긴다. arm fsm 은 학습 없이 규칙 FSM 만(비교 기준). 날마다 정답 대비 지표(reaction_ai)를 learn_summary.json 에."""
    import yaml
    from deskmate_hub.learning import load_learning_config
    from tools.life_sim.daygen import make_day
    from tools.life_sim.harness import run_scenario
    from tools.life_sim.scenario import load_scenario
    if args.tofsim:
        os.environ["TOFSIM_ROOT"] = args.tofsim
    out = os.path.join(args.out, f"p{args.person:03d}_{args.arm}" + (f"_d{args.drive}" if args.devices > 1 else ""))
    os.makedirs(os.path.join(out, "days"), exist_ok=True)
    state = os.path.join(out, "learner.json")
    pstate = os.path.join(out, "policy.json")
    if args.arm == "ai" and not args.resume:
        for f in (state, pstate):
            if os.path.exists(f):
                os.remove(f)                               # 첫날은 아무것도 모르는 상태에서
        if args.init_from:                                 # 또는 공통모델에서(life_sim common)
            import shutil
            for name, dst in (("learner.json", state), ("policy.json", pstate)):
                src = os.path.join(args.init_from, name)
                if os.path.exists(src):
                    shutil.copyfile(src, dst)
    from tools.life_sim import daygen as _daygen_mod
    from tools.life_sim.daygen import ROLES
    if args.persona:
        persona = args.persona
    elif args.roles == "cycle":
        persona = ROLES[(args.person - 1) % len(ROLES)]       # 사람 1~6 이 여섯 역할, 7~12 다시 … (24명이면 역할마다 4명)
    else:
        persona = make_day(args.person * 1000 + 1)["persona"]
    azimuths = None
    if args.devices > 1:
        span = float(args.arc_span_deg)
        azimuths = [round(-span + 2 * span * i / (args.devices - 1), 1) for i in range(args.devices)]
        if args.drive is None or not 0 <= args.drive < args.devices:
            raise SystemExit("--devices 를 주면 --drive 0..N-1 (이 실행에서 hub 를 맡는 기기 위치)도 준다")
    lcfg = None
    if args.arm == "ai":
        lcfg = dict(load_learning_config(), enabled=True, state_path=state)
        if args.learn_outputs:
            lcfg["undo_weight"] = 0.0      # 되돌리기는 기기 정책의 벌점으로만 — '안 피곤함' 라벨로 쓰지 않는다
        for kv in args.learning_set or []:
            k, _, v = kv.partition("=")
            lcfg[k.strip()] = yaml.safe_load(v)
    rows: list[dict] = []
    summ_path = os.path.join(out, "learn_summary.json")
    for d in range(1, args.days + 1):
        day = make_day(args.person * 1000 + d, persona=persona,
                       **({"desk_hours": tuple(args.desk_hours)} if args.desk_hours else {}))
        path = os.path.join(out, "days", f"day{d:02d}.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(day, fh, allow_unicode=True, sort_keys=False)
        sc = load_scenario(path)
        sc["person_seed"] = args.person
        sc["seed"] = args.person * 1000 + d
        role_set = list(_daygen_mod.ROLE_INGEST_SET.get(persona, [])) + list(args.ingest_set or [])
        if role_set:
            sc["hub"]["ingest_set"] = list(sc["hub"].get("ingest_set") or []) + role_set   # 역할 프로필(예: 수험생 필기 자세)
        if args.fixed_scene or azimuths:
            sc["scene_seed"] = 500000 + args.person             # 같은 사람 = 날마다 같은 방·책상·체형(·기기 둘레)
        if azimuths:
            sc["placement"], sc["arc_azimuths"], sc["drive_device"] = "arc", azimuths, args.drive
        sc["hub"]["learning"] = lcfg
        # 피로 기록 앱 KSS 질문(15 분) — 두 arm 모두 켠다. 사람에게 효과가 없고 난수도 따로라 arm 비교를 흐리지 않는다.
        # ai arm 에서만 라벨로 쓰인다(learning.yaml kss_label). FSM 규칙에는 들어가지 않는다.
        sc["devices_resolved"].setdefault("self_report", {})["enabled"] = not args.no_self_report
        if args.oracle_noise:
            sc["hub"]["oracle_noise"] = args.oracle_noise
        if args.person_prefs:                               # 더위·어두움에 지치는 정도를 사람마다(덥게 느끼는 온도·가산, 어둡다고 느끼는 조도·가산)
            fz = sc["reaction_resolved"].setdefault("fatigue", {})
            fz["hot"] = {"above_c": [25.0, 29.0], "gain": [0.1, 0.6]}
            fz["dim"] = {"below_lux": [150, 300], "gain": [0.1, 0.5]}
            sc["reaction_resolved"].setdefault("prefs", {})["enabled"] = True     # 기기 호불호(음악·음성·조명 …)
        if args.night_glare and not args.person_prefs:      # 개인 호불호 없이 밤 눈부심(청백색·화면 밝게)만 — 공통모델용 선호 없는 사람
            pr = sc["reaction_resolved"].setdefault("prefs", {})
            pr.update(enabled=True, dislike_p={})
        if args.hr:                                         # 시뮬 mmWave 심박 모델(사람마다 안정 심박, 졸면 하락) — 두 arm 같이
            sc["devices_resolved"].setdefault("mmwave", {}).setdefault("hr_model", {})["enabled"] = True
        if args.learn_outputs and args.arm == "ai":         # 개입 방식(기기) 선택 정책을 사람별로 이어 배움 — ai arm 만
            sc["policy"] = dict(sc.get("policy") or {}, engine="hub", profile="persist", state_path=pstate,
                                set=list(args.policy_set or []))
        src = None
        if args.synthetic:
            from tools.posture_sim.synthetic import SyntheticPerson
            src = SyntheticPerson(sc["segments"], seed=sc["seed"], fps=float(sc["fps"]))
        res = run_scenario(sc, out_dir=os.path.join(out, "days"), model_path=args.model, posture=args.posture, source=src,
                           backend=args.backend, tofsim_root=args.tofsim, label=f"day{d:02d}", progress=False)
        scn = res.get("scene") or {}
        m = dict(res.get("reaction_ai") or {}, day=d, persona=persona, wall_s=res.get("wall_s"),
                 scene={k: scn.get(k) for k in ("body_gender", "body_height_m", "seat_height_m", "radius_m", "devices_azimuth_deg",
                                                "arc_device", "placement_mode", "azimuth_deg", "head_dist_m")},
                 posture=(res.get("posture") or {}),
                 outputs={k: ((res.get("personalize") or {}).get("log") or {}).get(k) for k in ("by_arm", "verdicts", "mean_reward")},
                 traits=dict((res.get("fatigue") or {}).get("params") or {},
                             dislikes=(res.get("reaction_prefs") or {}).get("dislikes")))
        rows.append(m)
        if getattr(args, "compact_logs", False) or os.environ.get("LIFESIM_COMPACT_LOGS"):
            _compact_day(res["run_dir"])
        with open(summ_path, "w", encoding="utf-8") as fh:
            json.dump({"person": args.person, "arm": args.arm, "persona": persona, "drive": args.drive, "azimuths": azimuths,
                       "days": rows}, fh, ensure_ascii=False, indent=1)
        lg = m.get("learning") or {}
        print(f"[learn] p{args.person} {args.arm}{'' if args.drive is None else f' d{args.drive}'} day {d}: 피로 {m.get('fatigue_min')} 분, 구간 {m.get('episodes')} 놓침 {m.get('missed')}, "
              f"첫개입 중앙 {m.get('latency_median_s')} s, 개입 {m.get('interventions')} 헛 {m.get('false_interventions')}, "
              f"확인 {m.get('checkins')}, α {lg.get('alpha')} 라벨 {lg.get('n_labels')}(앱 {lg.get('labels_kss')}) "
              f"맞힘 AI {lg.get('acc_ai')}/FSM {lg.get('acc_fsm')}", flush=True)
    return 0


def cmd_common(args: argparse.Namespace) -> int:
    """learn 실행 폴더들(보통 --persona neutral 의 ai arm)의 learner.json·policy.json 을 공통모델 하나로 합친다."""
    from tools.life_sim.common import build_common, expand, policy_config_for_learn
    dirs = expand(args.runs)
    if not dirs:
        raise SystemExit("합칠 learn 폴더가 없다")
    meta = build_common(dirs, args.out, kappa=args.kappa, policy_cfg=policy_config_for_learn())
    print(f"[common] {args.out}: {json.dumps(meta, ensure_ascii=False)}")
    return 0


def cmd_table(args: argparse.Namespace) -> int:
    paths = [p for pat in args.summary for p in sorted(glob.glob(pat))]
    rows = ["| 실행 | 길이 | FSM 경로 | 개입 | 깨어남 | 환기/명령 | 휴식 | 자세 acc | drowsy 재현(모델/0x03) |",
            "|---|---|---|---|---|---|---|---|---|"]
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            s = json.load(fh)
        dr = (s["posture"]["per_label"].get("drowsy") or {}).get("recall")
        cmds = "; ".join(f"{c['target']}={c['value']}" for c in s["commands"][:4])
        rows.append(f"| {s['persona']}/{s['name']} | {s['duration_s']} s | {' → '.join(s['fsm']['states_seq'])} | "
                    f"{', '.join(iv['kind'] for iv in s['interventions'])} | {len(s['wakes'])} | {cmds or '-'} | "
                    f"{len(s['rests'])} | {s['posture']['acc_sec']:.2f} | {dr} / {s['posture']['drowsy_flag_recall_0x03']} |")
    print("\n".join(rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    from tools.life_sim import daygen as _daygen
    ap = argparse.ArgumentParser(prog="life_sim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("scenario", nargs="+")
    r.add_argument("--out", default="runs/lifesim")
    r.add_argument("--model", help="PostureNet 체크포인트(.pt). 없으면 --posture oracle")
    r.add_argument("--posture", choices=["gru", "oracle"], default="gru")
    r.add_argument("--synthetic", action="store_true", help="tofsim 대신 합성 격자(시험용)")
    r.add_argument("--backend", choices=["mujoco", "numpy"])
    r.add_argument("--tofsim", help="tofsim 루트(TOFSIM_ROOT)")
    r.add_argument("--fsm-config")
    r.add_argument("--seed", type=int)
    r.add_argument("--label")
    r.add_argument("--replay", action="store_true", help="프레임마다 Pose·격자·판정을 replay.jsonl 로(video 명령용, 실행당 ~20 MB)")
    r.add_argument("--presence", choices=["mmwave", "any"], help="hub 재실 판정: mmwave(우선, 기본 설정) | any(둘 중 하나, 이전 동작)")
    r.add_argument("--room-random", action="store_true", help="사용 환경(천장등·일광률·방 크기·무드등 세기)을 시드마다 뽑는다(devices.yaml room.randomize_ranges)")
    r.add_argument("--desk-max-cm", type=float, help="책상 재실 거리 상한(ingest.yaml desk_max_cm 덮어쓰기, 민감도 실험)")
    r.add_argument("--ingest-set", action="append", metavar="KEY=VALUE",
                   help="ingest.yaml 값 덮어쓰기(점 경로, 값은 YAML). 예: elapsed.reset_on_rest=true. 여러 번 줄 수 있다")
    r.add_argument("--fsm-set", action="append", metavar="KEY=VALUE",
                   help="fsm.yaml 값 덮어쓰기(점 경로, 값은 YAML). 예: timers.fatigue_hold_min_frac=0.8. 여러 번 줄 수 있다")
    r.add_argument("--self-report", action="store_true",
                   help="피로 기록 앱 KSS 질문 켜기(devices.yaml self_report — 15 분마다 묻고 졸림 S 로 답함, --fatigue 필요). "
                        "응답은 반응 학습 라벨(learning.yaml kss_label) — FSM 규칙에는 안 들어간다")
    r.add_argument("--vent-rule", action="store_true",
                   help="CO₂ 환기 타이밍 규칙 켜기(devices.yaml vent_control — FSM 밖, 깨어 있을 때 창문 환기 카드)")
    r.add_argument("--fatigue", action="store_true",
                   help="잠재 피로 켜기(reaction.yaml fatigue — 졸음·자세 무너짐·키 입력 저하가 피로 F 에서 생기고 정답 라벨을 남김)")
    r.add_argument("--stage2", metavar="DIR",
                   help="2단계 피로 모델 portable 폴더(common.portable.json·common.metadata.json) — hub 관찰 모드로 매 tick 판정")
    r.add_argument("--policy-engine", choices=["hub", "simple", "none"], help="각본의 policy.engine 덮어쓰기")
    r.add_argument("--policy-profile", choices=["none", "synth", "global"], help="각본의 policy.profile 덮어쓰기")
    r.add_argument("--raise-errors", action="store_true")
    r.set_defaults(fn=cmd_run)
    v = sub.add_parser("video", help="replay.jsonl 로 MuJoCo 3D + 센서 격자 + 상태 영상(mp4)")
    v.add_argument("run_dir")
    v.add_argument("--out", help="mp4 경로(기본 <run_dir>/video.mp4)")
    v.add_argument("--speed", type=float, default=10.0, help="재생 배속(기본 10: 1 시간 각본 → 6 분)")
    v.add_argument("--fps", type=int, default=20)
    v.add_argument("--start", type=float, default=0.0, help="각본 시작 기준 몇 초부터")
    v.add_argument("--seconds", type=float, help="몇 초 분량만")
    v.add_argument("--tofsim")
    v.add_argument("--azimuth", type=float)
    v.add_argument("--elevation", type=float)
    v.add_argument("--distance", type=float)
    v.set_defaults(fn=cmd_video)
    a = sub.add_parser("ab")
    a.add_argument("scenario", nargs="+")
    a.add_argument("--out", default="runs/lifesim")
    a.add_argument("--model")
    a.add_argument("--posture", choices=["gru", "oracle"], default="gru")
    a.add_argument("--synthetic", action="store_true")
    a.add_argument("--backend", choices=["mujoco", "numpy"])
    a.add_argument("--tofsim")
    a.add_argument("--seed", type=int)
    a.add_argument("--seeds", type=int, default=1, help="시드 수(기본 시드부터 연속). A/B 는 같은 시드 집합을 쓴다")
    a.add_argument("--raise-errors", action="store_true")
    a.set_defaults(fn=cmd_ab)
    rp = sub.add_parser("replot")
    rp.add_argument("run_dir", nargs="+")
    rp.set_defaults(fn=cmd_replot)
    pl = sub.add_parser("play", help="video 와 같은 화면(3D+기기+센서 격자+상태)을 창에서 실시간 재생(PC)")
    pl.add_argument("run_dir")
    pl.add_argument("--speed", type=float, default=6.0)
    pl.add_argument("--fps", type=int, default=10)
    pl.add_argument("--start", type=float, default=0.0)
    pl.add_argument("--seconds", type=float)
    pl.add_argument("--once", action="store_true")
    pl.add_argument("--tofsim")
    pl.add_argument("--azimuth", type=float)
    pl.add_argument("--elevation", type=float)
    pl.add_argument("--distance", type=float)
    pl.set_defaults(fn=cmd_play)
    vw = sub.add_parser("viewer", help="MuJoCo 뷰어 창에서 replay 를 실시간 재생(PC)")
    vw.add_argument("run_dir")
    vw.add_argument("--speed", type=float, default=4.0)
    vw.add_argument("--start", type=float, default=0.0)
    vw.add_argument("--once", action="store_true")
    vw.add_argument("--tofsim")
    vw.set_defaults(fn=cmd_viewer)
    t = sub.add_parser("table")
    t.add_argument("summary", nargs="+")
    t.set_defaults(fn=cmd_table)
    dg = sub.add_parser("daygen", help="자유 생활 하루 각본(잠재 피로 켬) — 2단계 피로 모델 학습 데이터용")
    dg.add_argument("--seeds", required=True, help="예: 1-120 또는 1,5,9-12")
    dg.add_argument("--out", required=True)
    dg.add_argument("--desk-min-h", type=float, default=2.0)
    dg.add_argument("--desk-max-h", type=float, default=3.5)
    dg.add_argument("--vent-rule-p", type=float, default=0.5, help="CO₂ 환기 규칙을 켤 하루의 비율")
    dg.set_defaults(fn=cmd_daygen)
    ln = sub.add_parser("learn", help="한 사람 × 여러 날: FSM 만(fsm) vs 사용자 반응 학습(ai) — 정답(잠재 피로) 대비 지표")
    ln.add_argument("--person", type=int, required=True, help="사람 번호(피로 계수·유형이 날마다 같다)")
    ln.add_argument("--days", type=int, default=14)
    ln.add_argument("--arm", choices=["fsm", "ai"], required=True)
    ln.add_argument("--persona", choices=sorted(set(_daygen.PERSONAS) | set(_daygen.EXTRA_ROLES)),
                    help="사람 유형 고정(역할 6가지 · neutral = 공통모델용 선호 없는 사람 · book_examinee·pc_student = 시연용)")
    ln.add_argument("--out", default="runs/learn")
    ln.add_argument("--model")
    ln.add_argument("--posture", choices=["gru", "oracle"], default="gru")
    ln.add_argument("--synthetic", action="store_true", help="tofsim 대신 합성 격자(빠름)")
    ln.add_argument("--oracle-noise", type=float, default=0.0, help="오라클 자세 판정을 이 확률로 틀리게(GRU 깜빡임 흉내)")
    ln.add_argument("--backend", choices=["mujoco", "numpy"])
    ln.add_argument("--tofsim")
    ln.add_argument("--compact-logs", action="store_true", help="하루가 끝나면 그날 jsonl 을 gzip(디스크 아끼기)")
    ln.add_argument("--resume", action="store_true", help="learner.json 을 지우지 않고 이어서")
    ln.add_argument("--learning-set", action="append", metavar="KEY=VALUE", help="learning.yaml 값 덮어쓰기(여러 번)")
    ln.add_argument("--no-self-report", action="store_true", help="피로 기록 앱 KSS 질문 끄기(라벨은 개입 반응·확인 카드만)")
    ln.add_argument("--roles", choices=["draw", "cycle"], default="draw",
                    help="draw: 사람마다 세 유형 중 뽑기(이전) / cycle: 여섯 역할(학생·개발자·수험생·디자이너·작가·연구자)을 사람 번호로 돌림")
    ln.add_argument("--fixed-scene", action="store_true", help="tofsim: 같은 사람이면 날마다 같은 방·책상·체형")
    ln.add_argument("--devices", type=int, default=1,
                    help="tofsim: 사람 둘레 호 위 기기 위치 수(>1 이면 --drive 위치의 기기 1대로 돈다, 방·체형·호 반지름은 위치끼리 같다)")
    ln.add_argument("--drive", type=int, help="--devices 중 이 실행의 기기 위치 번호(0 = 가장 오른쪽 −span°)")
    ln.add_argument("--arc-span-deg", type=float, default=40.0, help="--devices 위치를 −span~+span 에 고르게")
    ln.add_argument("--desk-hours", type=float, nargs=2, metavar=("LO", "HI"), help="하루 책상 시간 범위(시험용으로 짧게)")
    ln.add_argument("--ingest-set", action="append", metavar="KEY=VALUE", help="ingest.yaml 값 덮어쓰기(여러 번, 역할 프로필 뒤에 붙음)")
    ln.add_argument("--policy-set", action="append", metavar="KEY=VALUE",
                    help="--learn-outputs 정책 설정 덮어쓰기(personalize.yaml 점 경로, 예: bandit.weight_effect=0.8)")
    ln.add_argument("--init-from", help="공통모델 폴더(life_sim common 출력)의 learner.json·policy.json 에서 출발(ai arm)")
    ln.add_argument("--person-prefs", action="store_true",
                    help="사람마다 선호: 더위·어두움에 지치는 정도(덥다고 느끼는 온도 25~29 °C, 어둡다고 느끼는 조도 150~300 lx)와 "
                         "기기 호불호(음악·음성·알림음·차가운 조명·강풍·화면 밝기 — 싫으면 덜 깨고 자동이면 끔)")
    ln.add_argument("--night-glare", action="store_true", help="개인 호불호 없이 밤 눈부심 반응만 켠다(공통모델용 neutral)")
    ln.add_argument("--hr", action="store_true", help="시뮬 mmWave 심박 모델 켜기(두 arm) — ai arm 은 재실 기준 심박 하락을 입력으로 쓴다")
    ln.add_argument("--learn-outputs", action="store_true",
                    help="ai arm: 개입 방식(스피커·무드등·선풍기·공기청정기·화면 밝기·카드) 선택 정책을 사람별로 이어 배움(hub personalize, profile persist)")
    ln.set_defaults(fn=cmd_learn)
    cm = sub.add_parser("common", help="learn 실행들(선호 없는 사람)의 학습 상태를 공통모델 하나로 합친다")
    cm.add_argument("--runs", nargs="+", required=True, help="learn 출력 폴더 glob(예: runs/common/p*_ai*)")
    cm.add_argument("--out", required=True)
    cm.add_argument("--kappa", type=float, default=0.2, help="공통모델 무게(정책 사후분포 합칠 때·AdaGrad 누적 줄이는 배수)")
    cm.set_defaults(fn=cmd_common)
    args = ap.parse_args(argv)
    if args.cmd in ("run", "ab") and args.posture == "gru" and not args.model:
        args.posture = "oracle"
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
