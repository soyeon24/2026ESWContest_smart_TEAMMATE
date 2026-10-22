# life_sim 인계 노트 (2026-10-22, 브랜치 `feat/life-scenario-sim-oracle`)

이 브랜치는 **로컬 PC(UBAI 미접속)에서 numpy 백엔드 + oracle 자세**로 폐루프를 끝까지 돌린 것이다. 원격 세션이 UBAI 에서
MuJoCo + GRU 로 이어받을 때 갈아끼울 지점과 §A·§B 에서 나온 것을 적는다. 전부 시뮬레이션(실측 아님).

## 1. 무엇이 "oracle 자세·numpy 백엔드" 인가
| 단계 | 로컬에서 쓴 것 | 원격에서 바꿀 것 |
|---|---|---|
| ToF 프레임 | `tofgen.TofGenerator(backend="numpy")` — tofsim `body.build_scene` + `Sensor.measure_surfaces` (원시 프리미티브 레이캐스트, plain 장면) | `--backend mujoco` → `MjDesk.cast` + `mj_scene.sensor_frame` (이미 구현, 로컬 mujoco 3.9 로 속도만 확인) |
| 자세 판정 | `posture.OracleEstimator` — 정답 라벨을 `config/posture.yaml oracle.accuracy/confusion` 으로 흐린 확률(모델 없음) | `--posture gru --ckpt runs/<run>/ckpt_best.pt` → `posture.GruEstimator`(torch PostureNet, 센서별 은닉 상태, 체크포인트 labels 순서) |
| 졸음 플래그 | `posture.NodDetector` — 격자의 머리 거리(위 3 행 사람 zone 평균 mm) 하강/복귀로 끄덕임 횟수 → nod_rate_hz·drowsy. 라벨 안 봄. oracle 의 drowsy 라벨과 OR | 그대로 쓰되 GRU 의 drowsy 클래스와 OR (`PostureStage.observe`) |
| 센서 배치·모델 | 로컬 tofsim 워크트리 session.py 의 DEVICE_SENSORS(cad04 값과 같음), `TOFSIM_L8_PARAMS` 미설정(기본 SensorModel) | `~/tof-sim-v5-lifesim` 의 session.py, 보정값 쓰면 `TOFSIM_L8_PARAMS` 지정 후 `summary.json tof.sensor_params_env` 로 기록됨 |

**갈아끼울 함수(자세 판정 입력)**: `posture.PostureStage.observe(t, grids, truth)` — `grids = {sensor_index: (dist_mm[8,8] int16, status[8,8] uint8)}`
(tofsim `Sensor.measure` 출력 그대로). 안에서 `self.est.step(si, dist, status, truth)` 가 센서별 확률 벡터를 내고, 융합·다수결·끄덕임은
공통이다. 새 모델은 `step()` 을 가진 클래스를 추가하고 `PostureStage.__init__` 의 backend 분기에 붙이면 된다. `truth` 는 oracle 만 쓴다.
hub 로 들어가는 표본은 `tof_sample()`(0x03 모사: present·posture·nod_rate_hz·drowsy)과 `tof_mlp_sample()`(Pi 4 모델 판정 슬롯)이다.

실행(원격): `cd hub && export TOFSIM_DIR=~/tof-sim-v5-lifesim PYTHONUTF8=1 && python -m tools.life_sim.runner --scenario a1_wake_first --backend mujoco --posture gru --ckpt <ckpt> -v`
(`--out runs/lifesim/<persona>_<scenario>` 로 두면 지시문 경로와 같다). mp4 는 미구현(record_session.py 방식 이식 남음).

## 2. §A 에서 찾은 FSM 제약 (engine.py 미수정 — 보고만)
1. **졸음 → 자세성 라우팅.** ToF 0x03 `drowsy`/`nod_rate_hz` → `ingest.yaml tof.posture_delta drowsy 1.0` → routing posture 그룹 dominant →
   ACTION_POSTURE → personalize posture arms(posture_voice·sound_cue·posture_card). "깨우기" = Pi 5 음성·알림음·카드.
2. **drowsy guard 는 심박 의존.** fsm.yaml `guards.drowsy`(wake_alert, route environment)는 `respiration heart_slow` reason 이 필요해 `enabled: false`.
   ToF 끄덕임 reason(head_down/nod)으로 바꾸지 않으면 켜지지 않는다.
3. **비PC 에서 졸음만으론 확정 불가.** 타이핑이 멈추면 keystroke 미가용 → C_fatigue = (0.40·1 + 0.20·env + 0.15·elapsed)/0.75 ≈ 0.59 < 0.70.
   경과 90 분(elapsed 1.0) 또는 CO₂ 상승(env 1.0)이 같이 있어야 넘는다. 각본은 그래서 "90 분 몰입 뒤 졸음".
4. **환경 원인은 첫 라우팅이 되지 못한다.** 비PC 자세 0 이면 최대 (0.20+0.15)/0.75 = 0.47; 자세가 있으면 자세가 dominant; PC 는 env 가중치 0.10.
   ACTION_ENV 는 ESCALATE 재시도(제안 게이트)로만 나온다.
5. **MONITOR 한 tick 판정**(engine TODO). 깨우기 효과는 수십 초 걸리므로 검출기가 플래그를 빨리 내리지 않으면(`clear_after_quiet_s`)
   깨어나도 ESCALATE 가 한 번 더 난다. RECOVERY 는 상한 시간이 없어 0.30~0.70 에 머물면 무한 대기(CO₂ 오른 방).
6. 덤: ESCALATE 가 세 원인을 다 쓰면 REST↔RECOVERY↔ESCALATE 반복(새 개입 없음, `_remaining_options` 는 FATIGUE 재진입 때만 채움);
   `air_fan_up`(공기청정기) arm 의 device 가 `vent_fan`(선풍기)이고 `air_purifier` target 은 hub 에 없음; 겨울 환기 5 분은 `Situation.month`(시계) 기준이라
   날씨 토픽 season 으로는 안 바뀜; baseline 정규화(MAD floor 15 ppm)로 CO₂ +50 ppm 이면 env delta 1.0.

## 3. §B 수치 (results/ 에 JSONL·PNG·summary, `b_*_day_ab/{A,B}`; A = 합성 30 일 학습 프로필, B = 전역 prior, 같은 seed·각본)
| 각본 | 결과 |
|---|---|
| a1_wake_first | ACTION_POSTURE(posture_card 자동) → 깸 → MONITOR → RECOVERY → FOCUS 30 s. 끄덕임 검출 27 회 중 25 회 |
| a2_wake_escalate | 첫 개입 무시 → ESCALATE → break_long 제안 수락 → REST → FOCUS |
| a3_never_wake | ACTION_POSTURE → ACTION_BREAK(무응답) → ACTION_ENV(무응답) → REST↔RECOVERY↔ESCALATE 반복 |
| a4_stuffy_room | 깨어나도 CO₂ 로 C≈0.43 → RECOVERY 머묾 → 재발 → 환기 카드(거절) |
| b_vent_choice calm / windy / rain / winter(10월) / winter(1월 ×3 seed) | air_fan_up / **ventilate 수락("바람 불어 환기 먼저")** / air_fan_up(환기 제외) / ventilate "15분" / air_fan_up(5 분 규칙 시뮬 미확인) |

| 페르소나×하루 | 개입 A/B | 수락률 A/B | 깨우기 성공 A/B | 환기 A/B | 취침 권유 | 평균 C_fatigue A/B |
|---|---|---|---|---|---|---|
| 대학생 14:00~00:30 | 7 / 9 | 1.0 / 1.0 | 3 / 2 | 1 / 0 | 없음 | 0.493 / 0.505 |
| 재택 개발자 18:30~03:00 | 6 / 6 | 0.83 / 0.67 | 1 / 1 | 0 / 0 | 없음 | 0.597 / 0.595 |
| 수험생 13:30~00:00 | 3 / 3 | 0.5 / 0.0 | 0 / 0 | 0 / 0 | 없음 | 0.536 / 0.542 |
- A 는 페르소나 선호 arm(대학생 음성·긴 휴식, 개발자 차가운 조명, 수험생 공기)을 고르고 설명에 개인 통계("수락 33/40 · 효과 +0.90 · 개인 정책")가 붙는다.
- 설명 한 줄은 모든 에피소드에 있음. 거절 arm 세션 내 재제안 0, 쿨다운 위반 0. 되돌리기 0 회 → "되돌리기 뒤 제안 격하" 는 로그로 못 봄(`ab.verify_policy_rules` 단위 테스트만).
- 세션 상한 6 회 뒤엔 정책이 빠지고 FSM 기본 카드(fsm_default/env_default). 취침 권유 미발생: "직전 개입 2 회 무효" 가 수락 많은 반응에서 성립 안 함.
- 하루 개입이 3~9 회에 그치는 이유 = 제약 6(원인 소진 → REST 반복). 자리비움(IDLE) 뒤 새 세션에서만 다시 CAUSE_ANALYSIS.
- 수치는 확률 반응(reaction.yaml, 손으로 적은 가정)과 oracle 자세에 좌우된다. 실측 모델(10-19 drowsy 재현율 0)과는 무관.

## 4. 테스트
`hub/tests/test_life_sim.py` 13개(tofsim 없으면 짧은 폐루프 1개 skip). docker python:3.11 에서 hub 전체 348 passed · 1 skipped(amqtt) · 1 xfailed.
