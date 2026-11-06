"""Regra de decisão pré-registrada: o clima do INMET entra no modelo?

Os limites abaixo foram fixados em ``docs/preregistro_clima.md`` antes de treinar qualquer modelo com
clima, e são aplicados de forma mecânica por ``scripts/experimento_clima.py``.
"""
from __future__ import annotations

import pandas as pd

MELHORA_MINIMA_REL = 0.01  # deviance e MAE precisam melhorar pelo menos 1% ...
K_DP = 2.0                 # ... e pelo menos 2 desvios-padrão entre sementes do modelo sem clima
ANOS_COM_MELHORA = 2       # deviance e MAE precisam melhorar em pelo menos 2 dos 3 anos de teste
# nome -> (alvo, coluna do backtest, sentido em que a métrica melhora)
METRICAS = {
    "deviance": ("n_falhas", "deviance_poisson", "menor"),
    "mae": ("chi", "mae_alimentador", "menor"),
    "spearman": ("chi", "spearman_alimentador", "maior"),
    "top10": ("chi", "captura_top10", "maior"),
}
EXIGEM_MELHORA = ("deviance", "mae")  # as outras só não podem piorar além do ruído


def avaliar(resumo: pd.DataFrame) -> dict:
    """Aplica a regra. ``resumo`` tem uma linha por modo x semente x alvo x ano de teste (coluna ``metodo``).

    ``modo`` é ``semclima`` ou ``clima``. Devolve a decisão e a conta de cada critério.
    """
    r = resumo[resumo.metodo == "modelo"]
    criterios, tudo_ok = {}, True
    for nome, (alvo, col, sentido) in METRICAS.items():
        x = r[r.alvo == alvo]
        por_semente = x.groupby(["modo", "semente"])[col].mean().unstack("modo")  # média dos anos de teste
        sem, com = por_semente["semclima"], por_semente["clima"]
        base, dp = float(sem.mean()), float(sem.std(ddof=1))
        sinal = -1.0 if sentido == "menor" else 1.0
        melhora = sinal * float(com.mean() - base)  # positivo = melhor
        if nome in EXIGEM_MELHORA:
            limiar = max(MELHORA_MINIMA_REL * abs(base), K_DP * dp)
            passa = melhora >= limiar
        else:
            limiar = -K_DP * dp
            passa = melhora >= limiar
        por_ano = x.groupby(["modo", "ano_teste"])[col].mean().unstack("modo")
        melhor = por_ano["clima"] < por_ano["semclima"] if sentido == "menor" else por_ano["clima"] > por_ano["semclima"]
        s0 = por_semente.loc[0]
        semente0_melhor = bool(sinal * (s0["clima"] - s0["semclima"]) > 0)
        c = {"sem_clima": base, "dp_sementes_sem_clima": dp, "com_clima": float(com.mean()), "melhora": melhora,
             "limiar": float(limiar), "passa_limiar": bool(passa), "anos_com_melhora": int(melhor.sum()),
             "semente0_melhora": semente0_melhor}
        if nome in EXIGEM_MELHORA:
            passa = passa and c["anos_com_melhora"] >= ANOS_COM_MELHORA and semente0_melhor
        c["criterio_ok"] = bool(passa)
        criterios[nome] = c
        tudo_ok = tudo_ok and bool(passa)
    return {"clima_entra_no_modelo": tudo_ok, "criterios": criterios}
