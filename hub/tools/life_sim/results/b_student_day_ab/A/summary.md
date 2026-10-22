# b_student_day — 시뮬레이션 결과 (실측 아님)

과제 중 대학생의 하루 — 오전 자세 개입, 점심 IDLE, 오후 졸음 깨우기, 닫힌 방 환기, 늦은 밤 졸음 반복

- 페르소나 student · seed 11 · FSM production · 반응 대본 stochastic · 날씨 {'temp_c': 17.0, 'humidity': 50, 'wind_ms': 1.0, 'condition': 'clear'}
- ToF numpy 백엔드 · 자세 판정 oracle · 3792 tick(632.0 분) · 프레임 53820 · 벽시계 755.7 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_MIXED → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_BREAK → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → FOCUS_MIXED → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → FOCUS_MIXED → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_BREAK → REST → RECOVERY → FOCUS_NPC → FOCUS_MIXED → FOCUS_NPC
- 라우팅(route:cause 횟수): {'posture': 3, 'environment': 2, 'cognitive': 2}
- 자세 tick 정확도 0.995 · drowsy tick 재현율 1.0 (정답 drowsy tick 213, 오탐 tick 10) · 끄덕임 검출 {'0': 32, '1': 32}
- 첫 졸음(정답) 14530.0 s → 졸음 플래그 14520.0 s → 첫 ACTION 5610.0 s → 깨어남 31520 s → FOCUS 복귀 28550.0 s · REST 5780.0 s
- 사람: {'interventions': 7, 'auto': 3, 'suggest': 4, 'accepted': 4, 'rejected': 0, 'timeout': 0, 'undone': 0, 'woke': 3, 'while_drowsy': 4, 'posture_fixed': 2, 'arms': {'air_fan_up': 1, 'break_long': 1, 'break_short': 1, 'posture_card': 1, 'posture_voice': 2, 'ventilate_suggest': 1}, 'effects': ['break:12min', 'window_open:15min', 'break:4min'], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 1, 'undo': 0, 'alert': 3, 'card': 4}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5610 | 15:33 | posture_voice | auto | posture | None | auto_kept |  |  |  |  | 자세 음성 안내 수락 33/40 · 효과 +0.90 · 개인 정책 · 피드백 167건 |
| 5660 | 15:34 | air_fan_up | suggest | environment | None | accept |  |  |  |  | 공기청정기 풍량 올리기 수락 7/10 · 효과 +0.60 · 개인 정책 · 피드백 167건 |
| 5750 | 15:35 | break_long | suggest | cognitive | None | accept |  |  | Y | break:12min | chin_rest 6분 · 긴 휴식 수락 20/24 · 효과 +0.80 · 개인 정책 · 피드백 168건 |
| 31520 | 22:45 | posture_voice | auto | posture | None | auto_kept | Y | Y |  |  | 졸음 1회 · 세션 8.8 h · 자세 음성 안내 수락 33/40 · 효과 +0.90 · 개인 정책 · 피드백 170건 |
| 34520 | 23:35 | posture_card | auto | posture | None | auto_kept | Y | Y |  |  | 졸음 1회 · 세션 9.6 h · 평소 취침 시각 지남 · 자세 안내 카드 수락 0/2 · 효과 +0.15 · 개인 정책 · 피드백 171건 |
| 35190 | 23:46 | ventilate_suggest | suggest | environment | None | accept | Y |  |  | window_open:15min | 졸음 2회 · 세션 9.8 h · 평소 취침 시각 지남 · 환기 15분 · 창문 환기 수락 2/5 · 효과 +0.33 · 개인 정책 · 피드백  |
| 35230 | 23:47 | break_short | suggest | cognitive | None | accept | Y | Y | Y | break:4min | 정책 미적용(기록 전용) · FSM 기본 동작 take_a_break |
