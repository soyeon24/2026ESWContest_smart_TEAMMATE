#!/usr/bin/env bash
# PC(Linux/macOS/Git Bash)에서 Pi 4(ATLAS)로 ToF 자세 서비스 묶음을 올리고 자가 시험 뒤 서비스·중계기를 띄운다.
#   bash deploy-pi4.sh 172.16.34.199 [묶음 폴더=../dist/pi4]                 # Pi 4 에 직접 닿을 때
#   JUMP=172.20.10.10 bash deploy-pi4.sh 172.16.34.199                       # 핫스팟: Pi 5 를 거쳐 간다
# 묶음: GitHub Release 의 zip 을 hub/atlas-tof/dist/ 에 푼다(docs/run-on-hotspot.md).
set -euo pipefail
IP="${1:?보드 IP}"; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="${2:-}"; [ -n "$BUNDLE" ] || { [ -d "$HERE/pi4" ] && BUNDLE="$HERE/pi4" || BUNDLE="$HERE/../dist/pi4"; }; DEST=/mnt/rawdata/deskmate_tof; T="root@$IP"
SSH="ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new${JUMP:+ -J root@$JUMP}"
[ -f "$BUNDLE/deskmate_tofposture" ] || { echo "묶음이 아니다: $BUNDLE — GitHub Release 의 zip 을 hub/atlas-tof/dist/ 에 풀 것" >&2; exit 1; }
$SSH "$T" "tr -d '\0' < /proc/device-tree/model; echo; for p in \$(pidof deskmate_tofposture) \$(pidof uart_relay_board); do kill \$p; done; mkdir -p $DEST"
tar -cf - -C "$BUNDLE" . | $SSH "$T" "tar -xf - -C $DEST"
$SSH "$T" "chmod +x $DEST/deskmate_tofposture $DEST/tofposture_selftest $DEST/uart_relay_board $DEST/ch340cfg $DEST/usbpower $DEST/*.sh 2>/dev/null; sh $DEST/selftest.sh && sh $DEST/start.sh && sh $DEST/relay.sh"
echo "보드 상태: $SSH $T sh $DEST/status.sh"
