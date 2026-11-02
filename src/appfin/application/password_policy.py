"""Política da senha mestra (docs/PROJETO.md §7.4).

- Mínimo de 12 caracteres (ou frase-senha longa).
- Força estimada pelo zxcvbn com nota ≥ 3 (de 0 a 4).
- Não pode conter o nome do consultório nem palavras óbvias do contexto.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from zxcvbn import zxcvbn

MIN_LENGTH = 12
MAX_LENGTH = 256
MIN_SCORE = 3
_CONTEXT_WORDS = ("consultorio", "odonto", "dentista", "clinica", "appfin", "financeiro", "senha")
_SCORE_LABELS = ("muito fraca", "fraca", "razoável", "boa", "forte")


@dataclass(frozen=True, slots=True)
class PasswordAssessment:
    score: int
    label: str
    problems: list[str] = field(default_factory=list)

    @property
    def is_acceptable(self) -> bool:
        return not self.problems


def assess_master_password(password: str, user_inputs: tuple[str, ...] = ()) -> PasswordAssessment:
    if len(password) > MAX_LENGTH:
        return PasswordAssessment(0, _SCORE_LABELS[0], [f"Use no máximo {MAX_LENGTH} caracteres."])
    if not password:
        return PasswordAssessment(0, _SCORE_LABELS[0], ["Digite uma senha."])
    # zxcvbn é custoso para entradas longas; analisar os primeiros 100 caracteres é suficiente.
    result = zxcvbn(password[:100], user_inputs=[*_CONTEXT_WORDS, *user_inputs])
    score = int(result["score"])
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Use pelo menos {MIN_LENGTH} caracteres.")
    if password.strip() != password:
        problems.append("Não comece nem termine a senha com espaço.")
    if score < MIN_SCORE:
        problems.append(
            "Senha fácil de adivinhar. "
            "Prefira uma frase com 4 ou mais palavras sem relação entre si."
        )
    return PasswordAssessment(score, _SCORE_LABELS[score], problems)
