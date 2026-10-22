# b_vent_choice — 시뮬레이션 결과 (실측 아님)

닫힌 방 90 분 필기 → CO₂ 상승 → 턱괴기 → 자세 개입 무시 → 격상 → 환경 개입(환기·선풍기·조명) 선택 — 날씨 변주용

- 페르소나 examinee · seed 5 · FSM production · 반응 대본 ignore_first_any · 날씨 {'temp_c': 17.0, 'humidity': 50, 'wind_ms': 1.0, 'condition': 'clear'}
- ToF numpy 백엔드 · 자세 판정 oracle · 1020 tick(170.0 분) · 프레임 4860 · 벽시계 83.9 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_NPC → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_BREAK → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY
- 라우팅(route:cause 횟수): {'posture': 1, 'environment': 1, 'cognitive': 1}
- 자세 tick 정확도 0.996 · drowsy tick 재현율 None (정답 drowsy tick 0, 오탐 tick 0) · 끄덕임 검출 {'0': 0, '1': 0}
- 첫 졸음(정답) None s → 졸음 플래그 None s → 첫 ACTION 6200.0 s → 깨어남 None s → FOCUS 복귀 None s · REST 6350.0 s
- 사람: {'interventions': 3, 'auto': 1, 'suggest': 2, 'accepted': 0, 'rejected': 2, 'timeout': 0, 'undone': 0, 'woke': 0, 'while_drowsy': 0, 'posture_fixed': 1, 'arms': {'air_fan_up': 1, 'break_long': 1, 'posture_card': 1}, 'effects': [], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 0, 'undo': 0, 'alert': 1, 'card': 2}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 6200 | 11:43 | posture_card | auto | posture | ignore | auto_kept |  |  | Y |  | CO₂ 1560 ppm · 기본 정책 · 피드백 0건 |
| 6240 | 11:44 | air_fan_up | suggest | environment | None | reject |  |  |  |  | CO₂ 1572 ppm · 기본 정책 · 피드백 0건 |
| 6300 | 11:45 | break_long | suggest | cognitive | None | reject |  |  |  |  | CO₂ 1555 ppm · 기본 정책 · 피드백 1건 |
