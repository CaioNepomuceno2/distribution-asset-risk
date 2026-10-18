"""Risco monetizado e otimização da carteira de intervenções.

Risco anual do alimentador f no modo c:   R(f,c) = E[CHI(f,c)] x valor_chi(f)

O capex de cada intervenção é convertido em custo anual equivalente pela sua
vida útil, de modo que ativos longos (ex.: rede compacta, 30 anos) não sejam
penalizados por um horizonte de análise menor que a vida.

Um *pacote* é um subconjunto de intervenções aplicáveis ao alimentador. O CHI
residual de um pacote combina as eficácias de forma multiplicativa por modo:

    CHI_res(f,c) = E[CHI(f,c)] x prod_i (1 - alcance_i x eficacia_i(c))

A escolha é um problema da mochila com restrição de escolha única por
alimentador (multiple-choice knapsack), resolvido como programa inteiro (CBC):

    max  sum_{f,p} VPL_beneficio(f,p) x y(f,p)
    s.a. sum_{f,p} custo_inicial(f,p) x y(f,p) <= orçamento
         sum_p y(f,p) <= 1   para todo f
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pulp
import yaml

from gridrisk.features import MODOS


@dataclass(frozen=True)
class Intervencao:
    nome: str
    descricao: str
    tipo: str
    custo: float
    quantidade: str
    aplicavel: str
    vida_anos: int
    alcance: float
    eficacia: dict[str, float]

    def eficacia_modo(self, modo: str) -> float:
        return self.alcance * self.eficacia.get(modo, self.eficacia.get("todos", 0.0))


def carregar_catalogo(path: Path) -> tuple[dict, list[Intervencao]]:
    cfg = yaml.safe_load(Path(path).read_text())
    itv = [Intervencao(nome=k, **{c: v[c] for c in Intervencao.__dataclass_fields__ if c != "nome" and c in v})
           for k, v in cfg["intervencoes"].items()]
    return cfg["financeiro"], itv


def fator_anuidade(taxa: float, anos: int) -> float:
    return (1 - (1 + taxa) ** -anos) / taxa


def _avaliar(expr: str, row: pd.Series) -> float:
    env = {k: (0.0 if pd.isna(v) else v) for k, v in row.items()}
    return float(eval(expr, {"__builtins__": {}, "ceil": math.ceil, "min": min, "max": max}, env))


def pacotes(feeders: pd.DataFrame, chi_modo: pd.DataFrame, valor_chi: pd.Series,
            catalogo: list[Intervencao], fin: dict, max_itens: int = 3,
            chi_modo_reg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Enumera os pacotes viáveis por alimentador com custo e benefício.

    feeders:      atributos (uma linha por alimentador, índice = alimentador)
    chi_modo:     E[CHI] anual valorado no benefício, índice = alimentador, colunas = MODOS
    valor_chi:    R$ por CHI do alimentador
    chi_modo_reg: E[CHI] regulatório (sem expurgos), usado para o DEC evitado
    """
    chi_modo_reg = chi_modo if chi_modo_reg is None else chi_modo_reg
    taxa, H = fin["taxa_desconto"], fin["horizonte_anos"]
    fa_h = fator_anuidade(taxa, H)
    linhas = []
    for f, row in feeders.iterrows():
        if f not in chi_modo.index:
            continue
        chi = chi_modo.loc[f, MODOS].astype(float).values
        chi_reg = chi_modo_reg.loc[f, MODOS].astype(float).values
        aplic = []
        for itv in catalogo:
            try:
                ok = _avaliar(itv.aplicavel, row) > 0
                qtd = _avaliar(itv.quantidade, row)
            except (ZeroDivisionError, TypeError, ValueError):
                ok, qtd = False, 0.0
            if ok and qtd > 0:
                aplic.append((itv, qtd))
        for r in range(1, min(max_itens, len(aplic)) + 1):
            for combo in itertools.combinations(aplic, r):
                fator = np.ones(len(MODOS))
                capex = opex = capex_anual = 0.0
                for itv, qtd in combo:
                    fator *= 1 - np.array([itv.eficacia_modo(m) for m in MODOS])
                    if itv.tipo == "capex":
                        capex += itv.custo * qtd
                        capex_anual += itv.custo * qtd / fator_anuidade(taxa, itv.vida_anos)
                    else:
                        opex += itv.custo * qtd
                chi_evitado = float((chi * (1 - fator)).sum())
                chi_evitado_reg = float((chi_reg * (1 - fator)).sum())
                beneficio_ano = chi_evitado * float(valor_chi.get(f, 0.0))
                linhas.append({
                    "alimentador": f,
                    "pacote": "+".join(i.nome for i, _ in combo),
                    "n_itens": len(combo),
                    "capex": capex,
                    "opex_ano": opex,
                    "custo_inicial": capex + opex,  # capex + 1º ano de opex saem do orçamento
                    "chi_evitado_ano": chi_evitado,
                    "chi_reg_evitado_ano": chi_evitado_reg,
                    "beneficio_ano": beneficio_ano,
                    "custo_anual_equivalente": capex_anual + opex,
                    # VPL no horizonte com o capex anualizado pela vida útil (valor residual implícito)
                    "vpl": (beneficio_ano - capex_anual - opex) * fa_h,
                })
    return pd.DataFrame(linhas)


def otimizar(cands: pd.DataFrame, orcamento: float, objetivo: str = "vpl_beneficio",
             apenas_vpl_positivo: bool = True) -> pd.DataFrame:
    """Resolve a mochila de escolha múltipla. Devolve os pacotes escolhidos."""
    c = cands.copy()
    if apenas_vpl_positivo:
        c = c[c.vpl > 0]
    if c.empty:
        return c
    valor = c.vpl if objetivo == "vpl_beneficio" else c.chi_evitado_ano
    prob = pulp.LpProblem("carteira", pulp.LpMaximize)
    y = {i: pulp.LpVariable(f"y_{i}", cat="Binary") for i in c.index}
    prob += pulp.lpSum(valor[i] * y[i] for i in c.index)
    prob += pulp.lpSum(c.custo_inicial[i] * y[i] for i in c.index) <= orcamento
    for idx in c.groupby("alimentador").groups.values():
        prob += pulp.lpSum(y[i] for i in idx) <= 1
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=120, gapRel=1e-4))
    escolhidos = [i for i in c.index if y[i].value() and y[i].value() > 0.5]
    return c.loc[escolhidos].sort_values("vpl", ascending=False)


def _encher(ordem: pd.DataFrame, orcamento: float) -> pd.DataFrame:
    """Percorre os candidatos na ordem dada, um por alimentador, pulando o que não cabe."""
    escolhidos, gasto, vistos = [], 0.0, set()
    for i, r in ordem.iterrows():
        if r.alimentador in vistos or gasto + r.custo_inicial > orcamento:
            continue
        escolhidos.append(i)
        vistos.add(r.alimentador)
        gasto += r.custo_inicial
    return ordem.loc[escolhidos]


def priorizacao_tradicional(cands: pd.DataFrame, chi_historico: pd.Series, orcamento: float,
                            pacote_padrao: tuple[str, ...] = ("religador+automacao", "religador", "automacao"),
                            ) -> pd.DataFrame:
    """Baseline "pior primeiro": ordena alimentadores pelo CHI histórico e aplica o pacote
    padrão de confiabilidade (religador + automação; ou o que for aplicável)."""
    c = cands[cands.pacote.isin(pacote_padrao)].copy()
    c["_pref"] = c.pacote.map({p: k for k, p in enumerate(pacote_padrao)})
    c = c.sort_values("_pref").drop_duplicates("alimentador")
    c["_rank"] = c.alimentador.map(chi_historico).fillna(0)
    return _encher(c.sort_values("_rank", ascending=False), orcamento).drop(columns=["_pref", "_rank"])


def guloso(cands: pd.DataFrame, orcamento: float) -> pd.DataFrame:
    """Baseline guloso: maior razão VPL/custo primeiro, um pacote por alimentador."""
    c = cands[cands.vpl > 0].copy()
    c["_razao"] = c.vpl / c.custo_inicial.clip(lower=1)
    return _encher(c.sort_values("_razao", ascending=False), orcamento).drop(columns="_razao")


def fronteira(cands: pd.DataFrame, orcamentos: list[float], chi_historico: pd.Series) -> pd.DataFrame:
    """Compara, para cada orçamento, a carteira ótima com os dois baselines."""
    linhas = []
    for b in orcamentos:
        for metodo, sel in [("otimo", otimizar(cands, b)), ("guloso", guloso(cands, b)),
                            ("tradicional", priorizacao_tradicional(cands, chi_historico, b))]:
            linhas.append({"orcamento": b, "metodo": metodo, "investido": sel.custo_inicial.sum(),
                           "chi_evitado_ano": sel.chi_evitado_ano.sum(),
                           "chi_reg_evitado_ano": sel.chi_reg_evitado_ano.sum(), "vpl": sel.vpl.sum(),
                           "n_alimentadores": len(sel)})
    return pd.DataFrame(linhas)
