# 사용자 반응으로 배우는 피로 판단 (feat/reaction-ai)

> 처음엔 규칙 FSM 으로 시작하고, 사람마다 쌓인 **반응**으로 배운 모델이 피로 판단을 넘겨받는다.
> FSM 은 **지나친 개인화만 막는 울타리**로 남는다. 기본 꺼짐(`hub/deskmate_hub/config/learning.yaml enabled: false`) —
> 꺼져 있으면 hub 는 지금 규칙 FSM 그대로다(개발 원칙 2: 1단계 FSM 단독 완전 동작).

## 구조

```
SensorFrame ─► compute_scores(FSM) ─► c_fsm ─┐
      │                                       ├─► c = c_fsm + clip(α·(p − c_fsm), −down_max, +up_max) ─► FSM 상태·임계값·유지
      └─► 특징 x ─► 사람별 모델 p = σ(logit(c_fsm) + w·x) ┘      (c_fsm ≥ keep_floor 이면 낮추지 않음)
                         ▲
        라벨 ◄── 앱 KSS 응답(15 분) · 앱 무응답(자리에 있음) · 카드 수락/거절 · 자동 실행 되돌리기 · 확인 카드 예/아니요
```

| 부분 | 파일 | 설명 |
|---|---|---|
| 모델 | `deskmate_hub/learning/reaction.py` `OnlineLogistic` | 순수 Python 온라인 로지스틱 회귀(AdaGrad·L2). 보드 제한 Python 에서 돈다. 특징 22 개 |
| 잔차 학습 | `residual: true` | 출발점이 FSM 점수(logit(c_fsm))라 가중치 0 이면 p = c_fsm. 첫 라벨부터 FSM 만큼 맞히고, 라벨이 FSM 과 다르게 말하는 곳만 배운다 |
| 판단 넘겨받기 | `ReactionLearner.adjust` ← `FSMEngine.score_adjust` | α 는 라벨 `n_min` 개 전엔 0(FSM 그대로). 라벨이 `n_min`~`n_full` 쌓이고 최근 `acc_window` 라벨에서 모델이 FSM 보다 잘 맞힐수록 `alpha_max` 까지(같으면 절반 — 이때 p ≈ c_fsm 이라 바뀌는 게 거의 없다) |
| 울타리 | `up_max` 0.25·`down_max` 0.10·`keep_floor` | 모델이 FSM 점수를 바꿀 수 있는 폭(낮추는 폭이 더 좁다 — 졸음 놓침이 더 위험), 강한 증거(엎드림·강한 졸음) 보호 |
| 앱 KSS 라벨 | `on_self_report` ← `live.py`(cache.fatigue_label) | Pi 5 피로 기록 앱(PR #58)이 15 분마다 받는 KSS 응답(`deskmate/fatigue/label`). KSS ≥ `kss_label_at`(7) 이면 1. FSM 상태와 상관없이 들어와 FSM 이 틀리는 곳을 배울 수 있다. 같은 응답은 한 번만 |
| 앱 무응답 라벨 | `on_prompt_missed` ← `live.py`(cache.fatigue_missed) | 앱의 `prompt_missed` — 자리에 있고 타이핑하지 않으면 1(`missed_weight` 0.5). 졸 때는 답을 못 해서 KSS 응답만 쓰면 라벨이 깨어 있을 때로 치우친다 |
| 반응 라벨 | `after_tick`·`on_feedback` | 카드 수락 1 · 거절·되돌리기 0. 개입 뒤 C_fsm 이 떨어졌나로 정하는 라벨(effect·no_effect_awake)은 FSM 점수로 만든 정답이라 `effect_weight: 0`(기본)으로 끔 |
| 확인 카드 | `maybe_checkin` | 모델이 애매할 때(`probe_band`) `probe_gap_s` 마다, 세션당 `probe_max`. 앱이 최근 `probe_gap_s` 안에 물었으면 묻지 않는다. 앱이 없는 기간의 라벨 |
| 저장 | `state_path` | 가중치·라벨 수·최근 맞힘 — 세션·날을 넘어 이어 배운다 |
| hub 연결 | `live.py` | `learning_cfg`·`learner`, 확인 카드 `interaction/request kind: checkin_suggest`(응답은 학습에만, 제어·FSM 에는 안 감), `sensor_summary.learning` |
| 앱 응답 수신 | `ingest/mqtt_lines.py`·`cache.py`·`mapping.py` | `deskmate/fatigue/label` 의 `event: kss` 만 `cache.fatigue_label` 에(1~9, 신선도는 응답 `ts` 기준, 다시 온 옛 응답 무시). paho 경로도 구독. FSM 규칙 입력은 아니다 |

## 시뮬레이션 (life_sim)

- `python -m tools.life_sim learn --person N --days D --arm fsm|ai` — 한 사람이 D 일을 산다. 날마다 자유 생활 각본(`daygen`,
  잠재 피로 켬, 같은 사람이면 피로 계수·유형이 같음). `ai` 는 `learner.json` 을 다음 날로 넘긴다.
- 사람의 확인 카드 응답: 화면을 보면(`checkin.attend_*`) 지금 졸림 S 대로 예 = sigmoid((S − s50)/width) — `reaction.yaml checkin`.
  응답 난수는 사람 반응 난수와 따로다 — 섞이면 카드 하나가 뒤의 깸·카드 응답을 전부 밀어 α = 0 이어도 arm 이 갈라졌다(10-23 learn14).
- 앱 KSS 질문(`self_report.py`, devices.yaml `self_report`): `learn` 은 두 arm 모두 켠다(`--no-self-report` 로 끔). 15 분마다 묻고
  KSS = round(1 + 10·S), 30 % 확률로 ±1, 5~60 s 늦게, 질문 순간 자리 비움·졸음이면 놓침. 사람에게 효과 없음·난수 따로.
- 지표(`summary.reaction_ai`, 정답 = 잠재 피로): 피로 구간 수·놓침·시작부터 첫 개입까지·헛개입(정답 focus 때 개입)·수락/거절/되돌리기·
  깨어남·휴식 분·확인 카드 수와 답·학습 상태(α·라벨·맞힘).
- 빠른 확인: `--synthetic --posture oracle --oracle-noise 0.2`(합성 격자 + 정답 자세를 20 % 틀리게 = GRU 깜빡임 흉내).

### 10-23 합성 확인(4명 × 6일, PC)

| 판 | 무엇이 문제였나 | 결과 |
|---|---|---|
| 첫 판(learn14) | 라벨이 FSM 점수로 만든 회복·집중 중 '아니요' 위주라 FSM 이 거의 다 맞힘, 모델은 0 에서 출발 | 라벨 18~39 개에도 α = 0. 확인 카드가 사람 난수를 밀어 α = 0 인데 arm 이 갈라짐 |
| 잔차·앱 KSS·난수 분리(learnfix) | 졸면 앱에 답을 못 해 라벨이 깨어 있을 때로 치우침(응답 270: 졸림 65, 졸다 놓침 37) → 자세 가중치가 음수 | α 0.6~0.8 까지 오르지만 4~6일째 놓침 49 % vs FSM 30 %, 첫 개입 231 s vs 94 s |
| + 앱 무응답 라벨·낮춤 폭 0.10(learnfix2) | 4명 × 6일은 작다(사람마다 차이 큼), 합성 격자·정답 자세 20 % 틀림 | 4~6일째 헛개입 50 vs FSM 71(−30 %), 첫 개입 92 s vs 94 s, 놓침 38 % vs 30 %, 피로 302 분 vs 255 분, 휴식 519 분 vs 710 분. 자세 가중치 음수 사라짐 |

### 10-23 밤 UBAI learn_v10 — 24명 × 기기 위치 5곳 × FSM/AI × 14일(MuJoCo + GRU)

- 사람: `--roles cycle` 로 여섯 역할(학생·개발자·수험생·디자이너·밤 작업 작가·아침형 연구자, daygen `EXTRA_ROLES`·reaction.yaml
  personas)을 사람 번호로 돌린다 — 24명이면 역할마다 4명. 피로 계수는 사람 시드, 반응·피로 범위는 역할.
- 체형·방: `scene_seed` = 사람마다 고정(SMPL-X 성별·체형, 의자·책상 높이, 방, 기기 둘레 반지름 0.6~1.1 m) — 14일 내내 같다.
- 기기 위치: `--devices 5 --drive k` — 사람 둘레 호 −40·−20·0·20·40°(− = 사람 오른쪽)에 기기를 둘 수 있게 뽑고, 실행마다 그중
  한 곳의 기기 1대(센서 2개)로 hub 폐루프를 돈다. 같은 사람·같은 날 각본·같은 체형·같은 장착 오차에서 위치만 다르다.
  사람 × 위치 = 120 폐루프 × FSM/AI = 240 실행.
- 실행: UBAI `q/learn_pack.sbatch`(한 작업에 learn 40개 병렬), `q/learn_tasks_v10_{1..6}.txt`(4명씩), 러너 `q/queue3.sh`
  (QUOTA 3), 결과 `runs/learn_v10`, 집계 `python3 -I q/agg_learn.py runs/learn_v10`.
- 시험(10-23 21:50, 짧은 하루): 같은 사람이 −40° 에서 자세 정확도 0.72, +40° 에서 0.41 — 위치 효과가 크다.

### v11 — 심박 입력 + 개입 방식(기기)까지 사람별로 배움 (10-24 사용자 "추천", v10 뒤에 같은 설계)

- 입력: 재실 기준 심박 하락 `SensorFrame.hr_drop_bpm`(mapping `_hr_drop_feature`, ingest.yaml `learning_inputs` — 기준선 = 책상 재실 ∧
  깨어 움직일 때 심박 중앙값, 가만히 있으면 얼림; 10-23 HR 규칙 시뮬의 Bp 방식)·mmWave 체동 `mm_motion` 을 학습기 특징에 더한다
  (hr_drop·hr_avail·mm_motion·mm_avail). FSM 규칙에는 안 들어간다. 키 입력은 원래 keystroke 신호로 들어간다.
- 시뮬 심박: `--hr` 로 mmWave 심박 모델(posture_sim/mmwave.py HeartModel, 가정값) — 안정 심박·타이핑 가산·이완 폭은 사람 고유값(person_seed).
- 출력: `--learn-outputs` 면 ai arm 의 hub personalize 정책(컨텍스트 밴딧)을 사람별 `policy.json` 으로 14일 이어 배운다(profile persist).
  선택지 = 무드등 차갑게·따뜻하게, 선풍기, 음성, 알림음, 자세 카드, 휴식·환기 카드 + life_sim 에서만 더한 화면 밝게·공기청정기 세게
  (devices.yaml `policy_extra_arms`; hub 기본 personalize.yaml 은 그대로). 사람마다 기기별 반응은 reaction.yaml(역할별 wake·posture_fix).
- 비교: v10 = "언제만 배우는 AI"(출력은 FSM 고정 규칙, 심박 없음) · v11 = 언제 + 어떤 기기 + 심박. 두 판 모두 FSM arm 이 기준.
- 사람 선호(`--person-prefs`): 더위·어두움에 지치는 정도를 사람마다 — 덥다고 느끼는 온도 25~29 °C·가산 0.1~0.6, 어둡다고 느끼는
  조도 150~300 lx·가산 0.1~0.5(잠재 피로 fatigue.py, 사람 시드, 다른 계수 뽑기 순서는 그대로). 생활 패턴은 역할(시작 시각대)·
  사람별 오후 처짐·밤 가산(circadian)으로 이미 다르다. 미룬 것(v12): 기기별 선호·비선호(조명 색·소리) 반응, 음악 출력.
- UBAI: repo_v11ai, 작업 이름 lsai11, 결과 runs/learn_v11(계정1 1~12번 · 계정2 13~24번), v10 lsai 가 끝나면 대기 러너가 낸다.

### 공통모델 → 시연용 개인화 (10-24 사용자: 2번 방향 — 공통모델은 조금, 개인화와 함께 키움)

- 공통모델 = **선호가 별로 없는 사람**(`--persona neutral`: 활동 고르게, 반응 기본값, 기기 호불호 없음, 밤 눈부심만 `--night-glare`) 여럿이
  learn 으로 배운 상태를 `python -m tools.life_sim common --runs <폴더 glob> --out <dir> --kappa 0.2` 로 합친다(`tools/life_sim/common.py`).
  피로 판단 = 잔차 가중치 평균(AdaGrad 누적은 κ 배), 개입 방식 = arm·축별 사후분포를 κ 무게로 모음. 개인 라벨·피드백 수는 비운다.
- 개인화 = `learn --init-from <dir>` — 공통 상태에서 출발. 학습기는 개인 라벨 전에도 `common_alpha`(0.3)만큼 공통모델을 쓰고,
  그 사람 라벨에서 FSM 보다 못하면 걷는다. 정책은 개인 피드백 `cold_start.personal_min` 전까지 공통(전역) 모드.
- 시연 페르소나(daygen `EXTRA_ROLES`, reaction.yaml personas):
  - `book_examinee` 책으로 공부하는 수험생 — 늘 피곤(시작 피로·빨리 지침·밤 가산↑), 필기·읽기(키 입력 없음 → 비PC 맥락에서 FSM 키 가중치 0),
    조명엔 잘 깨고 선풍기 소음·신나는 음악은 싫어함, 백색소음은 괜찮음. 책 문제 풀이의 숙인 자세는 평소 자세라 자세 증거를 0 으로
    (daygen `ROLE_INGEST_SET` → ingest.yaml `tof.posture_*.lean_forward`).
  - `pc_student` 컴퓨터를 주로 쓰는 대학생 — 휴대폰·딴짓(통화·옆 보기·기대기)·나쁜 자세(거북목·턱괴기·팔꿈치), 자세 안내를 잘 안 따르고
    음성 안내는 싫어함, 신나는 음악·화면 밝게엔 잘 깸.
  - 세 번째는 미정.
- 출력 선택지(life_sim 에서만 hub personalize 에 더함): 화면 밝게·공기청정기 세게·신나는 음악·백색소음·무드등 자연광(공부)/청백색(각성)/
  주황(휴식·밤). 밤(22~6시)엔 청백색·화면 밝게를 누구나 끈다고 봐서, 정책이 때에 맞는 색을 배운다.

### 10-24 결과 — UBAI MuJoCo + GRU(opt_l8v5_c256_best), 24명 × 위치 5곳 × FSM/AI × 14일 (시뮬, 정답 = 잠재 피로)

| 판 · 8~14일, 하루 평균 | arm | 피로 분 | 놓침 % | 첫 개입 s | 개입 | 헛개입 | 휴식 분 | 자세 정확도 |
|---|---|---|---|---|---|---|---|---|
| v10(언제만 배움) 240 실행 | FSM | 30.0 | 57.0 | 194 | 14.4 | 5.4 | 42.5 | 0.605 |
| | AI | 33.3 | 58.8 | 212 | 13.0 | **4.2** | **34.8** | 0.606 |
| v11(+심박·기기 선택·호불호) 13~24번 120 실행 | FSM | 29.5 | 51.1 | 192 | 15.7 | 5.9 | 47.3 | 0.621 |
| | AI | 34.6 | 57.4 | 212 | 13.6 | **4.1** | **36.0** | 0.627 |

- AI 는 헛개입(−22~31 %)·강제 휴식(−18~24 %)을 확실히 줄이지만, 놓침·피로 시간은 조금 는다(v11 에서 더). 울타리(낮춤 0.10)로도 남는다.
- 둘 다 놓침이 50~60 % — GRU 자세 정확도가 실제에 가까운 장면에서 0.6 이라서(위치 −20° 0.66 최고, 읽기·필기가 많은 수험생·연구자 0.47~0.50).
  책 공부 장면 보강 학습(`tof-sim_ubai_results_1024/book_study`)·졸음 보강 학습(dz)이 먼저다.
- v11 의 기기 선택은 14일로는 덜 배워졌다: 많이 고른 것이 환기 카드·화면 밝게·청백색 조명. 종이로 공부하는 수험생에게도 화면 밝게(깨움 0.05)를
  자주 골랐다 — 자동 실행 arm 은 되돌리지 않으면 수락으로 쳐지는 보상 구조라 효과(깸)가 약해도 남는다. 효과 축 보상을 키우거나 공통 사전분포가 필요.
- 시연 기준선(demo_v12, 수험생·대학생 × 위치 5 × 14일): AI 헛개입 7.2 → 5.2/일, 휴식 64 → 52 분/일, 놓침 59 → 63 %.
  공통모델 v1(무난한 24명 × 14일, 라벨 4,756)에서 출발하는 판(demo_v12c)과 짝 비교 중.

## 한계

- 사람·피로·반응은 전부 가정값(시뮬). 실제 사람에게 맞는지는 실사용 반응 기록이 있어야 안다.
- 앱 KSS 응답이 없으면 라벨은 개입·확인 카드가 있을 때만 생긴다(선택 편향). 확인 카드는 사용자에게 부담이라 상한을 둔다.
  앱 응답은 수집 기간에만 있을 수 있고, KSS 응답 모양(±1, 졸면 놓침)도 각본이다.
- 모델은 작은 선형 모델이다 — 사람마다 적은 라벨(수십 개)로 배우려는 선택. 공통 사전학습(시뮬 대량 데이터)으로 초기값을 줄 수 있다.
