# a4_stuffy_room — 시뮬레이션 결과 (실측 아님)

90 분 몰입(닫힌 방, CO₂ 상승) → 오후 졸음 → 깨우기 → 환기 권유 → 회복

- 페르소나 student · seed 7 · FSM demo · 반응 대본 stochastic · 날씨 {'temp_c': 17.0, 'humidity': 50, 'wind_ms': 1.0, 'condition': 'clear'}
- ToF numpy 백엔드 · 자세 판정 oracle · 780 tick(130.0 분) · 프레임 21300 · 벽시계 326.0 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_MIXED → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_BREAK → REST → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY
- 라우팅(route:cause 횟수): {'posture': 1, 'cognitive': 1, 'environment': 1}
- 자세 tick 정확도 0.997 · drowsy tick 재현율 1.0 (정답 drowsy tick 51, 오탐 tick 4) · 끄덕임 검출 {'0': 31, '1': 32}
- 첫 졸음(정답) 5410.0 s → 졸음 플래그 5400.0 s → 첫 ACTION 5450.0 s → 깨어남 5490 s → FOCUS 복귀 None s · REST 5510.0 s
- 사람: {'interventions': 3, 'auto': 1, 'suggest': 2, 'accepted': 1, 'rejected': 1, 'timeout': 0, 'undone': 0, 'woke': 1, 'while_drowsy': 3, 'posture_fixed': 1, 'arms': {'break_long': 1, 'posture_card': 1, 'ventilate_suggest': 1}, 'effects': ['break:12min'], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 0, 'undo': 0, 'alert': 1, 'card': 2}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5450 | 14:30 | posture_card | auto | posture | None | auto_kept | Y |  |  |  | CO₂ 1081 ppm · 졸음 1회 · 기본 정책 · 피드백 0건 |
| 5490 | 14:31 | break_long | suggest | cognitive | None | accept | Y | Y | Y | break:12min | CO₂ 1067 ppm · 졸음 1회 · 기본 정책 · 피드백 0건 |
| 6510 | 14:48 | ventilate_suggest | suggest | environment | None | reject | Y |  |  |  | CO₂ 1151 ppm · 졸음 2회 · 환기 15분 · 기본 정책 · 피드백 2건 |
