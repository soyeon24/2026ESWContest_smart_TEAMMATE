#!/usr/bin/env bash
# Atlas SDK 컨테이너 없이 Pi 4(ATLAS, aarch64)용 정적 실행 파일을 만든다 (Zig 의 clang + musl).
#   python -m venv zigenv && zigenv/bin/pip install ziglang==0.13.0
#   ZIG="zigenv/bin/python -m ziglang" bash hub/atlas-tof/tools/build_static_aarch64.sh
# 결과: hub/atlas-tof/build/aarch64/ — 정적 링크라 보드 라이브러리와 무관.
#   deskmate_tofposture · tofposture_selftest   자세 서비스와 자가 시험
#   uart_relay_board · ch340cfg · usbpower      ESP32 프레임 중계기(USB·UART → :9100, :8772/raw), CH340 진단, USB 포트 전원 재시작
# 2026-10-15 UBAI 에서 이렇게 빌드해 qemu-aarch64 로 selftest PASS(골든 오차 4.1e-5) 확인.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$HERE"
ZIG="${ZIG:-zig}"; OUT=build/aarch64; mkdir -p "$OUT"
FLAGS="-target aarch64-linux-musl -O2 -std=c++17 -static -s"
$ZIG c++ $FLAGS -o $OUT/deskmate_tofposture src/main.cpp src/line_source.cpp src/http_server.cpp src/tof_line.cpp src/device_posture.cpp
$ZIG c++ $FLAGS -o $OUT/tofposture_selftest src/host_test.cpp src/tof_line.cpp src/device_posture.cpp
$ZIG c++ $FLAGS -o $OUT/uart_relay_board relay/uart_relay_board.cpp
$ZIG c++ $FLAGS -o $OUT/ch340cfg relay/ch340cfg.cpp
$ZIG c++ $FLAGS -o $OUT/usbpower relay/usbpower.cpp
ls -l $OUT
