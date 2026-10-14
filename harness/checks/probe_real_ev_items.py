"""Exercise atomic EV training through the real Qt bag and SQLite (#959)."""

import copy
import os
from pathlib import Path
import tempfile


def main():
    try:
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("NO_QT: real EV-item proof requires PyQt6")
        return 77

    from harness.bootstrap import quiet
    from harness.real_driver import RealDriver

    with tempfile.TemporaryDirectory(prefix="ankimon-ev-items-") as directory:
        os.environ["ANKIMON_SPRITE_CACHE"] = str(Path(directory) / "no-cache")
        with quiet():
            driver = RealDriver(
                user_path=directory,
                first_encounter=False,
                settings_overrides={
                    "battle.cards_per_round": 1,
                    "audio.sounds": False,
                    "audio.sound_effects": False,
                    "gui.pop_up_dialog_message_on_item": False,
                    "gui.pop_up_dialog_message_on_defeat": False,
                },
            )
        from Ankimon import battle_loop
        from Ankimon.singletons import get_item_window
        from harness.fixtures import build_pokemon

        services = driver.services
        db = services.db
        main_pokemon = services.main_pokemon
        main_pokemon.update_stats(
            **build_pokemon(
                {"species": "Pikachu", "level": 100, "moves": ["Splash"]}
            ).to_dict()
        )
        services.enemy_pokemon.update_stats(
            **build_pokemon(
                {"species": "Chansey", "level": 100, "moves": ["Splash"]}
            ).to_dict()
        )
        db.save_main_pokemon(main_pokemon.to_dict())
        bag = get_item_window()
        battle_loop._state.new_state = None
        battle_loop._state.mutator_full_reset = 1
        driver.answer(3)
        active = battle_loop._state.new_state.user.active
        active.attack_boost = 2
        active.speed_boost = -1
        active.status = "par"
        active.volatile_status.add("substitute")
        battle_loop._state.new_state.user.side_conditions["reflect"] = 3
        before_hp = main_pokemon.hp
        main_pokemon.battle_status = "par"
        main_pokemon.volatile_status.add("substitute")
        db.save_item(1053, "mighty-candy-xl", 1)
        db.save_item(1052, "health-candy-xl", 1)
        db.save_item(23, "max-potion", 1)
        with quiet():
            assert bag.dispatch_use("mighty-candy-xl")["ok"]
            assert bag.dispatch_use("health-candy-xl")["ok"]
        assert main_pokemon.stats["atk"] == active.attack == 209
        assert main_pokemon.max_hp == active.maxhp == 274
        assert main_pokemon.hp == main_pokemon.current_hp == active.hp == before_hp
        assert active.attack_boost == 2 and active.speed_boost == -1
        assert active.status == "par" and "substitute" in active.volatile_status
        assert battle_loop._state.new_state.user.side_conditions["reflect"] == 3
        assert db.get_main_pokemon()["ev"] == main_pokemon.ev
        driver.answer(3)
        assert battle_loop._state.new_state.user.active.attack == 209
        assert battle_loop._state.new_state.user.active.maxhp == 274
        with quiet():
            assert bag.dispatch_use("max-potion")["ok"]
        assert main_pokemon.hp == main_pokemon.current_hp == main_pokemon.max_hp == 274

        # A real SQL failure must undo the charge, preserve main ownership,
        # and leave no write that a later unrelated commit can publish.
        db.save_item(50, "carbos", 1)
        before_saved = copy.deepcopy(db.get_main_pokemon())
        before_live = copy.deepcopy(main_pokemon.to_dict())
        before_engine = copy.deepcopy(battle_loop._state.new_state)
        db.execute(
            "CREATE TEMP TRIGGER fail_ev_save BEFORE UPDATE OF data "
            "ON captured_pokemon BEGIN SELECT RAISE(ABORT, 'EV save failed'); END"
        ).close()
        with quiet():
            assert not bag.dispatch_use("carbos")["ok"]
        db.execute("DROP TRIGGER fail_ev_save").close()
        db.set_user_data("ev_proof_unrelated_write", True)
        assert db.get_item("carbos")["quantity"] == 1
        assert db.get_main_pokemon() == before_saved
        assert main_pokemon.to_dict() == before_live
        after_engine = battle_loop._state.new_state
        assert after_engine.user.active.evs == before_engine.user.active.evs
        assert after_engine.user.active.attack == before_engine.user.active.attack
        assert after_engine.user.active.maxhp == before_engine.user.active.maxhp
        assert not db._get_connection().in_transaction

        # Recalculation must not revive a fainted companion.
        main_pokemon.hp = main_pokemon.current_hp = 0
        main_pokemon.battle_status = "fainted"
        battle_loop._state.new_state.user.active.hp = 0
        db.save_main_pokemon(main_pokemon.to_dict())
        with quiet():
            assert bag.dispatch_use("carbos")["ok"]
        assert main_pokemon.hp == main_pokemon.current_hp == 0
        assert main_pokemon.battle_status == "fainted"
        assert db.get_main_pokemon()["hp"] == 0

        screenshots = os.environ.get("ANKIMON_PROOF_SCREENSHOTS")
        if screenshots:
            destination = Path(screenshots)
            destination.mkdir(parents=True, exist_ok=True)
            db.save_item(46, "protein", 2)
            bag.renewWidgets()
            bag.show()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QTest.qWait(100)
            QApplication.processEvents()
            assert bag.grab().save(str(destination / "ev-items.png"))
        bag.close()
        db.close()
    print("probe_real_ev_items: OK (atomic save, HP, live battle stats, fainted HP)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
