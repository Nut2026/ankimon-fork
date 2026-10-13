"""Regression tests for ``pyobj/item_window.py`` EV-item consumption.

Vitamins/wings/mochi/candies used to fall through to "give item to a Pokemon"
(``_prompt_and_give_held_item``) like any unimplemented item, since nothing
in ``dispatch_use``/the Qt bag's button builder recognised them. These pin
the consume-before-train ordering (mirroring ``Check_Heal_Item``), the caps
(vitamins stop at 100 EV, everything stops at 252/stat and 510 total), and
that the item is still spent on a maxed-out stat (matching the mainline
games, which waste the item rather than refusing the click).

``item_window.py`` imports Qt and most of the addon at module scope, so it is
loaded in isolation with those stubbed (mirroring
``test_heal_item_consumption.py``), except ``Ankimon.functions.ev_items``
(the module under test) and ``Ankimon.services``.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"


class _MockQWidget:
    """Real class so ``class ItemWindow(QWidget)`` is a valid definition."""

    def __init__(self, *args, **kwargs):
        pass


class _FakeItemDB:
    """The ``services.db`` seam: an inventory plus a write log."""

    def __init__(self, inventory=None):
        self.inventory = dict(inventory or {})
        self.quantity_calls = []

    def get_item(self, item_name):
        if item_name not in self.inventory:
            return None
        return {"item_name": item_name, "quantity": self.inventory[item_name]}

    def consume_item(self, item_name, count=1):
        self.quantity_calls.append((item_name, -count))
        current = self.inventory.get(item_name, 0)
        if current < count:
            return False
        if current == count:
            self.inventory.pop(item_name, None)
        else:
            self.inventory[item_name] = current - count
        return True

    def refund_item(self, item, count=1):
        self.quantity_calls.append((item["item_name"], count))
        self.inventory[item["item_name"]] = self.inventory.get(item["item_name"], 0) + count


class _FakePokemon:
    def __init__(self, name="mewtwo", ev=None):
        self.name = name
        self.ev = ev or {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
        self.invalidate_cp_cache_calls = 0

    def invalidate_cp_cache(self):
        self.invalidate_cp_cache_calls += 1


def _force_load(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def item_window_mod():
    """Load the real ``item_window`` with a stubbed Qt/addon runtime."""
    parent_pkgs = ("Ankimon", "Ankimon.functions", "Ankimon.pyobj")
    stub_names = [
        "aqt", "aqt.utils", "aqt.qt",
        "PyQt6", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtCore",
        "Ankimon.pyobj.evolution_window",
        "Ankimon.pyobj.InfoLogger",
        "Ankimon.pyobj.pc_box",
        "Ankimon.pyobj.pokemon_obj",
        "Ankimon.pyobj.settings",
        "Ankimon.pyobj.starter_window",
        "Ankimon.pyobj.error_handler",
        "Ankimon.business",
        "Ankimon.functions.pokedex_functions",
        "Ankimon.functions.badges_functions",
        "Ankimon.functions.pokemon_functions",
        "Ankimon.functions.update_main_pokemon",
        "Ankimon.resources",
        "Ankimon.utils",
        "Ankimon.pyobj.item_window",
    ]
    saved = {
        name: sys.modules.get(name)
        for name in (
            *stub_names,
            *parent_pkgs,
            "Ankimon.services",
            # Not stubbed -- it is the module under test.
            "Ankimon.functions.ev_items",
        )
    }

    try:
        for pkg in parent_pkgs:
            mod = types.ModuleType(pkg)
            mod.__path__ = [str(_SRC / pkg.replace(".", "/"))]
            mod.__package__ = pkg
            sys.modules[pkg] = mod
        for name in stub_names:
            sys.modules[name] = MagicMock()
        sys.modules["PyQt6.QtWidgets"].QWidget = _MockQWidget
        services_mod = _force_load("Ankimon.services", _SRC / "Ankimon" / "services.py")
        ev_items_mod = _force_load(
            "Ankimon.functions.ev_items", _SRC / "Ankimon" / "functions" / "ev_items.py"
        )
        mod = _force_load(
            "Ankimon.pyobj.item_window", _SRC / "Ankimon" / "pyobj" / "item_window.py"
        )
        mod._services_mod = services_mod
        mod._ev_items_mod = ev_items_mod
        yield mod
    finally:
        for name, val in saved.items():
            if val is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = val


def _make_window(mod, db, main_pokemon=None):
    """A bare ItemWindow: no Qt construction, just the collaborators used here."""
    win = mod.ItemWindow.__new__(mod.ItemWindow)
    win.logger = MagicMock()
    win.settings_obj = MagicMock()
    win.main_pokemon = main_pokemon
    win.achievements = {}
    win.renewWidgets = MagicMock()
    win.hp_heal_items = {}
    win.fossil_pokemon = {}
    win.escape_items = {}
    win.pokeball_chances = {}
    win.evolution_items = {}
    win.ev_items = (
        set(mod.VITAMINS) | set(mod.WINGS) | set(mod.MOCHI) | set(mod.CANDIES)
    )
    win._item_action_in_progress = False
    mod.services.db = db
    mod.save_main_pokemon = MagicMock()
    mod.play_effect_sound = MagicMock()
    return win


def test_vitamin_consumes_exactly_one_item(item_window_mod):
    """The happy path trains the stat and spends one vitamin doing it."""
    db = _FakeItemDB({"protein": 2})
    pokemon = _FakePokemon()
    win = _make_window(item_window_mod, db, pokemon)

    assert win._use_ev_item("protein") == (True, 10)
    assert pokemon.ev["atk"] == 10
    assert db.quantity_calls == [("protein", -1)]
    assert db.inventory["protein"] == 1
    assert pokemon.invalidate_cp_cache_calls == 1
    assert item_window_mod.save_main_pokemon.called


def test_ev_item_is_refused_when_the_bag_is_empty(item_window_mod):
    db = _FakeItemDB({})
    pokemon = _FakePokemon()
    win = _make_window(item_window_mod, db, pokemon)

    assert win._use_ev_item("protein") == (False, 0)
    assert pokemon.ev["atk"] == 0
    assert db.quantity_calls == []


def test_no_main_pokemon_does_not_burn_an_item(item_window_mod):
    db = _FakeItemDB({"protein": 1})
    win = _make_window(item_window_mod, db, main_pokemon=None)

    assert win._use_ev_item("protein") == (False, 0)
    assert db.quantity_calls == []
    assert db.inventory["protein"] == 1


def test_vitamin_has_no_soft_cap_and_keeps_training_past_100(item_window_mod):
    """Unlike the mainline games, a vitamin here keeps working past 100 EV."""
    db = _FakeItemDB({"protein": 1})
    pokemon = _FakePokemon(ev={"hp": 0, "atk": 100, "def": 0, "spa": 0, "spd": 0, "spe": 0})
    win = _make_window(item_window_mod, db, pokemon)

    assert win._use_ev_item("protein") == (True, 10)
    assert pokemon.ev["atk"] == 110, "vitamins must not stop at the mainline 100-EV soft cap"


def test_vitamin_still_stops_at_the_252_hard_cap(item_window_mod):
    db = _FakeItemDB({"protein": 1})
    pokemon = _FakePokemon(ev={"hp": 0, "atk": 251, "def": 0, "spa": 0, "spd": 0, "spe": 0})
    win = _make_window(item_window_mod, db, pokemon)

    spent, granted = win._use_ev_item("protein")
    assert spent is True
    assert pokemon.ev["atk"] == 252, "the item is still spent on a maxed stat"
    assert db.inventory.get("protein", 0) == 0


def test_wing_has_no_soft_cap_but_still_hits_252(item_window_mod):
    db = _FakeItemDB({"muscle-wing": 1})
    pokemon = _FakePokemon(ev={"hp": 0, "atk": 251, "def": 0, "spa": 0, "spd": 0, "spe": 0})
    win = _make_window(item_window_mod, db, pokemon)

    assert win._use_ev_item("muscle-wing") == (True, 1)
    assert pokemon.ev["atk"] == 252


def test_candy_xl_fills_a_stat_to_the_cap_in_one_use(item_window_mod):
    db = _FakeItemDB({"health-candy-xl": 1})
    pokemon = _FakePokemon()
    win = _make_window(item_window_mod, db, pokemon)

    spent, granted = win._use_ev_item("health-candy-xl")
    assert spent is True
    assert pokemon.ev["hp"] == 252


def test_ev_item_respects_the_510_total_cap_across_stats(item_window_mod):
    db = _FakeItemDB({"tough-candy-l": 1})
    pokemon = _FakePokemon(ev={"hp": 252, "atk": 252, "def": 0, "spa": 0, "spd": 0, "spe": 0})
    win = _make_window(item_window_mod, db, pokemon)

    assert win._use_ev_item("tough-candy-l") == (True, 6)
    assert pokemon.ev["def"] == 6, "only 6 EV of room remained under the 510 total"


def test_mochi_is_the_same_effect_as_the_matching_wing(item_window_mod):
    db = _FakeItemDB({"swift-mochi": 1, "swift-wing": 1})
    a = _FakePokemon()
    b = _FakePokemon()
    win_a = _make_window(item_window_mod, db, a)
    win_a._use_ev_item("swift-mochi")
    win_b = _make_window(item_window_mod, _FakeItemDB({"swift-wing": 1}), b)
    win_b._use_ev_item("swift-wing")

    assert a.ev["spe"] == b.ev["spe"] == 1


def test_dispatch_use_reports_a_refused_ev_item(item_window_mod):
    db = _FakeItemDB({})
    win = _make_window(item_window_mod, db, _FakePokemon())

    result = win.dispatch_use("protein")

    assert result["ok"] is False
    assert "protein" in result["message"].lower()


def test_dispatch_use_reports_a_real_ev_grant(item_window_mod):
    db = _FakeItemDB({"protein": 1})
    win = _make_window(item_window_mod, db, _FakePokemon())

    result = win.dispatch_use("protein")

    assert result["ok"] is True
    assert "trained" in result["message"].lower()
    assert db.quantity_calls == [("protein", -1)]


def test_dispatch_use_does_not_claim_a_training_that_did_not_happen(item_window_mod):
    """The toast must not say "Trained" when the item had zero effect."""
    db = _FakeItemDB({"protein": 1})
    pokemon = _FakePokemon(ev={"hp": 0, "atk": 252, "def": 0, "spa": 0, "spd": 0, "spe": 0})
    win = _make_window(item_window_mod, db, pokemon)

    result = win.dispatch_use("protein")

    assert result["ok"] is True
    assert "trained" not in result["message"].lower()
    assert "no effect" in result["message"].lower()


def test_a_failed_save_rolls_back_the_ev_and_refunds_the_item(item_window_mod):
    """A save failure must not leave a phantom EV gain or a lost item.

    The in-memory EV change would otherwise silently vanish on the next
    reload (since it never reached the database), while the item stayed
    spent -- so it has to roll back the object AND return the item.
    """
    db = _FakeItemDB({"protein": 1})
    pokemon = _FakePokemon()
    win = _make_window(item_window_mod, db, pokemon)
    item_window_mod.save_main_pokemon.side_effect = RuntimeError("disk on fire")

    assert win._use_ev_item("protein") == (False, 0)
    assert pokemon.ev["atk"] == 0, "the EV gain must be rolled back"
    assert db.inventory.get("protein", 0) == 1, "the item must be refunded"
    assert db.quantity_calls == [("protein", -1), ("protein", 1)]


def test_rare_candy_is_untouched_by_the_ev_item_branch(item_window_mod):
    """A non-EV item in the same CSV category must not be caught by this branch."""
    win = _make_window(item_window_mod, _FakeItemDB({}), _FakePokemon())

    assert "rare-candy" not in win.ev_items
