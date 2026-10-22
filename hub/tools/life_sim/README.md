# life_sim — 생활 각본 폐루프 시뮬 (2026-10-22)

사람의 하루를 각본으로 재생해 **가상 ToF 8×8 두 센서 → 자세·졸음 판정 → hub FSM(18상태) → 개인화 개입 선택(personalize) →
주변기기(mock) → 사람 반응 → 다시 ToF** 의 닫힌 고리를 돌린다. 결과는 전부 **시뮬레이션**이다. 실측 증거가 아니다
(10-19 실측 녹화에서는 모든 자세 모델이 drowsy 재현율 0 이었다).

```
cd hub
set TOFSIM_DIR=<dataset/tof_sim_v5 경로>            # 이 저장소 밖 워크트리 또는 UBAI ~/tof-sim-v5-lifesim
python -m tools.life_sim.runner --scenario a1_wake_first --backend numpy --posture oracle -v
python -m tools.life_sim.runner --scenario a1_wake_first --backend mujoco --posture gru --ckpt runs/<run>/ckpt_best.pt
python -m tools.life_sim.runner --scenario b_vent_choice --weather windy      # calm | windy | rain | winter | hot
python -m tools.life_sim.ab --scenario b_student_day --days 30               # 계정 A(합성 30 일 학습) vs B(전역 기본)
```

결과는 `runs/lifesim/<scenario>/` 에: `timeline.jsonl`(tick 마다 정답 라벨·판정·C_fatigue·C_focus·상태·개입·반응·환경·기기),
`interventions.jsonl`, `personalize.jsonl`(hub 의 개인화 로그 그대로), `summary.md`·`summary.json`, `timeline.png`.
A/B 는 `<scenario>_ab/{A,B}/` + `ab_summary.md` + `ab_fatigue.png`.

## 한 tick(score_period_sec = 10 s)

1. `tofgen.py` — 각본 구간(`scenario.Timeline.effective`)의 자세를 tofsim helper(`_target_pose`·`_plan_nods`·`_lerp_pose`·`_nod_offset`)
   로 프레임마다 만들고 센서 둘(cad04 DEVICE_SENSORS, 정면 arc)로 잰다. 졸음 구간은 10 Hz 전체, 긴 안정 구간은 `compress`(tick 당 n 장).
2. `posture.py` — 센서별 추론(oracle | hub tof_mlp | tof_sim_v5 GRU) → log-softmax 융합 → 1 s 다수결. 졸음은 격자 기반 끄덕임
   검출기(머리 거리 ≈ 0x03 head_delta_mm)가 nod_rate_hz·drowsy 를 낸다(모델이 drowsy 클래스를 내면 OR).
3. `environment.py` — CO₂(사람·창문·누설)·온도·조도(램프)·날씨(`deskmate/sensor/weather` 7 필드) 적분.
4. `hubio.py` — `SensorCache` 에 tof·tof_mlp·env·keystroke·weather 표본 → `LiveHub.tick_once`(build_frame → FSM → state/phase ·
   interaction/request · control/cmd). **engine.py·live.py 수정 없음.** 제어 어댑터는 `devices.DeviceRack`(계약 그대로, result 즉시).
5. `person.py` — 카드(수락/거절/무응답, 지연)·자동 실행(되돌리기 확률)·깨어남/자세 복귀 → `Timeline.override(upright …)` →
   다음 tick 프레임부터 자세가 바뀐다. 대본(`reaction.yaml profiles`)이 §A ①②③ 을 고정한다.

## 설정(전부 yaml, 코드에 숫자 없음)

| 파일 | 내용 |
|---|---|
| `config/scenarios/*.yaml` | 각본: seed·페르소나·시작 시각·FSM 프로파일·날씨·구간 목록(종류·길이·타이핑·피로 램프·끄덕임·창문)·압축 |
| `config/personas.yaml` | 페르소나 3(대학생·재택 개발자·수험생): pc_ratio·취침·키스트로크 원지표·CO₂ 발생·조도 |
| `config/reaction.yaml` | 반응 모델: arm×페르소나별 wake_p·accept_p·undo_p·fix_p, 지연·재발·대본 |
| `config/devices.yaml` | 기기 mock 효과 계수(선풍기 단·램프 lux·창문 환기율·날씨 배수) + 방 모델 |
| `config/posture.yaml` | 판정 백엔드·융합·다수결·oracle 혼동·끄덕임 검출기 임계값 |

## 알게 된 것(코드에서 확인, 시뮬로 재현)

- **졸음의 라우팅은 "자세성"** — ToF 0x03 의 `drowsy`/`nod_rate_hz` 가 ingest 에서 posture delta 1.0 이 되고(`ingest.yaml tof`),
  routing posture 그룹이 dominant → `ACTION_POSTURE` → personalize posture arms(`posture_voice`·`sound_cue`·`posture_card`).
  "깨우기" = Pi 5 앱의 음성(TTS)·알림음·화면 카드. fsm.yaml 의 `drowsy` guard(wake_alert, route environment)는 심박 reason 이
  필요해 꺼져 있다.
- **졸음만으로는 FATIGUE 가 확정되지 않는다** — 타이핑이 멈춘 비PC 컨텍스트에서 C_fatigue = (0.40·1 + 0.20·env + 0.15·elapsed)/0.75
  ≈ 0.59 < 0.70. 경과 90 분(elapsed 1.0) 이거나 CO₂ 상승(env 1.0)이 같이 있어야 넘는다. 각본은 그래서 "90 분 몰입 뒤 졸음".
- **MONITOR 가 한 tick 뒤 판정**(engine TODO) — 깨우기 효과는 수십 초 걸리므로 검출기가 졸음 플래그를 빨리 내리지 않으면
  (`clear_after_quiet_s`) 깨어났어도 ESCALATE 가 한 번 더 일어난다.
- **CO₂ 가 오른 방에서는 깨어나도 FOCUS 로 못 돌아온다** — baseline 정규화(MAD floor 15 ppm)로 env delta 가 1.0 에 붙어
  C_fatigue ≈ 0.47(0.30~0.70) 에서 RECOVERY 에 머문다(RECOVERY 는 상한 시간이 없다). 환기(창문)를 수락해야 회복.
- **ESCALATE 가 세 원인을 다 쓰면 REST ↔ RECOVERY ↔ ESCALATE 를 돈다** — `_remaining_options` 는 FATIGUE 재진입 때만 채워진다.
- **공기청정기 명령 경로가 없다** — `air_fan_up` arm 의 device 는 `vent_fan`(선풍기)이고 `air_purifier` target 은 control.yaml·
  personalize.yaml 어디에도 없다. 시뮬도 그대로(공기청정기 mock 은 자리만).
