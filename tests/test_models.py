from copy import deepcopy

from fluora_protocol.pa3.models import Pa3State

from tests.test_fake_server import SNAPSHOT


def test_snapshot_projection() -> None:
    snapshot = deepcopy(SNAPSHOT)
    snapshot["payload"]["animations"] = [
        {"label": "Twinkle", "category": "*", "is_audio": False, "occasion": 0},
        {"label": "Leaf Swirl", "category": "fluora", "is_audio": False, "occasion": 0},
        {"label": "Mirage", "category": "*", "is_audio": False, "occasion": 0},
    ]
    snapshot["payload"]["engine"]["mode"]["v"] = 1
    snapshot["payload"]["engine"]["active_scene_index"]["v"] = 1
    snapshot["payload"]["engine"]["scenes"] = [
        {"label": "Party"},
        {"label": "Chill"},
    ]

    state = Pa3State.from_snapshot(snapshot)
    assert state.serial == "abc123"
    assert state.power.identifier == "power-id"
    assert state.brightness.identifier == "brightness-id"
    assert state.mode.identifier == "mode-id"
    assert state.current_effect == "Scene: Chill"
    assert state.manual_animation_index
    assert state.manual_animation_index.identifier == "animation-id"
    assert next(effect.index for effect in state.effects if effect.label == "Mirage") == 2
    assert state.scenes == ("Party", "Chill")
