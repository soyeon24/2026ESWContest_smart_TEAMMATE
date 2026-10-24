"""life_sim 무드등 mock — adjust_brightness 계약(노트북 10-25, 사용자 "밝기 조정은 기존 대비 % 올리기").

기준 = 마지막으로 쓴 원시 밝기(꺼짐·모름 = 하한 30), 새 값 = clamp(round(기준 × (1 + n/100)), 30, 255),
올리는데 같은 값이면 최소 한 단계. 결과에 previous·actual, 되돌리기는 set_brightness <previous>.
"""
import pytest

from tools.life_sim.devices import DeviceWorld
from tools.life_sim.scenario import load_defaults


@pytest.fixture
def world():
    _, devices, _ = load_defaults()
    return DeviceWorld(devices, {"co2_ppm": 600}, {"temp_c": 18.0}, 0.0)


def cmd(op, value):
    return {"target_id": "desk_lamp", "operation": op, "value": value, "command_id": "c1", "gate": "auto"}


def test_adjust_from_off_uses_floor(world):
    r = world.apply_command(cmd("adjust_brightness", {"percent": 60}), 1.0)
    assert (r["previous"], r["actual"]) == (0, 48)          # 꺼짐 → 기준 30 × 1.6
    assert world.state.lamp_on and world.state.lamp_raw == 48


def test_adjust_is_relative_to_last_raw(world):
    world.apply_command(cmd("set_brightness", 110), 1.0)
    r = world.apply_command(cmd("adjust_brightness", {"percent": 60}), 2.0)
    assert (r["previous"], r["actual"]) == (110, 176)
    assert r["channels"] == ["lamp_bright"]                  # 176/255 = 69 % ≥ bright_pct 60
    r = world.apply_command(cmd("adjust_brightness", {"percent": -50}), 3.0)
    assert (r["previous"], r["actual"]) == (176, 88)
    assert r["channels"] == ["lamp_dim"]


@pytest.mark.parametrize("start,percent,want", [(200, 60, 255), (40, -50, 30), (30, 1, 31), (255, 10, 255)])
def test_adjust_clamps_and_steps(world, start, percent, want):
    world.apply_command(cmd("set_brightness", start), 1.0)
    assert world.apply_command(cmd("adjust_brightness", {"percent": percent}), 2.0)["actual"] == want


def test_adjust_accepts_json_string_and_undo_restores(world):
    world.apply_command(cmd("set_brightness", 100), 1.0)
    r = world.apply_command(cmd("adjust_brightness", '{"percent": 30}'), 2.0)
    assert r["actual"] == 130
    world.apply_command(cmd("set_brightness", r["previous"]), 3.0)     # hub 되돌리기
    assert world.state.lamp_raw == 100 and world.state.lamp_brightness == 39


def test_channel_lamps_set_the_raw_base(world):
    world.apply_channel("lamp_cool", 1.0)
    assert world.state.lamp_raw == 230
    assert world.apply_command(cmd("adjust_brightness", {"percent": 10}), 2.0)["actual"] == 253
    world.apply_channel("lamp_off", 3.0)
    assert world.apply_command(cmd("adjust_brightness", {"percent": 60}), 4.0)["previous"] == 0
