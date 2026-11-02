"""Serialização dos resultados para JSON interoperável."""

import math


def normalizar_nan(valor):
    """Representa métricas ausentes como null; infinitos continuam inválidos."""
    if isinstance(valor, dict):
        return {chave: normalizar_nan(item) for chave, item in valor.items()}
    if isinstance(valor, list):
        return [normalizar_nan(item) for item in valor]
    if isinstance(valor, float) and math.isnan(valor):
        return None
    return valor
