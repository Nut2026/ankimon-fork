"""Regression coverage for encounter, evolution, and startup fixes."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harness.driver import Driver


def run_probe():
    driver = Driver(first_encounter=False)

    # Encounter tier labels are strings; enabling the rare encounter popup must
    # not turn an ordinary encounter into a TypeError.
    driver.set_setting("gui.pop_up_dialog_message_on_encounter", True)
    driver.encounter()
    assert not [event for event in driver.drain_events() if event["type"] == "error"]

    from Ankimon.functions.friendship_evolution import evolution_readiness
    from Ankimon.functions.pokedex_functions import check_evolution_by_item

    for species, level, gender, expected in (
        (281, 30, "M", 282),
        (361, 42, "F", 362),
    ):
        result = evolution_readiness(
            {"id": species, "level": level, "gender": gender}
        )
        assert (result["method"], result["evo_id"], result["ready"]) == (
            "level", expected, True
        )
        assert result["item_status_text"]

    for region, expected in (("Kanto", 26), ("No Region", 26), ("Alola", 10100)):
        driver.set_setting("misc.active_region", region)
        assert check_evolution_by_item(25, 83, gender="M") == expected
    driver.set_setting("misc.active_region", "Kanto")
    assert check_evolution_by_item(123, 10001) == 900

    # The first tracker window must read the setting saved in the prior run.
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    with tempfile.TemporaryDirectory(prefix="ankimon_round_setting_") as profile:
        init = (
            "from harness.driver import Driver; import sys; "
            "d=Driver(user_path=sys.argv[1],first_encounter=False); "
            "d.set_setting('battle.cards_per_round',5)"
        )
        check = (
            "from harness.driver import Driver; import sys; "
            "d=Driver(user_path=sys.argv[1],first_encounter=False); "
            "assert d.services.tracker.cards_until_calc_multiplier == 5"
        )
        subprocess.run([sys.executable, "-c", init, profile], check=True, env=env)
        subprocess.run([sys.executable, "-c", check, profile], check=True, env=env)

    print("probe_recent_merges: OK")


if __name__ == "__main__":
    run_probe()
