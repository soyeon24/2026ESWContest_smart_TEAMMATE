# a1_wake_first — 시뮬레이션 결과 (실측 아님)

90 분 몰입(타이핑, 창문 열린 방) → 오후 졸음(끄덕임) → 첫 깨우기 개입에 반응해 바른 자세로 돌아온다

- 페르소나 student · seed 7 · FSM demo · 반응 대본 wake_first · 날씨 {'temp_c': 17.0, 'humidity': 50, 'wind_ms': 1.0, 'condition': 'clear'}
- ToF numpy 백엔드 · 자세 판정 oracle · 690 tick(115.0 분) · 프레임 17700 · 벽시계 253.7 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_MIXED → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → FOCUS_MIXED
- 라우팅(route:cause 횟수): {'posture': 1}
- 자세 tick 정확도 0.999 · drowsy tick 재현율 1.0 (정답 drowsy tick 9, 오탐 tick 2) · 끄덕임 검출 {'0': 2, '1': 3}
- 첫 졸음(정답) 5410.0 s → 졸음 플래그 5400.0 s → 첫 ACTION 5490.0 s → 깨어남 5490 s → FOCUS 복귀 5520.0 s · REST None s
- 사람: {'interventions': 1, 'auto': 1, 'suggest': 0, 'accepted': 0, 'rejected': 0, 'timeout': 0, 'undone': 0, 'woke': 1, 'while_drowsy': 1, 'posture_fixed': 0, 'arms': {'posture_card': 1}, 'effects': [], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 0, 'undo': 0, 'alert': 1, 'card': 0}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5490 | 14:31 | posture_card | auto | posture | wake | auto_kept | Y | Y |  |  | 졸음 1회 · 기본 정책 · 피드백 0건 |
