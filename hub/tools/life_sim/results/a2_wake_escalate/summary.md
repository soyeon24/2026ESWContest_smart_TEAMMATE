# a2_wake_escalate — 시뮬레이션 결과 (실측 아님)

90 분 몰입 → 오후 졸음. 첫 깨우기 개입을 무시하고 계속 졸다가 두 번째(격상) 개입에 깬다

- 페르소나 student · seed 7 · FSM demo · 반응 대본 wake_on_escalate · 날씨 {'temp_c': 17.0, 'humidity': 50, 'wind_ms': 1.0, 'condition': 'clear'}
- ToF numpy 백엔드 · 자세 판정 oracle · 720 tick(120.0 분) · 프레임 20700 · 벽시계 314.9 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_MIXED → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_BREAK → REST → RECOVERY → FOCUS_MIXED → FOCUS_NPC
- 라우팅(route:cause 횟수): {'posture': 1, 'cognitive': 1}
- 자세 tick 정확도 0.999 · drowsy tick 재현율 1.0 (정답 drowsy tick 17, 오탐 tick 2) · 끄덕임 검출 {'0': 2, '1': 3}
- 첫 졸음(정답) 5410.0 s → 졸음 플래그 5400.0 s → 첫 ACTION 5490.0 s → 깨어남 5540 s → FOCUS 복귀 5640.0 s · REST 5570.0 s
- 사람: {'interventions': 2, 'auto': 1, 'suggest': 1, 'accepted': 1, 'rejected': 0, 'timeout': 0, 'undone': 0, 'woke': 1, 'while_drowsy': 2, 'posture_fixed': 1, 'arms': {'break_long': 1, 'posture_card': 1}, 'effects': ['break:12min'], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 0, 'undo': 0, 'alert': 1, 'card': 1}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5490 | 14:31 | posture_card | auto | posture | ignore | auto_kept | Y |  |  |  | 졸음 1회 · 기본 정책 · 피드백 0건 |
| 5540 | 14:32 | break_long | suggest | cognitive | wake | accept | Y | Y | Y | break:12min | 졸음 1회 · 기본 정책 · 피드백 0건 |
