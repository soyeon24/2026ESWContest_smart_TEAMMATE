# a3_never_wake — 시뮬레이션 결과 (실측 아님)

90 분 몰입 → 오후 졸음. 어떤 개입에도 반응하지 않고 계속 존다. FSM 이 원인을 바꿔 가며 격상하다가 REST 로 간다

- 페르소나 student · seed 7 · FSM demo · 반응 대본 never_wake · 날씨 {'temp_c': 17.0, 'humidity': 50, 'wind_ms': 1.0, 'condition': 'clear'}
- ToF numpy 백엔드 · 자세 판정 oracle · 792 tick(132.0 분) · 프레임 29520 · 벽시계 428.6 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_MIXED → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_BREAK → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → FOCUS_NPC
- 라우팅(route:cause 횟수): {'posture': 1, 'cognitive': 1, 'environment': 1}
- 자세 tick 정확도 0.999 · drowsy tick 재현율 1.0 (정답 drowsy tick 239, 오탐 tick 2) · 끄덕임 검출 {'0': 2, '1': 3}
- 첫 졸음(정답) 5410.0 s → 졸음 플래그 5400.0 s → 첫 ACTION 5490.0 s → 깨어남 None s → FOCUS 복귀 7860.0 s · REST 5630.0 s
- 사람: {'interventions': 3, 'auto': 1, 'suggest': 2, 'accepted': 0, 'rejected': 0, 'timeout': 2, 'undone': 0, 'woke': 0, 'while_drowsy': 3, 'posture_fixed': 0, 'arms': {'break_long': 1, 'posture_card': 1, 'ventilate_suggest': 1}, 'effects': [], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 0, 'undo': 0, 'alert': 1, 'card': 2}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5490 | 14:31 | posture_card | auto | posture | ignore | auto_kept | Y |  |  |  | 졸음 1회 · 기본 정책 · 피드백 0건 |
| 5540 | 14:32 | break_long | suggest | cognitive | ignore | timeout | Y |  |  |  | 졸음 1회 · 기본 정책 · 피드백 0건 |
| 5600 | 14:33 | ventilate_suggest | suggest | environment | ignore | timeout | Y |  |  |  | 졸음 1회 · 환기 15분 · 기본 정책 · 피드백 1건 |
