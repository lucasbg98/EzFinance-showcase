"""Reimportação: células da planilha versus lançamentos já importados (plano de importação §6.2).

Puro. O app **nunca apaga trabalho feito nele**: um lançamento "alterado no app" (``version > 1``
ou com recibo) é mantido e a diferença só é informada.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class CellCandidate:
    """Célula com valor que viraria lançamento."""

    row_key: str
    amount_cents: int
    is_paid: bool
    notes: str


@dataclass(frozen=True, slots=True)
class ImportedState:
    """O que o app tem hoje para uma célula já importada."""

    transaction_id: str
    amount_cents: int
    is_paid: bool
    notes: str
    changed_in_app: bool


class ReconcileAction(StrEnum):
    CREATE = "create"  # célula nova
    SKIP = "skip"  # já importada, igual
    REPLACE = "replace"  # mudou na planilha e o app não mexeu: troca o antigo pelo novo
    KEEP = "keep"  # mudou (ou zerou) na planilha, mas foi alterada no app: mantém o do app
    REMOVE = "remove"  # zerou na planilha e o app não mexeu: remove o antigo


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    row_key: str
    action: ReconcileAction
    candidate: CellCandidate | None = None
    current: ImportedState | None = None


def reconcile(
    candidates: Sequence[CellCandidate],
    imported: Mapping[str, ImportedState],
    empty_keys: Collection[str] = (),
) -> list[ReconcileDecision]:
    """Decide o que fazer com cada célula.

    ``imported``: estado atual das células já importadas (chave → estado).
    ``empty_keys``: células hoje vazias/zeradas; se tinham sido importadas, saem do app.
    """
    decisions: list[ReconcileDecision] = []
    for candidate in candidates:
        current = imported.get(candidate.row_key)
        decisions.append(
            ReconcileDecision(candidate.row_key, _action(candidate, current), candidate, current)
        )
    candidate_keys = {candidate.row_key for candidate in candidates}
    for row_key in dict.fromkeys(empty_keys):
        current = imported.get(row_key)
        if current is None or row_key in candidate_keys:
            continue
        action = ReconcileAction.KEEP if current.changed_in_app else ReconcileAction.REMOVE
        decisions.append(ReconcileDecision(row_key, action, None, current))
    return decisions


def _action(candidate: CellCandidate, current: ImportedState | None) -> ReconcileAction:
    if current is None:
        return ReconcileAction.CREATE
    unchanged = (
        current.amount_cents == candidate.amount_cents
        and current.is_paid == candidate.is_paid
        and current.notes == candidate.notes
    )
    if unchanged:
        return ReconcileAction.SKIP
    return ReconcileAction.KEEP if current.changed_in_app else ReconcileAction.REPLACE
