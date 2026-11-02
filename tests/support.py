"""Constantes de apoio aos testes (dados sempre sintéticos)."""

from appfin.infrastructure.crypto.kdf import KdfParams

# Argon2id com custo mínimo: só para testes rodarem rápido.
# O código de produção recusa estes parâmetros (MINIMUM_SECURE_PARAMS).
FAST_PARAMS = KdfParams(opslimit=1, memlimit=8 * 1024)
FAST_MINIMUM = KdfParams(opslimit=1, memlimit=8 * 1024)
