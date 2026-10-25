"""Real-engine coverage for item-only HP recovery and committed potion updates."""

from pathlib import Path
import subprocess
import sys
import textwrap


_ROOT = Path(__file__).resolve().parents[1]
_BOOT = """
import random
from harness.driver import Driver
from harness.fixtures import build_pokemon
driver = Driver(
    first_encounter=False,
    settings_overrides={"battle.review_based_damage": False},
)
from Ankimon.functions import ankimon_hooks_to_poke_engine as bridge
from Ankimon.poke_engine import constants

def battle(user, opponent, user_move, opponent_move):
    random.seed(0)
    return bridge.simulate_battle_with_poke_engine(
        user, opponent, user_move, opponent_move, 1, None
    )
"""


def _run(code):
    result = subprocess.run(
        [sys.executable, "-c", _BOOT + textwrap.dedent(code)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_recovery_is_suppressed_before_later_hp_based_damage():
    _run("""
        user = build_pokemon({"species": "Mewtwo", "level": 50,
                              "moves": ["Recover"], "hp": 10})
        opponent = build_pokemon({"species": "Raticate", "level": 50,
                                  "moves": ["Super Fang"]})
        result = battle(user, opponent, "recover", "superfang")
        assert user.hp == user.current_hp == result[1].user.active.hp == 5
        assert not any(i[0] == constants.MUTATOR_HEAL and
                       i[1] == constants.USER and i[2] > 0
                       for i in result[0]["instructions"])
    """)


def test_enemy_pain_split_cannot_heal_the_player_through_negative_damage():
    _run("""
        user = build_pokemon({"species": "Mewtwo", "level": 50,
                              "moves": ["Safeguard"], "hp": 10})
        opponent = build_pokemon({"species": "Misdreavus", "level": 50,
                                  "moves": ["Pain Split"], "hp": 100})
        result = battle(user, opponent, "safeguard", "painsplit")
        assert user.hp == user.current_hp == result[1].user.active.hp == 10
        assert opponent.hp == 55
        assert not any(i[0] == constants.MUTATOR_DAMAGE and
                       i[1] == constants.USER and i[2] < 0
                       for i in result[0]["instructions"])

        # Pain Split's HP cost and recovery for the opponent still apply.
        user = build_pokemon({"species": "Misdreavus", "level": 50,
                              "moves": ["Pain Split"], "hp": 100})
        opponent = build_pokemon({"species": "Mewtwo", "level": 50,
                                  "moves": ["Safeguard"], "hp": 10})
        result = battle(user, opponent, "painsplit", "safeguard")
        assert user.hp == opponent.hp == 55
    """)


def test_opponent_healing_and_reversing_damage_are_unchanged():
    _run("""
        user = build_pokemon({"species": "Raticate", "level": 50,
                              "moves": ["Super Fang"]})
        opponent = build_pokemon({"species": "Mewtwo", "level": 50,
                                  "moves": ["Recover"], "hp": 10})
        result = battle(user, opponent, "superfang", "recover")
        assert opponent.hp > 10
        assert any(i[0] == constants.MUTATOR_HEAL and
                   i[1] == constants.OPPONENT and i[2] > 0
                   for i in result[0]["instructions"])

        state = result[1]
        before = state.user.active.hp
        mutator = bridge._ItemOnlyHealingMutator(state)
        instructions = [
            (constants.MUTATOR_DAMAGE, constants.USER, 3),
            (constants.MUTATOR_DAMAGE, constants.USER, -4),
            (constants.MUTATOR_HEAL, constants.USER, 20),
            (constants.MUTATOR_HEAL, constants.USER, -2),
        ]
        mutator.apply(instructions)
        assert state.user.active.hp == before - 5
        mutator.reverse(instructions)
        assert state.user.active.hp == before
        mutator.apply_one((constants.MUTATOR_HEAL, constants.USER, 20))
        assert state.user.active.hp == before
    """)


def test_end_of_turn_damage_uses_hp_without_leftovers_recovery():
    _run("""
        user = build_pokemon({"species": "Mewtwo", "level": 50,
                              "moves": ["Safeguard"], "hp": 1,
                              "held_item": "leftovers"})
        user.battle_status = constants.POISON
        opponent = build_pokemon({"species": "Raticate", "level": 50,
                                  "moves": ["Tail Whip"]})
        result = battle(user, opponent, "safeguard", "tailwhip")
        assert user.hp == user.current_hp == result[1].user.active.hp == 0
        assert [i[2] for i in result[0]["instructions"]
                if i[0] == constants.MUTATOR_DAMAGE and i[1] == constants.USER] == [1]
    """)


def test_potion_hp_sync_preserves_battle_state_and_checks_individual():
    _run("""
        user = build_pokemon({"species": "Mewtwo", "level": 50,
                              "moves": ["Recover"], "hp": 10})
        opponent = build_pokemon({"species": "Raticate", "level": 50,
                                  "moves": ["Super Fang"]})
        state = battle(user, opponent, "recover", "superfang")[1]
        active = state.user.active
        active.attack_boost = 3
        active.volatile_status.add("substitute")
        state.weather = "rain"
        state.trick_room = True
        old_hp = active.hp
        user.current_hp = user.hp = 25
        individual_id = user.individual_id
        user.individual_id = "another-individual"
        assert not bridge.sync_active_pokemon_hp(state, user)
        assert active.hp == old_hp
        user.individual_id = individual_id
        assert bridge.sync_active_pokemon_hp(state, user)
        assert active.hp == 25 and active.maxhp == user.max_hp
        assert state.user.active is active
        assert active.attack_boost == 3 and "substitute" in active.volatile_status
        assert state.weather == "rain" and state.trick_room is True
    """)
