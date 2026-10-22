# b_examinee_day — 시뮬레이션 결과 (실측 아님)

필기 수험생의 하루 — 비PC 필기, 닫힌 작은 방 CO₂ 상승 → 환기/공기 개입, 오후 졸음, 밤 졸음, 23시 이후 취침 권유 후보

- 페르소나 examinee · seed 31 · FSM production · 반응 대본 stochastic · 날씨 {'temp_c': 17.0, 'humidity': 50, 'wind_ms': 1.0, 'condition': 'clear'}
- ToF numpy 백엔드 · 자세 판정 oracle · 3870 tick(645.0 분) · 프레임 55170 · 벽시계 785.3 s
- 상태 경로: START → CONTEXT_DETECT → FOCUS_NPC → FATIGUE_SUSPECT → FATIGUE → CAUSE_ANALYSIS → ACTION_POSTURE → MONITOR → RECOVERY → ESCALATE → CAUSE_ANALYSIS → ACTION_ENV → MONITOR → ESCALATE → CAUSE_ANALYSIS → ACTION_BREAK → MONITOR → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY → ESCALATE → REST → RECOVERY
- 라우팅(route:cause 횟수): {'posture': 1, 'environment': 1, 'cognitive': 1}
- 자세 tick 정확도 0.996 · drowsy tick 재현율 1.0 (정답 drowsy tick 418, 오탐 tick 7) · 끄덕임 검출 {'0': 275, '1': 275}
- 첫 졸음(정답) 16510.0 s → 졸음 플래그 16500.0 s → 첫 ACTION 7410.0 s → 깨어남 None s → FOCUS 복귀 None s · REST 16640.0 s
- 사람: {'interventions': 3, 'auto': 1, 'suggest': 2, 'accepted': 1, 'rejected': 1, 'timeout': 0, 'undone': 0, 'woke': 0, 'while_drowsy': 2, 'posture_fixed': 1, 'arms': {'air_fan_up': 1, 'light_warm_dim': 1, 'posture_card': 1}, 'effects': [], 'session_ended_by_sleep': False}
- 기기 명령: {'cmd': 1, 'undo': 0, 'alert': 1, 'card': 2}

| t | 시각 | arm | 전달 | 원인 | 대본 | 응답 | 졸음 중 | 깸 | 자세 복귀 | 효과 | 설명 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 7410 | 15:33 | posture_card | auto | posture | None | auto_kept |  |  | Y |  | CO₂ 1708 ppm · 세션 2.1 h · 자세 안내 카드 수락 4/9 · 효과 +0.78 · 개인 정책 · 피드백 147건 |
| 16520 | 18:05 | air_fan_up | suggest | environment | None | accept | Y |  |  |  | CO₂ 1266 ppm · 졸음 1회 · 세션 4.6 h · 공기청정기 풍량 올리기 수락 8/10 · 효과 +0.87 · 개인 정책 · 피드백  |
| 16600 | 18:06 | light_warm_dim | suggest | cognitive | None | reject | Y |  |  |  | CO₂ 1282 ppm · 졸음 1회 · 세션 4.6 h · 조명 따뜻하고 어둡게 수락 0/2 · 효과 +0.29 · 개인 정책 · 피드백 14 |
