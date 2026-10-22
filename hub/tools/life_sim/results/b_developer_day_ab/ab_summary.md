# A/B — b_developer_day (시뮬레이션, 실측 아님)

- A: 합성 30 일(night_owl, 에피소드 134, 피드백 134건, personal 정책)에서 시작 · B: 전역 prior

| 지표 | A(학습 프로필) | B(전역 기본) |
|---|---|---|
| interventions | 6 | 6 |
| auto | 0 | 0 |
| suggest | 6 | 6 |
| accept_rate | 0.833 | 0.667 |
| undone | 0 | 0 |
| woke | 1 | 1 |
| while_drowsy | 1 | 0 |
| posture_fixed | 0 | 0 |
| mean_c_fatigue | 0.597 | 0.595 |
| fatigue_ticks_ge_0.7 | 1232 | 1235 |
| sleep_suggested | False | False |
| ventilate | 0 | 0 |
| rest | True | True |

- A arms: {'break_short': 1, 'light_cool_bright': 3, 'posture_card': 2}
- B arms: {'break_short': 1, 'light_cool_bright': 2, 'light_warm_dim': 1, 'posture_card': 2}

## 규칙 검증(personalize.jsonl)

| 검사 | A | B |
|---|---|---|
| episodes | 6 | 6 |
| undo_then_suggest_ok | 0 | 0 |
| undo_then_suggest_violations | 0 | 0 |
| reject_reproposed_in_session | 0 | 0 |
| cooldown_violations | 0 | 0 |
| session_cap_violations | 0 | 0 |
| missing_explanation | 0 | 0 |

## A

# b_developer_day — 시뮬레이션 결과 (실측 아님)

재택 개발자의 하루 — 오후 시작, 긴 PC 몰입, 어두운 방 조명 개입, 밤 졸음 반복, 새벽 취침 권유 후보

- 페르소나 developer · seed 23 · FSM production · 반응 대본 stochastic · 날씨 {'temp_c': 14.0, 'humidity': 55, 'wind_ms': 2.0, 'condition': 'cloudy'}
- ToF numpy 백엔드 · 자세 판정 oracle · 3060 tick(510.0 분) · 프레임 47580 · 벽시계 675.4 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_PC → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_BREAK → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → FOCUS_MIXED → FOCUS_PC → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_BREAK → REST → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY
- 라우팅(route:cause 횟수): {'cognitive': 2, 'environment': 2, 'posture': 2}
- 자세 tick 정확도 0.996 · drowsy tick 재현율 1.0 (정답 drowsy tick 271, 오탐 tick 7) · 끄덕임 검출 {'0': 122, '1': 122}
- 첫 졸음(정답) 19210.0 s → 졸음 플래그 19200.0 s → 첫 ACTION 5030.0 s → 깨어남 19480 s → FOCUS 복귀 13850.0 s · REST 5220.0 s
- 사람: {'interventions': 6, 'auto': 0, 'suggest': 6, 'accepted': 5, 'rejected': 1, 'timeout': 0, 'undone': 0, 'woke': 1, 'while_drowsy': 1, 'posture_fixed': 0, 'arms': {'break_short': 1, 'light_cool_bright': 3, 'posture_card': 2}, 'effects': [], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 3, 'undo': 0, 'alert': 0, 'card': 6}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5030 | 19:53 | break_short | suggest | cognitive | None | reject |  |  |  |  | CO₂ 1131 ppm · 조도 95 lx 어두움 · forward_head 10분 · 5분 휴식 수락 19/24 · 효과 +0.78 · 사용자 |
| 5090 | 19:54 | light_cool_bright | suggest | environment | None | accept |  |  |  |  | CO₂ 1123 ppm · 조도 86 lx 어두움 · forward_head 11분 · 조명 밝고 차갑게 수락 14/17 · 효과 +0.87 · |
| 5160 | 19:56 | posture_card | suggest | posture | None | accept |  |  |  |  | CO₂ 1114 ppm · forward_head 12분 · 자세 안내 카드 수락 10/16 · 효과 +0.82 · 개인 정책 · 피드백 136 |
| 19110 | 23:48 | light_cool_bright | suggest | cognitive | None | accept |  |  |  |  | CO₂ 1209 ppm · 세션 5.3 h · 평소 취침 시각 지남 · 조명 밝고 차갑게 수락 15/18 · 효과 +0.86 · 개인 정책 ·  |
| 19480 | 23:54 | posture_card | suggest | posture | None | accept | Y | Y |  |  | CO₂ 1220 ppm · 졸음 1회 · 세션 5.4 h · 평소 취침 시각 지남 · 자세 안내 카드 수락 11/17 · 효과 +0.80 · 개 |
| 19580 | 23:56 | light_cool_bright | suggest | environment | None | accept |  |  |  |  | CO₂ 1227 ppm · 졸음 1회 · 세션 5.4 h · 평소 취침 시각 지남 · 조명 밝고 차갑게 수락 16/19 · 효과 +0.86 ·  |

## B

# b_developer_day — 시뮬레이션 결과 (실측 아님)

재택 개발자의 하루 — 오후 시작, 긴 PC 몰입, 어두운 방 조명 개입, 밤 졸음 반복, 새벽 취침 권유 후보

- 페르소나 developer · seed 23 · FSM production · 반응 대본 stochastic · 날씨 {'temp_c': 14.0, 'humidity': 55, 'wind_ms': 2.0, 'condition': 'cloudy'}
- ToF numpy 백엔드 · 자세 판정 oracle · 3060 tick(510.0 분) · 프레임 47580 · 벽시계 684.4 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_PC → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_BREAK → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → FOCUS_MIXED → FOCUS_PC → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_BREAK → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY
- 라우팅(route:cause 횟수): {'cognitive': 2, 'environment': 2, 'posture': 2}
- 자세 tick 정확도 0.996 · drowsy tick 재현율 1.0 (정답 drowsy tick 244, 오탐 tick 8) · 끄덕임 검출 {'0': 99, '1': 99}
- 첫 졸음(정답) 19210.0 s → 졸음 플래그 19200.0 s → 첫 ACTION 5030.0 s → 깨어남 19180 s → FOCUS 복귀 13850.0 s · REST 5220.0 s
- 사람: {'interventions': 6, 'auto': 0, 'suggest': 6, 'accepted': 4, 'rejected': 2, 'timeout': 0, 'undone': 0, 'woke': 1, 'while_drowsy': 0, 'posture_fixed': 0, 'arms': {'break_short': 1, 'light_cool_bright': 2, 'light_warm_dim': 1, 'posture_card': 2}, 'effects': [], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 2, 'undo': 0, 'alert': 0, 'card': 6}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5030 | 19:53 | break_short | suggest | cognitive | None | reject |  |  |  |  | CO₂ 1131 ppm · 조도 95 lx 어두움 · forward_head 10분 · 사용자 행동이 필요해 묻고 진행 · 기본 정책 · 피드백 |
| 5090 | 19:54 | light_cool_bright | suggest | environment | None | accept |  |  |  |  | CO₂ 1123 ppm · 조도 86 lx 어두움 · forward_head 11분 · 기본 정책 · 피드백 1건 |
| 5160 | 19:56 | posture_card | suggest | posture | None | accept |  |  |  |  | CO₂ 1114 ppm · forward_head 12분 · 기본 정책 · 피드백 2건 |
| 19110 | 23:48 | light_warm_dim | suggest | cognitive | None | reject |  |  |  |  | CO₂ 1209 ppm · 세션 5.3 h · 평소 취침 시각 지남 · 기본 정책 · 피드백 3건 |
| 19180 | 23:49 | light_cool_bright | suggest | environment | None | accept |  | Y |  |  | CO₂ 1203 ppm · 세션 5.3 h · 평소 취침 시각 지남 · 조명 밝고 차갑게 수락 1/1 · 효과 +0.16 · 기본 정책 · 피드 |
| 19270 | 23:51 | posture_card | suggest | posture | None | accept |  |  |  |  | CO₂ 1206 ppm · 졸음 1회 · 세션 5.4 h · 평소 취침 시각 지남 · 자세 안내 카드 수락 1/1 · 효과 +0.17 · 기본  |
