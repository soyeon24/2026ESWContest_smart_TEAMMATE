# 휴대폰 핫스팟에서 처음부터 띄우기 (누구 PC 로든)

ESP32 센서 노드 → Pi 4(자세 서비스·중계기) → PC 뷰어까지, GitHub 에 있는 것만으로 띄우는 순서다. 특정 노트북의 파일·ssh 설정은 필요 없다.
2026-10-23 기준. 실행 파일·모델은 레포에 커밋하지 않고(팀 규칙) **GitHub Release** 로 받는다.

```
ESP32(esp32dev_usb) ─USB─► Pi 4 ─ uart_relay_board ─tcp:9100─► deskmate_tofposture :8771 (자세)
   L8 ×2 · C1001 · 환경                └─ :8772/raw (ToF 8×8 + mmWave·환경·하트비트)
Pi 4 eth0 172.16.34.199 ═ 랜선 ═ Pi 5 eth0 172.16.34.198 ··· Pi 5 wlan0 ─ 휴대폰 핫스팟 ─ PC
```

Pi 4 는 Wi-Fi 에 안 붙고 Pi 5 뒤 랜선에만 있다. PC 는 **Pi 5 를 거쳐(ssh -J)** Pi 4 에 간다.

## 받을 것

| 무엇 | 어디 |
|---|---|
| 소스·스크립트·이 문서 | 팀 저장소. PR #61 머지 전에는 `git fetch https://github.com/soyeon24/2026ESWContest_smart_TEAMMATE.git feat/esp32-usb-direct` |
| Pi 4 묶음(실행 파일 5개·모델·자가 시험) | 팀 저장소 Releases → `pi4-tof-bundle-20261023` → `deskmate_pi4_tof_20261023.zip` |
| Pi 4 hub IPK(FSM, 자세 서비스 판정 폴링) | 같은 Release → `com.deskmate.hub1_22218f1.ipk` (소스 `feat/pi4-hub-1023` 22218f1) |

zip 을 `hub/atlas-tof/dist/` 에 푼다(`dist/pi4/`, `dist/pc/` 가 생긴다, gitignore 됨). 배포 스크립트·`tof_live.py` 가 여기서 찾는다.
실행 파일은 소스로 다시 만들 수도 있다: `ZIG="zigenv/bin/python -m ziglang" bash hub/atlas-tof/tools/build_static_aarch64.sh`(README 「올리는 길」).

PC 에 필요한 것: Windows 10/11 기본 `ssh`·`tar`·PowerShell, Python 3(뷰어용 `http.server`), ESP32 를 구울 때만 PlatformIO.

## 1. ESP32 굽기 (펌웨어가 바뀌었을 때만)

```powershell
cd firmware\esp32_sensor_node
pio run -e esp32dev_usb -t upload --upload-port COM5     # 포트는 장치 관리자에서
```

- `esp32dev_usb` = UART2 와 같은 COBS+CRC 프레임을 USB 로도 낸다(fw 0x0125, ToF 방향 `FLIP_ROWS=1`·`FLIP_COLS=0` — 10-22 재장착 실기).
- USB 로는 JSON 진단이 안 나온다. `tools/sensor_monitor.py` 로 보려면 `esp32dev` 로 굽는다.
- 굽고 나면 ESP32 USB-C 를 **Pi 4 USB-A** 에 꽂는다(전원도 여기서). 부팅 뒤 첫 프레임까지 30 s 남짓.

## 2. 배선·전원

Pi 4 ↔ Pi 5 랜선, 두 보드 전원. 랜선 링크는 Pi 5 에서 `cat /sys/class/net/eth0/carrier` 가 1 이어야 한다(0 이면 케이블 다시 꽂기).

## 3. Pi 5 를 핫스팟에 붙이고 찾기

1. 휴대폰 핫스팟을 켜고(2.4 GHz 권장) PC 도 거기에 붙인다. **Cloudflare WARP 같은 VPN 은 끈다.**
2. Pi 5 찾기: `powershell -ExecutionPolicy Bypass -File tools\find-boards.ps1` — Pi 5 wlan0 MAC `88-a2-9e-3c-cc-b4` 로 찾아 주소를 알려 준다.
   - 보드는 **ping 에 답하지 않는다.** 살아 있는지는 22 번 포트로 본다(`Test-NetConnection <ip> -Port 22`). 배너가 `SSH-2.0-dropbear` 면 ATLAS 보드.
3. **그 핫스팟에 처음 붙이는 경우**(ATLAS 는 재부팅 뒤 핫스팟을 다시 안 붙을 수 있다): PC 를 랜선으로 Pi 5 eth0 에 직접 꽂고
   (Pi 4 랜선은 잠깐 뺀다) PC 유선 주소를 `172.16.34.50/24` 고정으로 준 뒤
   ```bash
   scp tools/atlas-hotspot-broker/board_wifi_connect.sh root@172.16.34.198:/tmp/
   ssh root@172.16.34.198 "sh /tmp/board_wifi_connect.sh '<SSID>' '<비밀번호>'"     # → connected: <주소>
   ```
   SSID·비밀번호는 어디에도 적지 않는다. 끝나면 Pi 4 랜선을 다시 꽂는다.
4. 보드 root 는 **빈 비밀번호**다. ssh 가 물으면 Enter(점프까지 두 번 물을 수 있다).

아래에서 `<PI5>` = Pi 5 의 핫스팟 주소(예: 172.20.10.10), Pi 4 = `172.16.34.199`.
Pi 4 주소가 다르면 `ssh root@<PI5> "ip neigh show dev eth0"` 로 본다.

## 4. Pi 4 에 올리고 띄우기

```powershell
cd hub\atlas-tof\tools
powershell -ExecutionPolicy Bypass -File .\deploy-pi4.ps1 -Ip 172.16.34.199 -Jump <PI5>
```

복사 → 자가 시험(`selftest.sh`: 골든 logits·리플레이) → 자세 서비스(`start.sh`) → 중계기(`relay.sh`) 순서로 한다.
Git Bash 면 `JUMP=<PI5> bash deploy-pi4.sh 172.16.34.199`.

- 설정은 보드의 `/mnt/rawdata/deskmate_tof/tofposture.env`(처음엔 `tofposture.env.example` 복사). 입력은 **`TOFPOSTURE_PORTS=tcp:9100`**(중계기) 그대로 둔다 —
  비우면 서비스가 ttyUSB 를 직접 열어 중계기와 같은 장치를 둘이 읽게 되고 프레임이 깨진다.
- 모델 바꾸기: `TOFPOSTURE_MODEL=models/a9_demo/posture_net.bin` 한 줄 → `sh start.sh`. 묶음의 기본 모델은 `models/` 바로 아래(model_card.json 참고).
- **재부팅하면 프로세스는 사라진다**(파일은 남는다). `ssh -J root@<PI5> root@172.16.34.199 "sh /mnt/rawdata/deskmate_tof/start.sh && sh /mnt/rawdata/deskmate_tof/relay.sh"`.
- 상태: `... sh /mnt/rawdata/deskmate_tof/status.sh`, 중계기 `... sh /mnt/rawdata/deskmate_tof/relay.sh status`(relay.log 에 `ch340 version=…`, `type5=` 가 늘면 정상).
- ESP32 를 통째로 다시 켜기: 보드에서 `./usbpower`(Pi 4 의 USB 포트 전원이 전부 같이 꺼졌다 켜진다).

## 5. PC 에서 보기

```powershell
powershell -ExecutionPolicy Bypass -File hub\atlas-tof\pc\view.ps1 -Pi5 <PI5>
```

ssh 터널(:8771 자세, :8772 원본)을 열고 `posture_view.html` 을 브라우저로 연다. 터널 창이 비밀번호를 물으면 Enter, 창은 열어 둔다.
화면 아래 "원본 격자"(ToF A/B 8×8)와 "나머지 센서 raw"(mmWave 0x20·환경 0x10·ToF 특징 0x03·ToF 자세 0x04·하트비트 0xF0).
보드 안에서 바로: `wget -qO- http://127.0.0.1:8772/raw`, `wget -qO- http://127.0.0.1:8771/api/state`.

## 6. hub(FSM) 까지 (선택)

Release 의 `com.deskmate.hub1_22218f1.ipk` 를 Atlas SDK 의 `arc install` 로 올린 뒤 `hub/atlas/tools/pi4-hub-activate.sh` 로 띄운다
(`feat/pi4-hub-1023` 의 `hub/atlas/README.md` 「설치 및 실행 확인」·「재부팅·재설치 후 기동」). 이 판은 자세 서비스 `/api/state` 를 1 s 마다 읽어
FSM 자세 신호로 쓴다(`tof.posture_source: service`). **아직 보드 설치·실기 확인 전이다.**
주의: hub 는 `/dev/serial0` 만 읽으므로 ESP32 를 USB 로 꽂은 지금 구성에서는 mmWave·환경 값이 hub 로 안 간다(중계기가 hub 로 복사하는 건 미구현).

## 7. 안 될 때

| 증상 | 볼 것 |
|---|---|
| Pi 5 가 안 보임 | VPN 끄기, 같은 핫스팟인지, 3-3 으로 다시 붙이기 |
| `ssh -J` 가 Pi 4 에서 막힘 | Pi 5 `eth0/carrier`, Pi 4 주소(`ip neigh`) |
| `/raw` 에 격자 없음, relay.log `bytes=0` | ESP32 USB 케이블·부팅 30 s 대기, `./ch340cfg auto 115200`, `./usbpower` |
| 한 센서만 online | 센서 A 배선(10-22 실기에서도 A 미기동, mask=2) |
| 자세가 거울상 | 펌웨어 방향은 이미 적용돼 온다 — 받는 쪽 `TOFPOSTURE_FLIP_*` 는 비워 둔다 |
| 뷰어가 `file://` 로 열려 빈 화면 | `view.ps1` 로 열기(로컬 http.server 필요) |
