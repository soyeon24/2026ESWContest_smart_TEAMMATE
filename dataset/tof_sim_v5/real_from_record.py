"""Recorded ToF lines -> the `--real` npz that train.py and evaluate score, and a quick model score on it.

    python real_from_record.py --labels real_protocol_v1.csv --out runs/real_20261015_a.npz rec.jsonl
    python real_from_record.py --labels real_protocol_v1.csv --out runs/real_a.npz rec.jsonl@COM5 rec.jsonl@COM6
    python real_from_record.py --out runs/replay.npz replay_s0.jsonl replay_s1.jsonl     # sim replays carry "label"
    python real_from_record.py --score ../tof-sim_ubai_random/export_20261014_2206_best/posture_net.pt runs/real_20261015_a.npz
    python real_from_record.py --score pc/posture_net.pt pc/posture_net_opt_ft_c128.pt -- runs/real_a.npz   # several models, same npz
    python train.py --run ... --real runs/real_20261015_a.npz                                  # scored at every eval

Inputs are `tof_live.py --record` files. Its lines are wrapped as {"host_t": <epoch s>, "port": "COM5", "raw": "<line>"};
every port in a file becomes its own sensor, sorted by port name (`file@COM5` takes that port only).
Unwrapped lines (older recordings, tools/sim_to_toflines.py) are one sensor per file. The firmware line formats are
read with the same parser as tof_live.py: bring-up CSV `F,<ms>,<64 distances>[,<64 status>]`, tof_logger JSON, and
(2026-10-21) firmware main's USB 'z' line {"t":"tof_grid",...,"s":[{"d","st"}|null, ...]} — two sensors on one port,
which become two sensors named `<file>@<PORT>#s0` / `#s1` (physical sensor A / B). Its grid is already oriented by the
firmware (flags = transforms it applied), so --flip-* are extra flips on top, as in tof_live.py.
(2026-10-26) Pi 4 board polling: lines holding the posture service's / relay's `GET /raw` JSON
({"sensors":[{"id","have","ts_ms","frame_seq","flags","dist_mm":[64],"status":[64]},…]}), either as the line itself
(with an optional top-level "host_t") or wrapped as {"host_t":…, "raw": <that object or its text>}. Each sensor id becomes
`<port or raw>#s<id>`, a frame polled twice (same ts_ms) is kept once, and the grid is taken as received — the
standard 0x05 grid is already oriented by the firmware (same as the 'z' line), so no flip unless --flip-* says so.

Frames are taken the way the Pi 4 service takes them: every 100 ms the newest frame (the bring-up firmware ranges at
15 Hz, main sends 5 Hz per sensor so each frame is used twice; the model runs at 10 Hz). A gap of more than 1 s or a
clock going backwards starts a new session, as the service then restarts the model state.

Labels come from a per-line "label" field (sim replays) or from --labels, a CSV `start_s,end_s,label[,what]`
(label = a name in tofsim.session.LABELS, or "skip" / "transition"). Its times are seconds from --t0 (the
protocol_start_*.txt that protocol_timer.py writes, or an epoch time), else from the start of the recording (the
earliest host time over all inputs when the lines carry one, else the first frame of each sensor).
Unlabelled time and --margin s on either side of every label change are flagged as transitions, which evaluate
does not score.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from tof_live import Source, orient  # noqa: E402  same line parser and grid orientation as the live runner
from tofsim.session import FLAG_TRANSITION, LABELS  # noqa: E402

TICK_MS = 100            # the model's frame period (10 Hz)
GAP_MS = 1000            # silence that restarts the model state on the board


def split_arg(arg: str):
    """'rec.jsonl@COM5' -> ('rec.jsonl', 'COM5'); a plain path -> (path, None)."""
    if "@" in arg and not os.path.exists(arg):
        path, port = arg.rsplit("@", 1)
        return path, port
    return arg, None


def raw_http_frames(obj: dict):
    """Pi 4 자세 서비스(atlas-tof, TOFPOSTURE_RAW_HTTP)·uart_relay_board 의 `GET /raw` JSON 하나 → [(센서 id, ms, dist, status)].
    격자는 받은 그대로다. 표준 0x05 는 펌웨어가 flags(b0 flip_rows, b1 flip_cols)대로 이미 돌려 보낸 배치이고, 이것이 모델 입력
    방향이다(펌웨어 USB 'z' 줄과 같다). 그래서 여기서는 더 뒤집지 않고, --flip-* 만 그 위에 더한다. 없음 = -1·0.
    시각은 센서 프레임의 ts_ms(보드 단조 시계), 없으면 uart_seq·frame_seq 순서를 100 ms 로 본다."""
    out = []
    for s in obj.get("sensors") or []:
        if not s.get("have") or len(s.get("dist_mm") or []) != 64:
            continue
        ms = s.get("ts_ms")
        if ms is None:
            ms = 100 * int(s.get("uart_seq") or s.get("frame_seq") or 0)
        st = s.get("status") or [5] * 64
        out.append((int(s.get("id", 0)), int(ms), np.asarray(s["dist_mm"], np.int16).reshape(8, 8),
                    np.asarray(st, np.uint8).reshape(8, 8)))
    return out


def read_sensors(path: str, port_filter, flip_rows: bool, flip_cols: bool):
    """{port: [(ms, dist[8,8] int16, status[8,8] uint8, label or None, host_t or None)]}, has_status, first host_t.
    Ports keep the order they first appear in; unwrapped lines go under the port None. The first host time is over
    every wrapped line of the file, whatever the port filter: it is when the recording started."""
    sensors, has_status, first_host = {}, True, None
    with open(path, encoding="utf-8", errors="replace") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            port, host_t = None, None
            if line.startswith('{"host_t"'):
                try:
                    w = json.loads(line)
                except ValueError:
                    continue
                port, host_t, line = w.get("port"), w.get("host_t"), w.get("raw", w if "sensors" in w else "")
                if host_t is not None and (first_host is None or host_t < first_host):
                    first_host = host_t
            if port_filter is not None and port != port_filter:
                continue
            raw_http = line if isinstance(line, dict) else None
            if raw_http is None and isinstance(line, str) and line.startswith("{") and '"dist_mm"' in line:
                try:
                    raw_http = json.loads(line)
                except ValueError:
                    raw_http = None
            if raw_http is not None and "sensors" in raw_http:
                if host_t is None and raw_http.get("host_t") is not None:
                    host_t = raw_http["host_t"]
                    if first_host is None or host_t < first_host:
                        first_host = host_t
                for sid, ms, d, st in raw_http_frames(raw_http):
                    key = f"{port or 'raw'}#s{sid}"
                    prev = sensors.get(key)
                    if prev and prev[-1][0] == ms:
                        continue                                         # 폴링(10 Hz)이 같은 프레임(센서 5 Hz)을 또 읽음
                    d = orient(d, flip_rows, flip_cols)
                    st = orient(st, flip_rows, flip_cols)
                    d = np.where(d > 0, d, -1).astype(np.int16)
                    sensors.setdefault(key, []).append((ms, d, st, None, host_t))
                continue
            if not isinstance(line, str):
                continue
            obj = Source._parse(line)
            if not obj or obj.get("t") != "tof" or len(obj.get("d", [])) != 64 or len(obj.get("st", [])) != 64:
                continue
            # firmware main's USB {"t":"tof_grid"} carries both sensors in one line: one sensor each, keyed PORT#s<i>
            for f in obj.get("frames") or [obj]:
                if f.get("has_status") is False:
                    has_status = False
                d = orient(np.asarray(f["d"], np.int16).reshape(8, 8), flip_rows, flip_cols)
                st = orient(np.asarray(f["st"], np.uint8).reshape(8, 8), flip_rows, flip_cols)
                d = np.where(d > 0, d, -1).astype(np.int16)          # the npz convention: no target = -1
                key = port if f.get("sensor") is None else f"{port or ''}#s{f['sensor']}"
                sensors.setdefault(key, []).append((int(f["ms"]), d, st, f.get("label"), host_t))
    return sensors, has_status, first_host


def split_runs(frames):
    """Cut where the clock goes backwards or the sensor was silent for more than GAP_MS."""
    runs, cur = [], []
    for f in frames:
        if cur and (f[0] < cur[-1][0] or f[0] - cur[-1][0] > GAP_MS):
            runs.append(cur)
            cur = []
        cur.append(f)
    if cur:
        runs.append(cur)
    return runs


def resample(run):
    """Newest frame at every 100 ms tick from the first frame: [(t_s from the run start, frame)]."""
    ms0, ms1 = run[0][0], run[-1][0]
    out, j = [], 0
    for k in range((ms1 - ms0) // TICK_MS + 1):
        t = ms0 + k * TICK_MS
        while j + 1 < len(run) and run[j + 1][0] <= t:
            j += 1
        out.append(((t - ms0) / 1000.0, run[j]))
    return out


def read_labels(path: str):
    rows = []
    with open(path, encoding="utf-8-sig") as fp:
        for r in csv.reader(fp):
            if not r or r[0].strip().startswith("#") or r[0].strip() == "start_s":
                continue
            a, b, name = float(r[0]), float(r[1]), r[2].strip()
            name = "skip" if name == "transition" else name
            if name != "skip" and name not in LABELS:
                sys.exit(f"{path}: unknown label {name!r} (use one of {LABELS} or skip)")
            rows.append((a, b, name))
    return sorted(rows)


def label_frames(times, line_labels, rows, margin):
    """label int8 [T], flags uint8 [T]; `times` in the label file's seconds."""
    T = len(times)
    y = np.zeros(T, np.int8)
    known = np.zeros(T, bool)
    t = np.asarray(times)
    if rows is None:
        for i, name in enumerate(line_labels):
            if name in LABELS:
                y[i], known[i] = LABELS.index(name), True
    else:
        for a, b, name in rows:
            m = (t >= a) & (t < b)
            if name != "skip":
                y[m], known[m] = LABELS.index(name), True
            else:
                known[m] = False
    flags = np.where(known, 0, FLAG_TRANSITION).astype(np.uint8)
    if margin > 0:                                    # around every change of label, the operator's timing is loose
        for i in np.nonzero(np.diff(y.astype(int)) != 0)[0]:
            flags[np.abs(t - t[i + 1]) <= margin] |= FLAG_TRANSITION
    return y, flags


def read_t0(arg: str) -> float:
    """An epoch time, or the first line of protocol_timer.py's protocol_start_*.txt."""
    if os.path.exists(arg):
        with open(arg, encoding="utf-8") as fp:
            return float(fp.readline().split()[0])
    return float(arg)


def convert(args):
    rows = read_labels(args.labels) if args.labels else None
    sensors, starts_host = [], []                      # (name, frames), each file's recording start
    for arg in args.files:
        path, port_filter = split_arg(arg)
        got, has_status, first_host = read_sensors(path, port_filter, args.flip_rows, args.flip_cols)
        starts_host.append(first_host)
        if not got:
            print(f"{arg}: no frames")
        if got and not has_status:
            print(f"{arg}: the firmware sent no status values; valid = distance > 0 (the model was trained on status)")
        for port, frames in sorted(got.items(), key=lambda kv: str(kv[0])):
            sensors.append((os.path.basename(path) + (f"@{port}" if port else ""), frames))
    runs = [(name, r, run) for name, frames in sensors for r, run in enumerate(split_runs(frames)) if len(run) >= 2]
    if not runs:
        sys.exit("nothing converted")
    with_host = all(run[0][4] is not None for _, _, run in runs)
    T0 = min(h for h in starts_host if h is not None) if with_host else None
    if args.t0:
        if not with_host:
            sys.exit("--t0 needs recordings with host times (tof_live.py --record of 2026-10-15 or later)")
        T0 = read_t0(args.t0)
        print(f"label times from --t0 ({T0:.3f}; the recording started {min(h for h in starts_host if h is not None) - T0:+.1f} s from it)")
    else:
        print("label times from " + ("the recording start (host clock)" if with_host else "each sensor's first frame"))
    dists, stats, ys, fls, starts, names, host0 = [], [], [], [], [], [], []
    pos = 0
    for name, r, run in runs:
        samp = resample(run)
        off = (run[0][4] - T0) if with_host else 0.0
        times = [t + off for t, _ in samp]
        if rows is None and not any(f[3] for _, f in samp):
            sys.exit(f"{name}: no per-line labels; give --labels")
        y, fl = label_frames(times, [f[3] for _, f in samp], rows, args.margin)
        dists.append(np.stack([f[1] for _, f in samp]))
        stats.append(np.stack([f[2] for _, f in samp]))
        ys.append(y); fls.append(fl); starts.append(pos); names.append(f"{name}#{r}")
        host0.append(run[0][4] if with_host else np.nan)
        pos += len(y)
        kept = (fl & FLAG_TRANSITION) == 0
        share = {LABELS[i]: round(float(np.mean(y[kept] == i)), 3) for i in np.unique(y[kept])}
        hz = (len(run) - 1) / max(1e-6, (run[-1][0] - run[0][0]) / 1000.0)
        print(f"{names[-1]}: {len(run)} frames at {hz:.1f} Hz from t={off:.1f} s -> {len(y)} at 10 Hz ({len(y) / 10:.0f} s), "
              f"scored {kept.sum()} | label share {share}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    np.savez_compressed(args.out, dist=np.concatenate(dists), status=np.concatenate(stats), label=np.concatenate(ys),
                        flags=np.concatenate(fls), starts=np.array(starts), labels=np.array(LABELS),
                        sources=np.array(names), session_host_t0=np.array(host0, dtype=np.float64))
    print(f"-> {args.out}: {pos} frames, {len(starts)} sessions")


def score(args):
    for path in args.score:
        score_one(path, args.files[0])


def score_one(model_path: str, npz_path: str):
    import torch

    from tofsim.data import to_input
    from tofsim.evaluate import evaluate, format_eval
    from tofsim.model import PostureNet

    ck = torch.load(model_path, map_location="cpu", weights_only=False)
    sd = ck.get("model") or ck.get("state_dict")
    labels = list(ck.get("labels", LABELS))
    net = PostureNet(8, 8, len(labels), hidden=int(sd["gru.weight_hh_l0"].shape[1]))
    net.load_state_dict(sd)
    net.eval()
    with np.load(npz_path, allow_pickle=False) as z:
        data = {k: z[k] for k in z.files}
    if "forward_head" in LABELS and "forward_head" not in labels:
        # a model without forward_head can do no better than "upright" there: score it that way
        data["label"] = np.where(data["label"] == LABELS.index("forward_head"), LABELS.index("upright"), data["label"])
    names = [str(s) for s in data.get("sources", [])]
    print(f"model {model_path}: {len(labels)} labels, hidden {net.gru.hidden_size}")
    print("per sensor:", format_eval(evaluate(net, data)))
    starts = list(data["starts"]) + [len(data["label"])]
    n = len(starts) - 1
    # the board's fusion (sum of log-probabilities) over the two sensors of the same stretch of time. Two sessions: those
    # two. More: sessions are paired by their run number (the "#<r>" convert() appends: a gap or reboot cut both sensors
    # at the same place), so rec@s0#1 goes with rec@s1#1.
    if n == 2:
        pairs = [(0, 1)]
    else:
        runs = {}
        for i, nm in enumerate(names[:n]):
            runs.setdefault(nm.rsplit("#", 1)[1] if "#" in nm else "", []).append(i)
        pairs = [tuple(v) for _, v in sorted(runs.items()) if len(v) == 2]
    if not pairs:
        return
    h0all = data.get("session_host_t0", np.full(n, np.nan))
    P, Y = [], []
    for i, j in pairs:
        h0 = np.array([h0all[i], h0all[j]])
        shift = int(round((h0[1] - h0[0]) * 10)) if np.all(np.isfinite(h0)) else 0     # frames sensor j starts later
        a0, b0 = starts[i] + max(0, shift), starts[j] + max(0, -shift)
        T = min(starts[i + 1] - a0, starts[j + 1] - b0)
        if T <= 45:
            print(f"both sensors ({names[i]} + {names[j]}): too little overlap to fuse")
            continue
        logp = []
        with torch.no_grad():
            for s0, s in ((starts[i], a0), (starts[j], b0)):        # run each from its own start, keep the overlap
                x = torch.from_numpy(to_input(data["dist"][s0:s + T], data["status"][s0:s + T]))[None]
                logp.append(torch.log_softmax(net(x)[0][0], -1).numpy()[s - s0:])
        pred = (logp[0] + logp[1]).argmax(-1)
        y = data["label"][a0:a0 + T].astype(int)
        keep = ((data["flags"][a0:a0 + T] | data["flags"][b0:b0 + T]) & FLAG_TRANSITION) == 0
        keep[:45] = False
        acc = float((pred[keep] == y[keep]).mean()) if keep.any() else float("nan")
        rec = {LABELS[c]: round(float((pred[keep & (y == c)] == c).mean()), 2) for c in np.unique(y[keep])}
        print(f"both sensors ({names[i]} + {names[j]}, offset {shift} frames): acc {acc:.3f} | recall {rec}")
        P.append(pred[keep]); Y.append(y[keep])
    if len(P) > 1:
        p, y = np.concatenate(P), np.concatenate(Y)
        f1 = []
        for c in np.unique(y):
            tp = float(np.sum((p == c) & (y == c)))
            f1.append(2 * tp / max(1.0, float(np.sum(p == c) + np.sum(y == c))))
        rec = {LABELS[c]: round(float((p[y == c] == c).mean()), 2) for c in np.unique(y)}
        print(f"both sensors, all {len(P)} pairs: acc {float((p == y).mean()):.3f} macroF1 {float(np.mean(f1)):.3f} | recall {rec}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="recorded line files (file or file@PORT), or with --score one npz")
    ap.add_argument("--out", help="npz to write")
    ap.add_argument("--labels", help="CSV start_s,end_s,label[,what], seconds from the start of the recording")
    ap.add_argument("--margin", type=float, default=2.0, help="seconds around each label change left unscored")
    ap.add_argument("--t0", help="protocol_start_*.txt from protocol_timer.py (or an epoch time): label time zero")
    ap.add_argument("--flip-rows", action="store_true", help="as tof_live.py --flip-rows")
    ap.add_argument("--flip-cols", action="store_true", help="as tof_live.py --flip-cols")
    ap.add_argument("--score", nargs="+", help="checkpoint(s) or export posture_net.pt to score on the npz given as the file "
                    "(several: each is scored in turn; end the list with -- before the npz)")
    args = ap.parse_args()
    if args.score:
        score(args)
    elif args.out:
        convert(args)
    else:
        ap.error("give --out (convert) or --score (score an npz)")


if __name__ == "__main__":
    main()
