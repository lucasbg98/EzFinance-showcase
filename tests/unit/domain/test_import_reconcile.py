"""Reimportação: todas as situações da §6.2 do plano (dados fictícios)."""

from __future__ import annotations

import pytest

from appfin.domain.spreadsheet_import.reconcile import (
    CellCandidate,
    ImportedState,
    ReconcileAction,
    reconcile,
)

KEY = "a" * 64


def _candidate(cents: int = 10_000, *, paid: bool = True, notes: str = "") -> CellCandidate:
    return CellCandidate(KEY, cents, paid, notes)


def _state(
    cents: int = 10_000, *, paid: bool = True, notes: str = "", changed: bool = False
) -> ImportedState:
    return ImportedState("tx-1", cents, paid, notes, changed)


def _action(candidate: CellCandidate, state: ImportedState | None) -> ReconcileAction:
    imported = {KEY: state} if state else {}
    [decision] = reconcile([candidate], imported)
    return decision.action


def test_new_cell_is_created() -> None:
    assert _action(_candidate(), None) is ReconcileAction.CREATE


def test_identical_cell_is_skipped_even_if_changed_in_app() -> None:
    assert _action(_candidate(), _state()) is ReconcileAction.SKIP
    assert _action(_candidate(), _state(changed=True)) is ReconcileAction.SKIP


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(cents=20_000),  # valor mudou
        _candidate(notes="Comentário novo"),  # observação mudou
    ],
)
def test_changed_cell_replaces_when_untouched_in_app(candidate: CellCandidate) -> None:
    assert _action(candidate, _state()) is ReconcileAction.REPLACE


def test_projection_becoming_realized_is_a_replacement() -> None:
    assert _action(_candidate(paid=True), _state(paid=False)) is ReconcileAction.REPLACE


def test_changed_cell_is_kept_when_edited_in_app() -> None:
    assert _action(_candidate(cents=20_000), _state(changed=True)) is ReconcileAction.KEEP


def test_cell_now_empty_is_removed_when_untouched() -> None:
    decisions = reconcile([], {KEY: _state()}, empty_keys=[KEY])

    assert [d.action for d in decisions] == [ReconcileAction.REMOVE]
    assert decisions[0].current == _state()


def test_cell_now_empty_is_kept_when_edited_in_app() -> None:
    decisions = reconcile([], {KEY: _state(changed=True)}, empty_keys=[KEY, KEY])

    assert [d.action for d in decisions] == [ReconcileAction.KEEP]


def test_empty_cell_never_imported_produces_nothing() -> None:
    assert reconcile([], {}, empty_keys=[KEY]) == []


def test_each_candidate_gets_one_decision_in_order() -> None:
    other = "b" * 64
    candidates = [_candidate(), CellCandidate(other, 5_000, False, "")]

    decisions = reconcile(candidates, {KEY: _state()})

    assert [(d.row_key, d.action) for d in decisions] == [
        (KEY, ReconcileAction.SKIP),
        (other, ReconcileAction.CREATE),
    ]
