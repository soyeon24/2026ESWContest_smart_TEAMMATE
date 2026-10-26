"""PC 에서 실제 센서로 모델을 바로 돌려 본다 (보드 없이). Pi 4 서비스(hub/atlas-tof)와 같은 처리 경로.

    ESP32 USB → 이 스크립트 → 터미널에 자세 (센서마다 모델 하나, 10 Hz, log-softmax 합)

    .venv\\Scripts\\python tof_live.py --ports COM5 --echo                           # 처음: 줄 형식·보드율 확인
    .venv\\Scripts\\python tof_live.py --ports COM5,COM6 --model ..\\tof-sim_ubai_random\\export_20261014_1957_best\\posture_net.onnx
    .venv\\Scripts\\python tof_live.py --ports a.jsonl,b.jsonl --model ...onnx         # 파일 리플레이 (sim_to_toflines.py 출력)
    .venv\\Scripts\\python tof_live.py --ports COM5 --record live_%Y%m%d_%H%M.jsonl    # 원본 줄 저장 (나중에 리플레이·채점)

녹화 줄은 {"host_t": PC 시각(epoch s), "port": 포트, "raw": 원본 줄} 로 감싸 저장한다(포트 여러 개도 한 파일에서 구분).
리플레이는 --ports live.jsonl (전부) 또는 --ports live.jsonl@COM5 (그 포트 줄만). 감싸지 않은 옛 녹화도 그대로 읽는다.

필요: pip install pyserial onnxruntime. 세 펌웨어 형식을 다 읽는다:
  - tof_logger(env:tof_logger) JSON 줄 ({"t":"tof",...}, 921600) — firmware/esp32_sensor_node/src/tof_logger/TofLine.cpp
  - VL53L8CX I2C bring-up(김태환, tof-bringup-full-4MB.bin) CSV 줄 — F,ms,64거리[,64상태] / P,ms,present,posture,…
    (펌웨어 문자열에서 복원한 형식이라 --echo 로 첫 줄을 꼭 확인한다. 상태값이 없으면 거리>0 을 유효로 본다)
  - 운영 펌웨어 main 의 USB 'z' 줄 {"t":"tof_grid","ms","frame","sensors_ok","w","h","flags","s":[{"d","st"}|null,…]}
    (firmware/esp32_sensor_node/src/transport/usb_json.cpp, 2026-10-21 추가). **포트 하나에 센서 둘**이 한 줄로 오고, 센서마다
    모델을 하나씩 둔다(COM5#s0, COM5#s1). 센서당 5 Hz 라 10 Hz 스텝에서 한 프레임이 두 번 쓰인다(보드 서비스와 같음).
    flags 는 펌웨어가 **이미 적용한** 방향(b0 rows · b1 cols)이라 여기서는 기본으로 안 뒤집는다(--flip-* 는 그 위에 더 뒤집기).
    frame(u8) 로 순서를 본다: 차이 0..10 은 이어짐, 그 밖은 그 센서 모델 리셋. 거리 0 이하는 "없음"(-1).
    Source._parse 는 이 줄도 예전처럼 {"t":"tof","ms","d","st","has_status"} 로 돌려준다(첫 센서). 센서 전부는 obj["frames"].
    'z' 는 펌웨어 시리얼 콘솔에서 토글한다(PC 진단용 출력, tools/sensor_monitor.py 와 같음).
보드율은 기본 자동(921600→115200→460800→230400). 펌웨어가 15 Hz 로 보내도 모델은 10 Hz 로만 돌린다
(매 100 ms 마다 센서별 최신 프레임). 센서가 1 s 넘게 조용하면 그 센서는 빼고, 돌아오면 GRU 상태를 0 으로
다시 시작한다 — 서비스와 같은 규칙.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from collections import deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# tofsim 을 import 하지 않는다(그쪽은 mujoco·torch 를 끌어온다). 아래 둘은 tofsim/data.py·session.py 와 같아야 한다.
LABELS = ["upright", "lean_forward", "recline", "face_down", "chin_rest", "drowsy", "away", "misplaced", "forward_head"]
VALID_STATUS = np.array([5, 6, 9, 10])
MAX_MM = 4000.0


def to_input(dist, status):
    valid = np.isin(status, VALID_STATUS) & (dist >= 0)
    x = np.where(valid, dist.astype(np.float32) / MAX_MM, 0.0).astype(np.float32)
    return np.stack([x, valid.astype(np.float32)], axis=-3)


KO = {"upright": "바른자세", "lean_forward": "상체 앞으로", "recline": "뒤로 젖힘", "face_down": "엎드림",
      "chin_rest": "턱괴기", "drowsy": "꾸벅 졸음", "away": "자리비움", "misplaced": "위치 재조정", "forward_head": "거북목"}


def orient(a, flip_rows, flip_cols):
    """보드 서비스의 TOFPOSTURE_FLIP_ROWS/COLS 와 같은 뒤집기."""
    if flip_rows:
        a = a[::-1]
    if flip_cols:
        a = a[:, ::-1]
    return np.ascontiguousarray(a)


def show_grid(path, frame, flip_rows, flip_cols):
    """8x8 거리를 cm 로 찍는다. 무효 zone 은 ' .'. row 0 = 위, col 0 = 센서에서 볼 때 왼쪽이 맞는지 손으로 확인."""
    d = orient(np.asarray(frame["d"], np.int16).reshape(8, 8), flip_rows, flip_cols)
    st = orient(np.asarray(frame["st"], np.uint8).reshape(8, 8), flip_rows, flip_cols)
    ok = np.isin(st, VALID_STATUS) & (d >= 0)
    fw = frame.get("fw_flags")
    fw_s = "" if fw is None else f"  펌웨어가 이미 적용: rows={bool(fw & 1)} cols={bool(fw & 2)}"
    print(f"--- {path}  (cm, '.' = 무효)  위쪽 줄이 천장 쪽, 왼쪽 열이 센서에서 볼 때 왼쪽이어야 한다{fw_s}")
    for r in range(8):
        print("   " + " ".join(f"{d[r, c] // 10:4d}" if ok[r, c] else "   ." for c in range(8)))


class OnnxStep:
    """posture_net.onnx: (x (1,2,H,W), h (1,1,hidden)) -> (logits (1,C), h)."""

    def __init__(self, path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        self.s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.hidden = self.s.get_inputs()[1].shape[2]
        self.classes = self.s.get_outputs()[0].shape[1]
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, self.hidden), np.float32)

    flip_rows = False
    flip_cols = False

    def step(self, dist, status):
        d, st = np.asarray(dist, np.int16).reshape(8, 8), np.asarray(status, np.uint8).reshape(8, 8)
        d, st = orient(d, self.flip_rows, self.flip_cols), orient(st, self.flip_rows, self.flip_cols)
        x = to_input(d, st)[None]
        logits, self.h = self.s.run(None, {"x": x.astype(np.float32), "h": self.h})
        return logits[0]


RECORD_LOCK = threading.Lock()     # Source 스레드들이 같은 녹화 파일에 줄 단위로 번갈아 쓴다


class Source(threading.Thread):
    """시리얼 포트 또는 파일에서 줄을 읽어 최신 프레임만 들고 있는다."""

    AUTO_BAUDS = (921600, 115200, 460800, 230400)

    def __init__(self, path, baud, record, fast=False, echo=False, forward=None):
        super().__init__(daemon=True)
        self.path, self.baud, self.record, self.fast = path, baud, record, fast
        self.forward, self.fwd_sock, self.fwd_next, self.fwd_sent = forward, None, 0.0, 0   # (host, port) 또는 None
        self.echo, self.echo_left = echo, 3          # --echo: 안내·규칙 줄 전부 + 프레임 줄 처음 3개
        self.rule, self.info = "", ""
        self.lock = threading.Lock()
        self.latest = None          # (frame dict, rx_time) — 첫 센서(예전 한 포트 = 한 센서 코드용)
        self.latest_by = {}         # 센서 키(None = 포트가 곧 센서, 0/1 = tof_grid 의 물리 센서) -> (frame dict, rx_time)
        self.frames = 0
        self.hello = ""
        self.err = ""
        self.times = deque(maxlen=30)
        self.times_by = {}          # 센서 키 -> deque(rx_time)
        # "녹화파일@COM5" 는 녹화 파일에서 그 포트 줄만 리플레이
        self.file, self.port_filter = path, None
        if not os.path.isfile(path) and "@" in path and os.path.isfile(path.rsplit("@", 1)[0]):
            self.file, self.port_filter = path.rsplit("@", 1)
        self.is_file = os.path.isfile(self.file)
        self.done = False

    def run(self):
        if self.is_file:
            t0, ms0 = time.monotonic(), None
            with open(self.file, encoding="utf-8", errors="replace") as fp:
                for line in fp:
                    if line.startswith('{"host_t"'):          # 감싼 녹화 줄
                        try:
                            w = json.loads(line)
                        except ValueError:
                            continue
                        if self.port_filter is not None and w.get("port") != self.port_filter:
                            continue
                        line = w.get("raw", "")
                    obj = self._parse(line)
                    if obj is None:
                        continue
                    ms = int(obj.get("ms", 0))
                    if ms0 is None:
                        ms0 = ms
                    due = t0 + (ms - ms0) / (1000.0 if not self.fast else 20000.0)
                    while time.monotonic() < due:
                        time.sleep(0.002)
                    self._take(obj, line)
            self.done = True
            return
        import serial
        bauds = list(self.AUTO_BAUDS) if self.baud in (0, None) else [self.baud]
        bi = 0
        while True:
            baud = bauds[bi % len(bauds)]
            try:
                with serial.Serial(self.path, baud, timeout=0.2) as ser:
                    self.err = ""
                    self.baud_now = baud
                    t_open, got_bytes, got_valid = time.monotonic(), False, False
                    while True:
                        line = ser.readline()
                        if not line:
                            # 보드율 자동: 바이트는 오는데 3초 동안 센서 줄이 없으면 다음 후보
                            if len(bauds) > 1 and got_bytes and not got_valid and time.monotonic() - t_open > 3:
                                self.err = f"no sensor lines at {baud}, trying next baud"
                                bi += 1
                                break
                            continue
                        got_bytes = True
                        text = line.decode("utf-8", errors="replace")
                        obj = self._parse(text)
                        if obj is not None:
                            got_valid = True
                            self._take(obj, text)
                        elif len(bauds) > 1 and not got_valid and time.monotonic() - t_open > 3:
                            self.err = f"no sensor lines at {baud}, trying next baud"
                            bi += 1
                            break
            except Exception as e:  # 포트 없음·뽑힘: 3초 뒤 다시
                self.err = str(e)
                time.sleep(3)

    @staticmethod
    def _grid_frames(obj):
        """{"t":"tof_grid",...} -> 센서마다 {"t":"tof",...} (sensor = s 의 자리). 모양이 틀린 센서는 건너뛴다."""
        try:
            w, h, ms, fid = int(obj["w"]), int(obj["h"]), int(obj["ms"]), int(obj["frame"]) & 0xFF
        except (KeyError, TypeError, ValueError):
            return []
        flags = int(obj.get("flags") or 0)
        out = []
        for i, s in enumerate(obj.get("s") or []):
            if not isinstance(s, dict):
                continue                                         # null = 그 센서 꺼짐
            d, st = s.get("d") or [], s.get("st") or []
            if w * h != 64 or len(d) != 64 or len(st) != 64:
                continue
            out.append({"t": "tof", "ms": ms, "seq": fid, "seq_bits": 8, "w": w, "h": h,
                        "d": [int(v) if int(v) > 0 else -1 for v in d], "st": [int(v) for v in st],
                        "has_status": True, "sensor": i, "fw_flags": flags})
        return out

    @staticmethod
    def _parse(text):
        """세 펌웨어 형식. tof_logger JSON({"t":...}), bring-up CSV(F,ms,64값[,64상태] / P,ms,present,posture,...),
        main USB {"t":"tof_grid"}(센서 여럿 → 첫 센서를 예전 모양으로, 전부는 "frames")."""
        text = text.strip()
        if text.startswith('{"t":'):
            try:
                obj = json.loads(text)
            except ValueError:
                return None
            if not isinstance(obj, dict):
                return None
            if obj.get("t") == "tof_grid":
                frames = Source._grid_frames(obj)
                if not frames:
                    return {"t": "tof_grid", "ms": obj.get("ms", 0), "frames": []}
                return dict(frames[0], frames=frames)
            return obj
        if len(text) > 2 and text[1] == "," and text[0] in "FP":
            parts = text.split(",")
            try:
                ms = int(parts[1])
            except ValueError:
                return None
            if text[0] == "P":
                return {"t": "rule", "ms": ms, "posture": parts[3] if len(parts) > 3 else ""}
            try:
                vals = [int(v) for v in parts[2:]]
            except ValueError:
                return None
            if len(vals) == 64:
                return {"t": "tof", "ms": ms, "seq": ms, "w": 8, "h": 8, "d": vals,
                        "st": [5 if v > 0 else 255 for v in vals], "has_status": False}
            if len(vals) == 128:
                return {"t": "tof", "ms": ms, "seq": ms, "w": 8, "h": 8, "d": vals[:64], "st": vals[64:]}
            return None
        if text.startswith("Ranging started"):
            return {"t": "tof_hello", "ms": 0, "sensor": "VL53L8CX-bringup", "w": 8, "h": 8, "hz": 15}
        if text.startswith("[ERR]"):
            return {"t": "tof_err", "ms": 0, "where": text[6:], "code": 0}
        if text.startswith("#") or "bring-up" in text:
            return {"t": "info", "text": text}
        return None

    def _send(self, raw):
        """--forward: 받은 줄을 Pi 4 서비스의 tcp:<port> 로 그대로 넘긴다. 끊기면 3초 뒤 다시 붙는다."""
        if self.fwd_sock is None:
            if time.monotonic() < self.fwd_next:
                return
            try:
                self.fwd_sock = socket.create_connection(self.forward, timeout=2)
                self.fwd_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError as e:
                self.fwd_sock, self.fwd_next = None, time.monotonic() + 3
                self.err = f"forward {self.forward[0]}:{self.forward[1]}: {e}"
                return
        try:
            self.fwd_sock.sendall((raw.rstrip("\r\n") + "\n").encode("ascii", "replace"))
            self.fwd_sent += 1
        except OSError as e:
            self.err = f"forward lost: {e}"
            try:
                self.fwd_sock.close()
            except OSError:
                pass
            self.fwd_sock, self.fwd_next = None, time.monotonic() + 3

    def _take(self, obj, raw):
        if self.record is not None:
            # 포트 여러 개가 한 파일에 쓰므로 어느 포트·언제 받았는지 같이 남긴다 (real_from_record.py 가 읽는 형식)
            rec = json.dumps({"host_t": round(time.time(), 4), "port": self.path, "raw": raw.rstrip("\r\n")}, ensure_ascii=True)
            with RECORD_LOCK:
                self.record.write(rec + "\n")
        if self.forward is not None:
            self._send(raw)
        if self.echo and (self.echo_left > 0 or obj.get("t") in ("tof_hello", "tof_err", "info", "rule")):
            print(f"[{self.path}] {raw.rstrip()[:300]}", flush=True)
            if obj.get("t") == "tof":
                self.echo_left -= 1
        kind = obj.get("t")
        if kind == "rule":
            self.rule = obj.get("posture", "")
        elif kind == "info":
            self.info = obj.get("text", "")
        elif kind == "tof_hello":
            self.hello = f"{obj.get('sensor')} {obj.get('w')}x{obj.get('h')} {obj.get('hz')}Hz flip_rows={obj.get('flip_rows')} flip_cols={obj.get('flip_cols')}"
            with self.lock:
                self.latest = None          # 센서 재시작 → 모델 상태도 새로
        elif kind == "tof_err":
            self.err = f"{obj.get('where')} code {obj.get('code')}"
        elif kind == "tof" and len(obj.get("d", [])) == 64 and len(obj.get("st", [])) == 64:
            now = time.monotonic()
            frames = obj.get("frames") or [obj]
            with self.lock:
                self.latest = (frames[0], now)
                for f in frames:
                    self.latest_by[f.get("sensor")] = (f, now)
            for f in frames:
                self.times_by.setdefault(f.get("sensor"), deque(maxlen=30)).append(now)
            self.frames += 1
            self.times.append(now)

    def hz(self, key="__all__"):
        t = self.times if key == "__all__" else self.times_by.get(key, ())
        if len(t) < 2:
            return 0.0
        return (len(t) - 1) / max(1e-6, t[-1] - t[0])

    def name(self, key):
        return self.path if key is None else f"{self.path}#s{key}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ports", required=True, help="콤마로 나눈 시리얼 포트(COM5, /dev/ttyUSB0) 또는 리플레이 파일")
    ap.add_argument("--model", default=None, help="posture_net.onnx (기본: ../tof-sim_ubai_random 의 최신 export)")
    ap.add_argument("--baud", type=int, default=0, help="0 = 자동(921600/115200/460800/230400 중 줄이 읽히는 값)")
    ap.add_argument("--echo", action="store_true", help="받은 줄을 그대로 찍는다(안내·규칙 줄 전부, 프레임 줄은 처음 3개) — 형식 확인용")
    ap.add_argument("--rate", type=float, default=10.0, help="모델 스텝 Hz (학습 프레임률, 바꾸지 말 것)")
    ap.add_argument("--stale", type=float, default=1.0, help="이 초 동안 프레임이 없으면 센서 제외")
    ap.add_argument("--fusion", choices=["logprob", "mean"], default="logprob")
    ap.add_argument("--record", default=None, help="받은 줄을 이 파일에 그대로 저장 (strftime 서식 가능)")
    ap.add_argument("--quiet", action="store_true", help="자세가 바뀔 때만 출력")
    ap.add_argument("--fast", action="store_true", help="파일 리플레이를 20배속으로 (모델 스텝도 같이 빨라짐)")
    ap.add_argument("--flip-rows", action="store_true", help="격자를 위아래로 뒤집어 넣는다 (보드 TOFPOSTURE_FLIP_ROWS=1 과 같음)")
    ap.add_argument("--flip-cols", action="store_true", help="격자를 좌우로 뒤집어 넣는다 (보드 TOFPOSTURE_FLIP_COLS=1 과 같음)")
    ap.add_argument("--show", action="store_true", help="1초마다 센서별 8x8 거리(cm)를 찍는다 — 방향 확인용")
    ap.add_argument("--forward", default=None,
                    help="받은 줄을 Pi 4 서비스로 넘긴다. 포트 순서대로 HOST:PORT 를 콤마로 (예: 172.16.34.146:9001,172.16.34.146:9002)")
    args = ap.parse_args()
    if args.fast:
        args.rate *= 20.0

    model = args.model
    if model is None:
        import glob
        cands = [os.path.join(HERE, "posture_net.onnx")] if os.path.isfile(os.path.join(HERE, "posture_net.onnx")) else []
        cands = cands or sorted(glob.glob(os.path.join(HERE, "..", "rpi4_tof_deploy", "pc", "posture_net.onnx")))
        cands = cands or sorted(glob.glob(os.path.join(HERE, "..", "tof-sim_ubai_random", "export_*", "posture_net.onnx")))
        if not cands:
            sys.exit("--model 을 지정하세요 (posture_net.onnx)")
        model = cands[-1]
    print(f"model {model}")
    record = open(time.strftime(args.record), "w", encoding="ascii") if args.record else None
    ports = [p.strip() for p in args.ports.split(",") if p.strip()]
    fwd = [None] * len(ports)
    if args.forward:
        hp = [x.strip() for x in args.forward.split(",") if x.strip()]
        if len(hp) != len(ports):
            sys.exit("--forward 는 --ports 와 같은 개수여야 합니다")
        fwd = [(h.rsplit(":", 1)[0], int(h.rsplit(":", 1)[1])) for h in hp]
    sources = [Source(p, args.baud, record, args.fast, args.echo, f) for p, f in zip(ports, fwd)]
    # 센서 채널 = (포트 번호, 센서 키). 포트 하나에 센서 하나(키 None)가 보통이고, main 의 tof_grid 는 포트 하나에 0·1 둘.
    # 채널은 첫 프레임이 올 때 생긴다. 채널마다 모델(GRU 상태) 하나.
    nets, online_prev, last_seq = {}, {}, {}
    probe = OnnxStep(model)
    last_show = 0.0
    C = probe.classes
    labels = LABELS[:C]

    def net_for(ch):
        if ch not in nets:
            nets[ch] = probe if not nets else OnnxStep(model)
            nets[ch].flip_rows, nets[ch].flip_cols = args.flip_rows, args.flip_cols
            nets[ch].reset()
        return nets[ch]

    def rewound(frame, prev):
        """ESP32 재부팅·큰 유실이면 True. frame_id(u8) 는 순환하므로 차이로 본다(서비스와 같은 규칙)."""
        if prev is None:
            return False
        if frame.get("seq_bits") == 8:
            return ((int(frame["seq"]) - prev) & 0xFF) > 10
        return int(frame["seq"]) < prev

    for s in sources:
        s.start()
    print(f"sensors {ports}  rate {args.rate} Hz  fusion {args.fusion}  (Ctrl+C 로 종료)")

    period = 1.0 / args.rate
    stale = args.stale / (20.0 if args.fast else 1.0)
    next_t = time.monotonic()
    last_label = None
    smooth = None
    alpha = 1.0 / (10.0 if args.fast else args.rate)   # 1초 EMA (모델 스텝 기준 10개)
    try:
        while True:
            now = time.monotonic()
            if now < next_t:
                time.sleep(min(0.005, next_t - now))
                continue
            next_t = now + period if now - next_t > 2 * period else next_t + period
            channels = []
            for si, s in enumerate(sources):
                with s.lock:
                    snap = dict(s.latest_by)
                for key in sorted(snap, key=lambda k: -1 if k is None else k):
                    channels.append(((si, key), s, key, snap[key]))
            if args.show and now - last_show >= 1.0:
                last_show = now
                for _, s, key, lt in channels:
                    show_grid(s.name(key), lt[0], args.flip_rows, args.flip_cols)
            acc, online, per = np.zeros(C), 0, []
            for ch, s, key, latest in channels:
                net = net_for(ch)
                on = (now - latest[1]) <= stale
                if not on:
                    if online_prev.get(ch):
                        net.reset()
                    online_prev[ch] = False
                    per.append("  --  ")
                    continue
                if not online_prev.get(ch) or rewound(latest[0], last_seq.get(ch)):
                    net.reset()        # 새로 붙었거나 ESP32 재부팅
                online_prev[ch] = True
                last_seq[ch] = int(latest[0]["seq"])
                logits = net.step(latest[0]["d"], latest[0]["st"])
                p = np.exp(logits - logits.max()); p /= p.sum()
                acc += np.log(p + 1e-6) if args.fusion == "logprob" else p
                online += 1
                per.append(f"{labels[int(p.argmax())][:6]:6s}{p.max():.2f}")
            if online == 0:
                fused = None
                line = "no sensor online  " + "  ".join(f"{s.path}: {s.err or ('frames ' + str(s.frames))}" for s in sources)
            else:
                acc /= online
                fused = np.exp(acc - acc.max()); fused /= fused.sum()
                if args.fusion == "mean":
                    fused = acc
                smooth = fused if smooth is None else smooth + alpha * (fused - smooth)
                k = int(smooth.argmax())
                line = (f"{labels[k]:13s} {KO[labels[k]]:7s} {smooth[k]:.2f} | " + " | ".join(per) +
                        " | " + " ".join(f"{s.name(key)} {s.hz(key):4.1f}Hz" for _, s, key, _ in channels) +
                        "".join(f" rule:{s.rule}" for s in sources if s.rule) +
                        "".join(f" fwd:{s.fwd_sent}" for s in sources if s.forward is not None))
                label_now = labels[k]
                if args.quiet and label_now == last_label:
                    if all(s.done for s in sources if s.is_file) and sources and all(s.is_file for s in sources):
                        break
                    continue
                last_label = label_now
            print(time.strftime("%H:%M:%S"), line, flush=True)
            if sources and all(s.is_file for s in sources) and all(s.done for s in sources):
                break
    except KeyboardInterrupt:
        pass
    finally:
        if record is not None:
            record.close()


if __name__ == "__main__":
    main()
