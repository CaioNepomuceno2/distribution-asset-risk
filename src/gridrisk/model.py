"""Modelos de frequência de falha e de CHI por alimentador x modo de falha.

* ``n_falhas`` ~ LightGBM com objetivo Poisson (contagem anual).
* ``chi``      ~ LightGBM com objetivo Tweedie (massa em zero + cauda longa).

Validação temporal por origem móvel: para cada ano de teste ``t``, treina com
anos ``< t``. Os baselines são os que um planejamento tradicional usaria:
média histórica de 3 anos e "ano passado se repete".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from gridrisk.features import MODOS

ID = ["alimentador", "ano", "modo"]
ALVOS = ["n_falhas", "chi", "chi_regulatorio", "ci"]
# Idades da BDGD ficam de fora: a data de conexão cadastral não reflete a idade
# física do ativo (datas-padrão, recadastramento em massa). Ver docs/dados.md.
IDADES = ["idade_media_trafos", "idade_p90_trafos", "frac_trafos_25anos", "frac_trafos_sem_data",
          "idade_media_chaves"]
EXCLUIR = set(ID + ALVOS + IDADES + ["alimentador_nome", "subestacao_bdgd", "ten_nom_cod"])

PARAMS_BASE = {
    "learning_rate": 0.03, "num_leaves": 31, "min_child_samples": 40, "subsample": 0.8, "subsample_freq": 1,
    "colsample_bytree": 0.8, "reg_lambda": 1.0, "n_estimators": 600, "verbose": -1,
}


def feature_cols(panel: pd.DataFrame) -> list[str]:
    return [c for c in panel.columns if c not in EXCLUIR] + ["modo"]


def design(panel: pd.DataFrame) -> pd.DataFrame:
    X = panel[feature_cols(panel)].copy()
    num = [c for c in X.columns if c != "modo"]
    X[num] = X[num].astype("float64")
    X["modo"] = pd.Categorical(X["modo"].astype(str), categories=MODOS)
    return X


def make_model(alvo: str, seed: int = 0) -> lgb.LGBMRegressor:
    if alvo == "n_falhas":
        return lgb.LGBMRegressor(objective="poisson", random_state=seed, **PARAMS_BASE)
    return lgb.LGBMRegressor(objective="tweedie", tweedie_variance_power=1.4, random_state=seed, **PARAMS_BASE)


def fit(panel: pd.DataFrame, alvo: str, seed: int = 0) -> lgb.LGBMRegressor:
    X = design(panel)
    m = make_model(alvo, seed)
    m.fit(X, panel[alvo], categorical_feature=["modo"])
    return m


def poisson_deviance(y, mu):
    mu = np.maximum(mu, 1e-9)
    return 2 * np.mean(np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / mu), 0) - (y - mu))


def captura_top(y_true: pd.Series, y_pred: pd.Series, frac: float = 0.1) -> float:
    """Fração do total real capturada pelos ``frac`` alimentadores de maior previsão."""
    k = max(1, round(len(y_pred) * frac))
    top = y_pred.sort_values(ascending=False).index[:k]
    return float(y_true.loc[top].sum() / y_true.sum())


def metricas(df: pd.DataFrame, alvo: str, pred: str) -> dict:
    """Métricas no nível alimentador x modo e no nível alimentador (soma dos modos)."""
    fe = df.groupby("alimentador")[[alvo, pred]].sum()
    out = {
        "mae_alim_modo": float(np.mean(np.abs(df[alvo] - df[pred]))),
        "mae_alimentador": float(np.mean(np.abs(fe[alvo] - fe[pred]))),
        "spearman_alimentador": float(spearmanr(fe[alvo], fe[pred]).statistic),
        "captura_top10": captura_top(fe[alvo], fe[pred], 0.10),
        "captura_top20": captura_top(fe[alvo], fe[pred], 0.20),
        "vies_total_pct": float(100 * (df[pred].sum() / df[alvo].sum() - 1)),
    }
    if alvo == "n_falhas":
        out["deviance_poisson"] = float(poisson_deviance(df[alvo].values, df[pred].values))
    return out


@dataclass
class Backtest:
    alvo: str
    previsoes: pd.DataFrame
    resumo: pd.DataFrame
    modelos: dict = field(default_factory=dict)


def backtest(panel: pd.DataFrame, alvo: str, anos_teste: list[int]) -> Backtest:
    hist_col = "n_falhas_media_3a" if alvo == "n_falhas" else "chi_media_3a"
    last_col = "n_falhas_media_1a" if alvo == "n_falhas" else "chi_media_1a"
    prevs, linhas, modelos = [], [], {}
    for t in anos_teste:
        tr, te = panel[panel.ano < t], panel[panel.ano == t].copy()
        m = fit(tr, alvo)
        modelos[t] = m
        te["pred_modelo"] = m.predict(design(te))
        te["pred_media_3a"] = te[hist_col]
        te["pred_ano_anterior"] = te[last_col]
        for p in ["pred_modelo", "pred_media_3a", "pred_ano_anterior"]:
            linhas.append({"ano_teste": t, "metodo": p.removeprefix("pred_"), **metricas(te, alvo, p)})
        prevs.append(te[ID + [alvo, "pred_modelo", "pred_media_3a", "pred_ano_anterior"]])
    resumo = pd.DataFrame(linhas)
    return Backtest(alvo, pd.concat(prevs, ignore_index=True), resumo, modelos)


def calibracao(prev: pd.DataFrame, alvo: str, pred: str = "pred_modelo", q: int = 10) -> pd.DataFrame:
    fe = prev.groupby(["ano", "alimentador"])[[alvo, pred]].sum().reset_index()
    fe["decil"] = fe.groupby("ano")[pred].transform(lambda s: pd.qcut(s.rank(method="first"), q, labels=False) + 1)
    return fe.groupby("decil")[[pred, alvo]].mean().rename(columns={pred: "previsto", alvo: "observado"})
