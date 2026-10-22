"""생활 각본 폐루프 시뮬 — 가상 ToF 두 센서 → 자세·졸음 판정 → hub FSM → 개인화 개입 → 주변기기(mock) → 사람 반응.

    cd hub
    python -m tools.life_sim.runner --scenario tools/life_sim/config/scenarios/a1_wake_first.yaml --backend numpy

전부 **시뮬레이션**이다. 실측 증거가 아니다(10-19 실측에서는 모든 자세 모델이 drowsy 재현율 0 이었다).
임계값·확률·기기 효과 계수는 `config/*.yaml` 에만 둔다. `inference/engine.py` 는 건드리지 않는다.
"""
