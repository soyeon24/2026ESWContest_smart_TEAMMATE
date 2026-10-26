"""Expected board output of the 10-28 left demo combination, per labelled step: the Python side of the C++ replay diff.

Model input (deskmate_tofposture TOFPOSTURE_RADIAL=1 then TOFPOSTURE_FILL_NOTARGET_MM=3000): perpendicular -> radial
distance (x sqrt(1 + x^2 + y^2) per zone, x/y = zone centre on the tangent plane), then status 255 -> 3000 mm, status 5.
Per-sensor GRU stepped on 10 Hz ticks with the newest frame (5 Hz frames used twice), mean of log(p + 1e-6), softmax,
EMA alpha 0.1. Rule (d) (real_facedown_rule.py, original grid) turns the output to face_down; the seated substitution
turns model misplaced into upright on a seated geometry. drowsy is reported again at smoothed conf >= 0.80 (hub floor).
Frames are placed on their own ESP clock (record_board /raw ts_ms); the Pi /api/state clock was ~11 s off on 10-26.

    python real_demo_combo.py ckpt.pt rec_raw.jsonl --labels labels.csv --t0 protocol_start.txt [--no-radial] [--no-fill]
"""
from __future__ import annotations

import argparse
from collections import Counter

import numpy as np
import torch

import real_facedown_rule as RF
from tofsim.data import to_input
from tofsim.model import PostureNet

_TX = np.tan(np.radians(22.5))
_C = (np.arange(8) + 0.5) * 2 * _TX / 8 - _TX
_X, _Y = np.meshgrid(_C, _C)
RADIAL = np.sqrt(1 + _X ** 2 + _Y ** 2)      # symmetric, so row/column flips do not matter


def load_model(path):
    ck = torch.load(path, map_location="cpu", weights_only=False)
    sd = ck.get("model") or ck.get("state_dict")
    labels = [str(x) for x in ck["labels"]]
    net = PostureNet(8, 8, len(labels), hidden=int(sd["gru.weight_hh_l0"].shape[1]))
    net.load_state_dict(sd)
    net.eval()
    return net, labels


def model_input(pairs, which, ticks_idx, radial=True, fill_mm=3000):
    d = np.array([p[which][0] for p in pairs], np.float32).reshape(-1, 8, 8)[ticks_idx]
    s = np.array([p[which][1] for p in pairs], np.int32).reshape(-1, 8, 8)[ticks_idx]
    if radial:
        d = np.where(d >= 0, np.round(d * RADIAL), d)
    if fill_mm:
        m = s == 255
        d, s = np.where(m, fill_mm, d), np.where(m, 5, s)
    return torch.from_numpy(to_input(d, s))[None]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ckpt")
    ap.add_argument("rec", help="rec_raw.jsonl from record_board.py")
    ap.add_argument("--labels", required=True)
    ap.add_argument("--t0", required=True)
    ap.add_argument("--margin", type=float, default=2.0)
    ap.add_argument("--no-radial", action="store_true")
    ap.add_argument("--no-fill", action="store_true")
    ap.add_argument("--drowsy-floor", type=float, default=0.80)
    args = ap.parse_args()
    net, labels = load_model(args.ckpt)
    pairs, _states, offs = RF.read_raw(args.rec)
    t0 = float(open(args.t0, encoding="utf-8").readline().split()[0])
    ts = np.array([p[0] for p in pairs])
    rule = RF.FaceDownRule()
    ron, seat = [], []
    for t, (da, sa), (db, sb) in pairs:
        r = rule.update(t / 1000.0, da, sa, db, sb)
        ron.append(r["on"]); seat.append(r["seated"])
    ron, seat = np.array(ron), np.array(seat)
    ticks = np.arange(ts[0], ts[-1] + 1, 100)
    k = np.searchsorted(ts, ticks, side="right") - 1
    with torch.no_grad():
        lg = sum(torch.log(torch.softmax(net(model_input(pairs, i, k, not args.no_radial, 0 if args.no_fill else 3000))[0][0], -1)
                           + 1e-6).numpy() for i in (1, 2)) / 2
    p = np.exp(lg - lg.max(1, keepdims=True)); p /= p.sum(1, keepdims=True)
    sm = np.empty_like(p); sm[0] = p[0]
    for j in range(1, len(p)):
        sm[j] = sm[j - 1] + 0.1 * (p[j] - sm[j - 1])
    post = np.array(labels)[sm.argmax(1)]
    conf = sm.max(1)
    final = np.where(ron[k], "face_down", np.where((post == "misplaced") & seat[k], "upright", post))
    rel = ticks / 1000.0 + offs["raw"] - t0
    allp, allm, ally = [], [], []
    for a, b, lab in RF.read_labels(args.labels):
        m = (rel >= a + args.margin) & (rel < b - args.margin)
        if not m.any():
            continue
        n = int(m.sum())
        c = Counter(final[m])
        top = ", ".join(f"{kk} {v / n:.0%}" for kk, v in c.most_common(3))
        dz = float(((final[m] == "drowsy") & (conf[m] >= args.drowsy_floor)).mean())
        print(f"  {a:7.1f} {lab:13s} hit {c.get(lab, 0) / n:4.0%} | {top} | model only: {(post[m] == lab).mean():4.0%} "
              f"| drowsy>={args.drowsy_floor:.2f} {dz:4.0%}")
        allp.append(final[m]); allm.append(post[m]); ally.append(np.full(n, lab))
    Y = np.concatenate(ally)
    for name, P in (("combo", np.concatenate(allp)), ("model only", np.concatenate(allm))):
        f1 = [2 * np.sum((P == c) & (Y == c)) / max(1, np.sum(P == c) + np.sum(Y == c)) for c in np.unique(Y)]
        print(f"  {name}: acc {np.mean(P == Y):.3f} macroF1 {np.mean(f1):.3f}")


if __name__ == "__main__":
    main()
