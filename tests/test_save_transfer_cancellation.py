"""Cancel's menu worker preserves save ownership without blocking the GUI."""

import importlib
import sys
from concurrent.futures import Future
from threading import Event, Thread, get_ident
from types import ModuleType, SimpleNamespace

import pytest

from test_save_transfer import _make_save, st
from test_save_transfer_safety import transfer  # noqa: F401
from Ankimon import save_import


@pytest.fixture
def cancellation(transfer, tmp_path, monkeypatch):
    queued = []

    class QueuedQueryOp:
        def __init__(self, *, parent, op, success):
            self.op = op
            self.success = success
            self.future = Future()
            self.worker_thread = None
            queued.append(self)

        def failure(self, callback):
            self.failed = callback
            return self

        def without_collection(self):
            return self

        def run_in_background(self):
            return self

        def work(self):
            self.worker_thread = get_ident()
            try:
                self.future.set_result(self.op(None))
            except Exception as error:
                self.future.set_exception(error)

        def deliver(self):
            error = self.future.exception()
            if error is None:
                self.success(self.future.result())
            else:
                self.failed(error)

    epoch = [0]

    def validate():
        if epoch[0] != 0:
            raise RuntimeError("The confirmed Anki profile changed")

    context = SimpleNamespace(manager=SimpleNamespace(), validate=validate)
    operations = ModuleType("aqt.operations")
    operations.QueryOp = QueuedQueryOp
    monkeypatch.setitem(sys.modules, "aqt.operations", operations)
    monkeypatch.setattr(st, "user_path", tmp_path)
    notices, emitted = [], []
    events = importlib.import_module("Ankimon.events").events
    monkeypatch.setattr(
        events,
        "emit",
        lambda name, **fields: emitted.append((get_ident(), name, fields)),
    )
    save_import.stage_import(transfer.incoming, transfer.active)
    return SimpleNamespace(
        transfer=transfer,
        context=context,
        epoch=epoch,
        queued=queued,
        notices=notices,
        emitted=emitted,
        notify=lambda *args: notices.append((get_ident(), args)),
    )


def _run_worker(operation):
    worker = Thread(target=operation.work)
    worker.start()
    worker.join(5)
    assert not worker.is_alive()


def test_cancel_waits_off_thread_and_reports_on_gui_thread(cancellation):
    c = cancellation
    entered, release = Event(), Event()

    def competing_stage():
        with save_import._STAGING_LOCK:
            entered.set()
            assert release.wait(5)

    owner = Thread(target=competing_stage)
    owner.start()
    assert entered.wait(5)
    st.cancel_pending_save_import_async(c.context, c.notify)
    operation = c.queued[0]
    worker = Thread(target=operation.work)
    worker.start()
    try:
        assert not operation.future.done()
        assert not c.notices and not c.emitted
        _, directory = save_import._paths(c.transfer.active)
        assert (directory / "pending.json").is_file()
    finally:
        release.set()
        owner.join(5)
        worker.join(5)
    assert not owner.is_alive() and not worker.is_alive()
    assert operation.worker_thread != get_ident()
    assert save_import.pending_import_info(c.transfer.active) is None
    assert not c.notices and not c.emitted
    operation.deliver()
    assert c.notices[0][0] == c.emitted[0][0] == get_ident()
    assert "cancelled" in c.notices[0][1][0]


def test_cancellation_uses_captured_targets_and_deduplicates_clicks(
    cancellation, tmp_path, monkeypatch
):
    c = cancellation
    st.cancel_pending_save_import_async(c.context, c.notify)
    st.cancel_pending_save_import_async(c.context, c.notify)
    assert len(c.queued) == 1
    other = _make_save(tmp_path / "another-profile.db", pokemon=5)
    save_import.stage_import(c.transfer.incoming, other)
    monkeypatch.setattr(st, "_active_db_path", lambda: other)
    _run_worker(c.queued[0])
    c.queued[0].deliver()
    assert save_import.pending_import_info(c.transfer.active) is None
    assert save_import.pending_import_info(other) is not None
    assert not c.context.manager._save_cancel_running


@pytest.mark.parametrize("when", ["queued", "status"])
def test_profile_change_prevents_stale_cancellation(cancellation, monkeypatch, when):
    c = cancellation
    st.cancel_pending_save_import_async(c.context, c.notify)
    if when == "queued":
        c.epoch[0] += 1
    else:
        original = save_import.pending_import_is_installed

        def change_profile(target):
            result = original(target)
            c.epoch[0] += 1
            return result

        monkeypatch.setattr(save_import, "pending_import_is_installed", change_profile)
    _run_worker(c.queued[0])
    c.queued[0].deliver()
    assert save_import.pending_import_info(c.transfer.active) is not None
    assert not c.notices and not c.emitted
    assert not c.context.manager._save_cancel_running


def test_status_and_cancellation_share_staging_transaction(cancellation, monkeypatch):
    c = cancellation
    original = save_import.pending_import_is_installed
    observations = []

    def inspect_lock(target):
        def competing_request():
            acquired = save_import._STAGING_LOCK.acquire(blocking=False)
            observations.append(acquired)
            if acquired:
                save_import._STAGING_LOCK.release()

        competitor = Thread(target=competing_request)
        competitor.start()
        competitor.join(5)
        return original(target)

    monkeypatch.setattr(save_import, "pending_import_is_installed", inspect_lock)
    st.cancel_pending_save_import_async(c.context, c.notify)
    _run_worker(c.queued[0])
    c.queued[0].deliver()
    assert observations and not any(observations)
    assert save_import.pending_import_info(c.transfer.active) is None


def test_destroyed_notice_window_does_not_turn_success_into_failure(cancellation):
    c = cancellation

    def destroyed_window(*args):
        raise RuntimeError("wrapped C/C++ object has been deleted")

    st.cancel_pending_save_import_async(c.context, destroyed_window)
    _run_worker(c.queued[0])
    c.queued[0].deliver()
    assert save_import.pending_import_info(c.transfer.active) is None
    assert len(c.emitted) == 1
    assert not c.context.manager._save_cancel_running
