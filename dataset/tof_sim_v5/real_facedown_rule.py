"""Demo-only face_down rule on the raw 8x8 geometry of the two device sensors (2026-10-26, left placement).

Why: at the fixed device tilt (CAD 20 deg up, sensors 0.13 m above the desk) and the user's real face-down position,
the posture model (opt_l8_c256) never reads face_down on the board: P(face_down) <= 0.005 at a natural distance,
<= 0.57 with the head 25-35 cm away. The rule reads the body position straight from the grid instead.
This is the reference the board posture service (deskmate_tofposture, C++) is matched to.

Input: the two grids as the board's /raw gives them (already oriented by the firmware 0x05 flags: row 0 = top),
A = sensor 0, B = sensor 1, evaluated once per frame pair (both sensors carry the same ts_ms, 5 Hz).

Per frame ("near" cell = status 5 or 9 and 150 < d < 1200 mm):
  up    near cells in rows 0..3, A + B
  lo    near cells in rows 4..7, A + B
  topA  first row of A with >= 2 near cells (8 if none); topB the same for B
  dlo   median distance (m) of the near cells in rows 4..7, A and B pooled (numpy median: mean of the middle two
        when the count is even); undefined when there are none
  dup   the same for rows 0..3
  flag  (low body)  up <= 4 and lo >= 26 and dlo <= 0.60 and topA >= 4 and topB >= 4
        (near body) lo >= 30 and dlo <= 0.40 and (no upper near cell or dup <= 0.45)
Decision: share of flagged frames among the frames of the last 4.0 s (t >= now - 4.0, the current one included);
face_down turns on at share >= 0.7 and stays on while share >= 0.4.

Optional upright substitution (separate switch): "seated" = up >= 8 and topA <= 3 and topB <= 3. When face_down is
off, the model says misplaced and the frame is seated, report upright.

Checked on the 10-26 left recordings (fork data/real-20261026; frames on their own ESP clock, 2 s cut at each step
edge): face_down steps 100 % in left1, left2 and left2_facedown, on 2.0-2.2 s after the step prompt;
check_close30 face-down stretches 100 %, its sitting stretch 0 %. False face_down in every other labelled step 0 %
(upright, lean_forward incl. writing, forward_head, recline, chin_rest, drowsy, away); left1 step 11 ("upright",
710-740 s) reads 100 % because the user lay face down there.
  One person, one placement (about 0.65 m), one day: dlo <= 0.60 m is a distance for this setup (face-down
  0.45-0.56 m, recline 0.71-0.74 m). Re-check with tools/aim_check.py if the demo desk or chair changes.

    python real_facedown_rule.py rec_raw.jsonl [--labels labels.csv --t0 protocol_start.txt] [--csv frames.csv]

--csv writes every evaluated frame (t, features, flag, on, seated) as the golden file for the C++ port.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import deque
from dataclasses import dataclass

import numpy as np

NEAR_STATUS = (5, 9)


@dataclass
class RuleParams:
    near_min_mm: float = 150.0
    near_max_mm: float = 1200.0
    up_max: int = 4             # low body: at most this many near cells in rows 0..3
    lo_min: int = 26            # low body: at least this many near cells in rows 4..7
    dlo_max_m: float = 0.60     # low body: lower body this close
    top_min: int = 4            # low body: no row above this one holds >= 2 near cells, in A and in B
    near_lo_min: int = 30       # near body
    near_dlo_max_m: float = 0.40
    near_dup_max_m: float = 0.45
    window_s: float = 4.0
    on_share: float = 0.7
    off_share: float = 0.4
    seated_up_min: int = 8      # upright substitution
    seated_top_max: int = 3


def features(dist_a, status_a, dist_b, status_b, p: RuleParams = RuleParams()) -> dict:
    """Per-frame features of the two 8x8 grids (row 0 = top)."""
    out = {}
    nears, dists = [], []
    for d, s in ((dist_a, status_a), (dist_b, status_b)):
        d = np.asarray(d, dtype=np.int32).reshape(8, 8)
        s = np.asarray(s, dtype=np.int32).reshape(8, 8)
        nears.append(np.isin(s, NEAR_STATUS) & (d > p.near_min_mm) & (d < p.near_max_mm))
        dists.append(d)
    (na, nb), (da, db) = nears, dists
    ra, rb = na.sum(1), nb.sum(1)
    out["up"] = int(ra[:4].sum() + rb[:4].sum())
    out["lo"] = int(ra[4:].sum() + rb[4:].sum())
    out["topA"] = int(np.argmax(ra >= 2)) if (ra >= 2).any() else 8
    out["topB"] = int(np.argmax(rb >= 2)) if (rb >= 2).any() else 8
    lo_d = np.r_[da[4:][na[4:]], db[4:][nb[4:]]]
    up_d = np.r_[da[:4][na[:4]], db[:4][nb[:4]]]
    out["dlo"] = float(np.median(lo_d)) / 1000.0 if lo_d.size else None
    out["dup"] = float(np.median(up_d)) / 1000.0 if up_d.size else None
    return out


def frame_flag(f: dict, p: RuleParams = RuleParams()) -> bool:
    dlo = f["dlo"]
    if dlo is None:
        return False
    low = (f["up"] <= p.up_max and f["lo"] >= p.lo_min and dlo <= p.dlo_max_m
           and f["topA"] >= p.top_min and f["topB"] >= p.top_min)
    near = f["lo"] >= p.near_lo_min and dlo <= p.near_dlo_max_m and (f["dup"] is None or f["dup"] <= p.near_dup_max_m)
    return bool(low or near)


def seated(f: dict, p: RuleParams = RuleParams()) -> bool:
    return f["up"] >= p.seated_up_min and f["topA"] <= p.seated_top_max and f["topB"] <= p.seated_top_max


class FaceDownRule:
    """Feed one frame pair at a time: `update(t_s, dist_a, status_a, dist_b, status_b)` -> dict with `on`."""

    def __init__(self, p: RuleParams = RuleParams()):
        self.p = p
        self.win: deque[tuple[float, bool]] = deque()
        self.on = False

    def reset(self) -> None:
        self.win.clear()
        self.on = False

    def update(self, t_s: float, dist_a, status_a, dist_b, status_b) -> dict:
        f = features(dist_a, status_a, dist_b, status_b, self.p)
        flag = frame_flag(f, self.p)
        self.win.append((t_s, flag))
        while self.win[0][0] < t_s - self.p.window_s:
            self.win.popleft()
        share = sum(1 for _, x in self.win if x) / len(self.win)
        self.on = share >= (self.p.off_share if self.on else self.p.on_share)
        return dict(f, flag=flag, share=share, on=self.on, seated=seated(f, self.p))


def read_raw(path: str):
    """record_board.py rec_raw.jsonl -> (pairs [(ts_ms, (dA, sA), (dB, sB))] in time order, board states, offsets).

    Two clocks: /raw ts_ms is the ESP32's millis, /api/state ts_ms the Pi service's; on 10-26 they were ~11 s apart.
    offsets = {"raw": host - ESP ms / 1000 (from each frame's poll time minus its age), "state": host - Pi ms / 1000}."""
    fr = {0: {}, 1: {}}
    states = []
    raw_off = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            if o.get("kind") == "raw":
                s = o["sensor"]
                if s.get("have") and len(s.get("dist_mm") or []) == 64:
                    fr[s["id"]][int(s["ts_ms"])] = ([-1 if v is None else v for v in s["dist_mm"]],
                                                     [255 if v is None else v for v in s["status"]])
                    raw_off.append(o["host_t"] - (int(s["ts_ms"]) + float(s.get("age_ms") or 0)) / 1000.0)
            elif o.get("kind") == "state":
                st = o["state"]
                states.append((o["host_t"], int(st["ts_ms"]), st.get("posture") or ""))
    pairs = [(t, fr[0][t], fr[1][t]) for t in sorted(set(fr[0]) & set(fr[1]))]
    offsets = {"raw": float(np.median(raw_off)) if raw_off else 0.0,
               "state": float(np.median([h - ts / 1000.0 for h, ts, _ in states])) if states else 0.0}
    return pairs, states, offsets


def read_labels(path: str):
    out = []
    with open(path, encoding="utf-8") as f:
        for r in csv.reader(l for l in f if not l.startswith("#")):
            if r and r[0] != "start_s":
                out.append((float(r[0]), float(r[1]), r[2]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rec", help="rec_raw.jsonl from record_board.py (/raw sensor objects + /api/state)")
    ap.add_argument("--labels", help="CSV start_s,end_s,label (seconds from --t0)")
    ap.add_argument("--t0", help="protocol_start_*.txt (first line = epoch of label time zero)")
    ap.add_argument("--margin", type=float, default=2.0, help="seconds cut at each step edge")
    ap.add_argument("--csv", help="write every evaluated frame here (golden file for the C++ port)")
    args = ap.parse_args()
    pairs, states, offs = read_raw(args.rec)
    if not pairs:
        raise SystemExit("no frame pairs")
    # host time = ESP ms / 1000 + off for frames, Pi ms / 1000 + off_state for board states; labels count from --t0
    off, off_state = offs["raw"], offs["state"]
    t0 = float(open(args.t0, encoding="utf-8").readline().split()[0]) if args.t0 else pairs[0][0] / 1000.0 + off
    rule = FaceDownRule()
    rows = []
    for ts, (da, sa), (db, sb) in pairs:
        r = rule.update(ts / 1000.0, da, sa, db, sb)
        rows.append(dict(t=ts / 1000.0 + off - t0, ts_ms=ts, **r))
    if args.csv:
        keys = ["ts_ms", "t", "up", "lo", "topA", "topB", "dlo", "dup", "flag", "share", "on", "seated"]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: (round(r[k], 4) if isinstance(r[k], float) else ("" if r[k] is None else r[k])) for k in keys})
    t = np.array([r["t"] for r in rows])
    on = np.array([r["on"] for r in rows])
    print(f"{len(rows)} frame pairs, face_down on {on.mean():.1%} of frames")
    if args.labels:
        bt = np.array([ts / 1000.0 + off_state - t0 for _, ts, _ in states])
        bp = np.array([p for _, _, p in states])
        for a, b, lab in read_labels(args.labels):
            m = (t >= a + args.margin) & (t < b - args.margin)
            if not m.any():
                continue
            bm = (bt >= a + args.margin) & (bt < b - args.margin)
            first = t[m][on[m]].min() - a if on[m].any() else None
            print(f"  {a:7.1f} {lab:13s} rule face_down {on[m].mean():5.0%}"
                  + (f" (first +{first:.1f} s)" if first is not None else "")
                  + (f" | board face_down {(bp[bm] == 'face_down').mean():4.0%}" if bm.any() else ""))


if __name__ == "__main__":
    main()
