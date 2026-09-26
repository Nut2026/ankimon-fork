# PR #827: proposed review fixes

The monthly-challenge flow still permits overlapping decisions and a database
write after an error dialog changes the active account. The local follow-up also
clips animated sprites. This document proposes the remaining fixes and their
acceptance tests; it does not implement them.

The review covered [PR #827](https://github.com/h0tp-ftw/ankimon/pull/827) from
`67da7bc6235fb91c53906cc07b1b82e64afbe891` to published head
`e5abbc284dc63cb95766b9c8fb06d55be122593b`: 29 commits and three changed files.
It also checked local follow-up `9d4a03f0d0b3dbc466222787cb9287753325111b`.
The proposals below build on that local commit.

| Finding | Status at the reviewed local commit |
| --- | --- |
| Stale callbacks can award into another account | Database generation and collection identity checks added; retain these checks |
| Fetch worker reads and writes a mutable shared database | Database work moved to the main-thread callback; retain this separation |
| An accepted but missing Pokemon asks for acceptance again | Fixed: restore directly and retain accepted status on failure |
| Overlapping monthly dialogs record contradictory decisions | P2: still reproduced |
| Error-dialog failure handling overwrites another account's state | P2: still reproduced |
| Animated sprites exceed their fixed labels | P3: introduced by the local follow-up |

1. **Allow only one pending monthly check per active session.**

   Change `check_and_award_monthly_pokemon()` in
   [pokemon_trade.py](../../src/Ankimon/pyobj/pokemon_trade.py), and bind the
   connectivity completion in [profile_hooks.py](../../src/Ankimon/profile_hooks.py)
   to the collection that scheduled it.

   A connectivity result from a previous profile can arrive after another profile
   opens and start a check against the new session. Its own connectivity result
   can start a second check. Both requests then pass session validation. The first
   decision dialog's nested event loop delivers the second callback before the
   first decision is saved. Real Qt/SQLite tests accepted the inner dialog and
   rejected the outer one, leaving an owned Pokemon with rejected status `2`.

   Capture the database manager, its identity token, and the open collection on
   the main thread. Coalesce another request for that session while fetching,
   processing, or showing its dialogs. A different session must remain able to
   start its own check. Discard connectivity completions whose originating
   collection has closed or changed.

   Release the pending request on every completion, failure, and stale-result
   path, including failure to dispatch the worker. Cleanup must belong to the
   specific request so an old callback cannot clear a newer request's guard.
   After a decision dialog returns, revalidate both session identity and the
   current challenge decision/ownership before saving. A stale prompt must not
   overwrite a newer decision or an existing Pokemon's progress. Define this
   check against the state offered by the prompt; do not globally reinterpret
   every owned-but-rejected record without considering the explicit rejection
   feature in PR #828.

2. **Separate award persistence from presentation failures.**

   Change `add_pokemon_to_collection()` and the monthly acceptance handler in
   [pokemon_trade.py](../../src/Ankimon/pyobj/pokemon_trade.py). At local commit
   `9d4a03f0`, the unchecked failure write is at line 868; the published equivalent
   is at line 938.

   The helper can commit the Pokemon, fail while refreshing an open PC, display
   the real modal `Ankimon Error` dialog, and return `False`. A database switch
   during that second dialog happens after the acceptance handler's identity
   check. The subsequent failure write then targets the new account.

   The proof injected a PC-refresh exception after a real SQLite save, switched
   from account A to B during the actual warning dialog, and dismissed it. B's
   challenge ID was replaced with A's and its saved rejection changed from `2`
   to `0`. The exception was injected to exercise error handling; this does not
   imply that ordinary PC refresh always fails.

   Treat a committed save as a successful award even if refreshing the PC fails.
   Keep refresh and warning presentation outside the persistence result, and
   finish the accepted-state write before any presentation step that can enter
   another event loop. Revalidate the originating session after any remaining
   helper that can show a dialog, before either success or failure state writes.
   Do not hold a database transaction across a modal dialog.

   Avoid resetting an already-unclaimed challenge to `0` after a failed save.
   A failed restoration of an accepted Pokemon must retain status `1`. If any
   failure write remains necessary, validate its database identity and current
   challenge state immediately before writing. Preserve the existing atomic
   update of the challenge ID and status in `set_monthly_challenge_state()`.

3. **Restore aspect-ratio-preserving animation scaling.**

   Restore the first-frame sizing in `_build_sprite_box()` in
   [pokemon_trade.py](../../src/Ankimon/pyobj/pokemon_trade.py), removed by the
   local follow-up near lines 103-107. Load the first frame, calculate the size
   that fits the label with `Qt.AspectRatioMode.KeepAspectRatio`, and apply it
   through `QMovie.setScaledSize()` before starting playback. Retain the movie's
   label parent and the existing sprite-visibility setting.

   The actual Wingull GIF used in the review has a 143x24 first frame. The local
   commit renders it at that size in both 120x120 and 64x64 labels, cropping its
   wings. The published implementation passes the same check, rendering at
   120x20 and 64x10 respectively.

Add permanent regression coverage under `tests/` or `harness/`, outside the
shipped `src/` tree. Use disposable databases and controlled network responses.
These are acceptance criteria for the implementation:

| Scenario | Required result |
| --- | --- |
| Deliver old and new profile connectivity completions after reopening | Stale completion is discarded; one monthly decision dialog appears |
| Deliver two monthly results while the first dialog is open | No second decision for the same session; the first choice persists once |
| Fail the fetch or dispatch, then retry; finish an older request after a newer one starts | Retry works; old cleanup does not remove the new request's guard |
| Switch A to B during a warning after an injected refresh failure | B's challenge ID, decision, and collection remain unchanged; A's committed award is preserved |
| Save succeeds but PC refresh fails without an account switch | Award remains accepted; refresh failure cannot downgrade its decision |
| Previously accepted Pokemon is missing; restore succeeds or fails | No new Accept/Reject prompt; status remains `1` in both cases |
| Switch database, replace the manager, close/reopen the profile, or switch A to B to A during fetch | Stale callback performs no state writes or award; fetch worker performs no database work |
| Render the 143x24 GIF in each dialog size, then hide sprites | Movie fits 120px and 64px labels without clipping; hiding sprites still works |

Use real offscreen Qt dialogs and SQLite for modal-event-loop cases, with actual
button clicks and queued callbacks. Add a screenshot check for both sprite sizes.
Retain the database identity and atomic state-update tests. Once the fixes are
implemented, run `python3 harness/check.py`, `python -m pytest tests/`, and the
real-addon startup smoke test required for the profile-hook change. Report any
environment limitation separately from a failing assertion.

The review already reproduced the three outstanding issues. The published-head
baseline passed nine Tier-1 checks and seven monthly tests. The isolated integrity
test passed with unrelated audio constructors substituted; native audio hung in
the sandbox. Focused database transaction and identity proofs passed. A full-suite
pass was not established. Those results describe the reviewed commits, not the
proposed fixes, which still require implementation and validation.
