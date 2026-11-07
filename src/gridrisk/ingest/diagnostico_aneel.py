"""Diagnósticos das interrupções e da continuidade da ANEEL, e do cadastro, que sustentam ``docs/decisoes_ems.md``.

Cada função devolve uma tabela pequena e só mede; ``scripts/diagnostico_aneel.py`` grava as tabelas em
``<reports>/diagnostico/``. As decisões ficam no documento, não aqui.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from gridrisk import otimizacao as O
from gridrisk.ingest import duplicatas
from gridrisk.ingest.continuidade import dec_fec_oficial, leitura_sem_duplicatas

LIMITES_ISE_H = (3, 6, 12, 24, 48, 72, 96, 120)


def interrupcoes_por_mes(interrupcoes: Path) -> pd.DataFrame:
    """Registros por ano e mês: mostra meses sem nenhum registro."""
    return duckdb.sql(f"select ano, mes, count(*) as registros from read_parquet('{interrupcoes}') group by all "
                      "order by ano, mes").df()


def _perfil(fonte: str, uc: str, tensao: str, causa: str, origem: str, expurgo: str, sigla: str) -> str:
    return f"""
        select {expurgo} as codigo, count(*) as registros, round(avg({uc}), 2) as uc_medio,
               round(100 * avg(case when {tensao} < 1000 then 1.0 else 0 end), 1) as pct_bt,
               round(100 * avg(case when {tensao} >= 69000 then 1.0 else 0 end), 1) as pct_at,
               mode({causa}) as causa_modal, mode({origem}) as origem_modal,
               round(avg(date_diff('second', DatInicioInterrupcao, DatFimInterrupcao) / 3600.0), 2) as duracao_media_h
        from read_parquet('{fonte}') where trim(SigAgente) = '{sigla}' group by 1"""


def perfil_expurgo(pasta: Path, sigla: str, ano_legado: int = 2025, ano_novo: int = 2026) -> pd.DataFrame:
    """Perfil de cada código de expurgo do layout legado e de cada categoria do layout novo.

    É a comparação que sustenta o mapeamento ``EXPURGO_LEGADO``: o mesmo perfil de UC por registro, de nível de tensão
    e de causa em ambos os layouts, para a mesma distribuidora.
    """
    leg = duckdb.sql(_perfil(
        str(pasta / f"interrupcoes-energia-eletrica-{ano_legado}.parquet"), "NumUnidadeConsumidora", "NumNivelTensao",
        "upper(strip_accents(trim(split_part(DscFatoGeradorInterrupcao, '-', 3))))",
        "upper(strip_accents(trim(split_part(DscFatoGeradorInterrupcao, '-', 1))))", "cast(IdeMotivoInterrupcao as varchar)",
        sigla)).df().assign(layout=f"legado {ano_legado}")
    novo = duckdb.sql(_perfil(
        str(pasta / f"interrupcoes-energia-eletrica-{ano_novo}.parquet"), "QtdConsumidoresAfetados", "NumNivelTensao",
        "upper(strip_accents(trim(DscFatoGeradorCausa)))", "upper(strip_accents(trim(DscFatoGeradorOrigem)))",
        "DscMotivoExpurgo", sigla)).df().assign(layout=f"novo {ano_novo}")
    return pd.concat([leg, novo], ignore_index=True)[
        ["layout", "codigo", "registros", "uc_medio", "pct_bt", "pct_at", "causa_modal", "origem_modal", "duracao_media_h"]
    ].sort_values(["layout", "registros"], ascending=[True, False]).reset_index(drop=True)


def codigos_expurgo_por_ano(pasta: Path, sigla: str, anos: list[int]) -> pd.DataFrame:
    """Registros por código de expurgo do layout legado e por ano (os anos do layout novo não têm o código)."""
    partes = " union all ".join(
        f"select {a} as ano, IdeMotivoInterrupcao as codigo from read_parquet("
        f"'{pasta / f'interrupcoes-energia-eletrica-{a}.parquet'}') where trim(SigAgente) = '{sigla}'" for a in anos)
    return duckdb.sql(f"select ano, codigo, count(*) as registros from ({partes}) group by all order by 1, 2").df()


def falhas_por_expurgo(interrupcoes: Path) -> pd.DataFrame:
    """Falhas de MT (internas, não programadas) por ano e expurgo, em registros e em CHI."""
    d = duckdb.sql(f"""
        select ano, expurgo, count(*) as registros, sum(chi) as chi from read_parquet('{interrupcoes}')
        where origem_mt and origem = 'INTERNA' and tipo = 'NAO PROGRAMADA' group by all order by 1, 2""").df()
    d["pct_registros"] = 100 * d.registros / d.groupby("ano").registros.transform("sum")
    d["pct_chi"] = 100 * d.chi / d.groupby("ano").chi.transform("sum")
    return d


def falhas_por_grupo_causa(interrupcoes: Path) -> pd.DataFrame:
    d = duckdb.sql(f"""
        select ano, grupo_causa, count(*) as registros from read_parquet('{interrupcoes}')
        where origem_mt and origem = 'INTERNA' and tipo = 'NAO PROGRAMADA' group by all order by 1, 2""").df()
    d["pct_registros"] = 100 * d.registros / d.groupby("ano").registros.transform("sum")
    return d


def chi_por_modo(falhas: pd.DataFrame, ano_ini: int, ano_fim: int) -> pd.DataFrame:
    """CHI anual médio por modo de falha, total e regulatório, e a fração expurgada."""
    n = ano_fim - ano_ini + 1
    m = falhas[falhas.ano.between(ano_ini, ano_fim)].groupby("modo")[["chi", "chi_regulatorio"]].sum() / n
    m["pct_do_total"] = 100 * m.chi / m.chi.sum()
    m["pct_expurgado"] = 100 * (1 - m.chi_regulatorio / m.chi)
    total = m[["chi", "chi_regulatorio"]].sum()
    m.loc["TOTAL"] = [total.chi, total.chi_regulatorio, 100.0, 100 * (1 - total.chi_regulatorio / total.chi)]
    return m.sort_values("chi", ascending=False).reset_index()


def _dec_mensal(indicadores: Path, interrupcoes: Path, sigla: str) -> pd.DataFrame:
    """DEC oficial e calculado por conjunto x ano x mês, só até o último mês com interrupções de cada ano."""
    oficial = dec_fec_oficial(indicadores, sigla)
    ate = duckdb.sql(f"select ano, max(mes) as mes_max, count(*) as registros from read_parquet('{interrupcoes}') "
                     "group by ano").df()
    oficial = oficial.merge(ate[["ano", "mes_max"]], on="ano").query("mes <= mes_max").drop(columns="mes_max")
    calc = duckdb.sql(f"""
        select conjunto_id c, ano, mes, sum(chi) chi from read_parquet('{interrupcoes}')
        where expurgo = 'NAO HOUVE EXPURGO' and duracao_h >= 3.0/60 group by all""").df()
    return oficial.merge(calc, on=["c", "ano", "mes"], how="left").fillna({"chi": 0})


def dec_sem_buracos(indicadores: Path, interrupcoes: Path, sigla: str, razao_minima: float = 0.9) -> pd.DataFrame:
    """Correlação mensal por conjunto entre o DEC oficial e o calculado, com e sem os meses de razão muito baixa.

    ``razao`` = DEC calculado ÷ oficial no mês (todos os conjuntos). Meses abaixo de ``razao_minima`` são buracos nos
    dados de interrupções (mês sem registros, ou CHI que o regulador conta e o arquivo marca como expurgado).
    """
    m = _dec_mensal(indicadores, interrupcoes, sigla)
    m["x"] = m.chi / m.NumCon
    mes = m.groupby(["ano", "mes"]).apply(
        lambda g: (g.chi.sum() / g.NumCon.sum()) / ((g.DEC * g.NumCon).sum() / g.NumCon.sum()), include_groups=False)
    ruins = mes[mes < razao_minima].index
    sem = m[~m.set_index(["ano", "mes"]).index.isin(ruins)]
    return pd.DataFrame([
        {"conjunto": "todos os meses", "meses_excluidos": "", "linhas": len(m), "corr_dec": m[["DEC", "x"]].corr().iloc[0, 1]},
        {"conjunto": f"sem os meses com razão < {razao_minima}", "linhas": len(sem),
         "meses_excluidos": ", ".join(f"{a}-{mm:02d}" for a, mm in ruins), "corr_dec": sem[["DEC", "x"]].corr().iloc[0, 1]},
    ])


def ise_acima_de_limite(indicadores: Path, interrupcoes: Path, sigla: str, ano: int, mes: int,
                        limites: tuple[int, ...] = LIMITES_ISE_H) -> pd.DataFrame:
    """CHI de ISE por meio de CHI no mês, acima de cada limite de duração, contra a diferença entre o DEC oficial e o calculado.

    Se o regulador só conta a parcela de ISE acima de um limite de restabelecimento, a diferença (CHI oficial menos CHI
    calculado) deve ser parecida com o excesso acima desse limite. É uma comparação, não uma prova.
    """
    m = _dec_mensal(indicadores, interrupcoes, sigla)
    g = m[(m.ano == ano) & (m.mes == mes)]
    chi_oficial = float((g.DEC * g.NumCon).sum())
    chi_calculado = float(g.chi.sum())
    linhas = []
    for d in limites:
        r = duckdb.execute(f"""
            select coalesce(sum(case when duracao_h > {d} then chi end), 0),
                   coalesce(sum(case when duracao_h > {d} then (duracao_h - {d}) * uc_afetadas end), 0),
                   count(*) filter (where duracao_h > {d})
            from read_parquet('{interrupcoes}') where ano = {ano} and mes = {mes} and expurgo = 'ISE POR MEIO DE CHI'
        """).fetchall()[0]
        linhas.append({"ano": ano, "mes": mes, "limite_h": d, "eventos": r[2], "chi_cheio_acima_do_limite": r[0],
                       "chi_so_o_excesso": r[1], "chi_oficial": chi_oficial, "chi_calculado": chi_calculado,
                       "diferenca_oficial_menos_calculado": chi_oficial - chi_calculado})
    return pd.DataFrame(linhas)


def mes_de_menor_razao(indicadores: Path, interrupcoes: Path, sigla: str, registros_minimos: int = 1000) -> tuple[int, int]:
    """(ano, mês) de menor razão calculado ÷ oficial entre os meses com pelo menos ``registros_minimos`` registros."""
    m = _dec_mensal(indicadores, interrupcoes, sigla)
    razao = m.groupby(["ano", "mes"]).apply(lambda g: g.chi.sum() / (g.DEC * g.NumCon).sum(), include_groups=False)
    n = interrupcoes_por_mes(interrupcoes).set_index(["ano", "mes"]).registros
    razao = razao[[i for i in razao.index if n.get(i, 0) >= registros_minimos]]
    ano, mes = razao.idxmin()
    return int(ano), int(mes)


def compensacoes_por_ano(compensacao: Path, sigla: str) -> pd.DataFrame:
    """R$ pagos por violação (indicadores ``PG*``) e conjuntos com compensação, por ano, sem as linhas repetidas."""
    fonte = leitura_sem_duplicatas(compensacao, f"trim(SigAgente) = '{sigla}'")
    d = duckdb.sql(f"""
        select AnoIndice as ano, count(distinct IdeConjUndConsumidoras) as conjuntos,
               sum(VlrIndiceEnviado) filter (where SigIndicador like 'PG%') as pg_reais
        from {fonte} group by 1 order by 1""").df()
    d["pg_milhoes"] = d.pg_reais / 1e6
    return d


def conjuntos_compensacao(compensacao: Path, interrupcoes: Path, sigla: str) -> pd.DataFrame:
    """Conjuntos com compensação paga, conjuntos nas interrupções e a interseção (para o R$/CHI por conjunto)."""
    fonte = leitura_sem_duplicatas(compensacao, f"trim(SigAgente) = '{sigla}' and SigIndicador like 'PG%'")
    c = set(duckdb.sql(f"select distinct IdeConjUndConsumidoras from {fonte}").df().iloc[:, 0])
    i = set(duckdb.sql(f"select distinct conjunto_id from read_parquet('{interrupcoes}')").df().iloc[:, 0])
    return pd.DataFrame([{"com_compensacao": len(c), "nas_interrupcoes": len(i), "em_ambos": len(c & i)}])


def duplicatas_interrupcoes(pasta: Path, sigla: str, anos: list[int]) -> pd.DataFrame:
    """``count(*)`` contra ``count(distinct *)`` dos Parquet anuais de interrupções da distribuidora."""
    return pd.DataFrame([duplicatas.contar(pasta / f"interrupcoes-energia-eletrica-{a}.parquet", sigla) for a in anos])


def circuitos_vazios(interim: Path) -> pd.DataFrame:
    """Circuitos sem rede MT e sem consumidor em cada snapshot (``bdgd_feeders_<ano>.parquet``)."""
    linhas = []
    for p in sorted(interim.glob("bdgd_feeders_*.parquet")):
        d = pd.read_parquet(p)
        linhas.append({"ano": int(p.stem.split("_")[-1]), "circuitos": len(d),
                       "sem_rede_e_sem_uc": int((d.rede_mt_km.isna() & (d.n_uc == 0)).sum()),
                       "sem_uc": int((d.n_uc == 0).sum()), "rede_menor_que_1km": int((d.rede_mt_km < 1).sum())})
    return pd.DataFrame(linhas)


def elegibilidade(feeders: pd.DataFrame, catalogo: list[O.Intervencao]) -> pd.DataFrame:
    """Alimentadores em que cada intervenção do catálogo é aplicável (regra ``aplicavel`` e quantidade positiva)."""
    f = feeders.drop_duplicates("alimentador_nome")
    linhas = []
    for itv in catalogo:
        n = 0
        for _, row in f.iterrows():
            try:
                n += bool(O._avaliar(itv.aplicavel, row) > 0 and O._avaliar(itv.quantidade, row) > 0)
            except (ZeroDivisionError, TypeError, ValueError):
                pass
        linhas.append({"intervencao": itv.nome, "elegiveis": n, "alimentadores": len(f), "pct": 100 * n / len(f)})
    return pd.DataFrame(linhas)


def comparacao_descritiva(riscos: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Indicadores normalizados por consumidor e por km, de ``risco_alimentador.parquet`` de cada distribuidora."""
    linhas = {}
    for nome, d in riscos.items():
        uc, km = d.n_uc.sum(), d.rede_mt_km.sum()
        linhas[nome] = {
            "alimentadores": len(d), "consumidores": int(uc), "rede_mt_km": float(km), "consumidores_por_km": uc / km,
            "chi_previsto_por_consumidor": d.chi_previsto.sum() / uc, "chi_previsto_por_km": d.chi_previsto.sum() / km,
            "chi_regulatorio_previsto_por_consumidor": d.chi_reg_previsto.sum() / uc,
            "dec_previsto_falhas_mt_h": float(d.dec_contribuicao_h.sum()),
            "risco_social_rs_por_consumidor": d.risco_rs_social.sum() / uc,
            "risco_compensacao_rs_por_consumidor": d.risco_rs_compensacao.sum() / uc,
            "top10pct_do_risco_social": _concentracao(d.risco_rs_social, 0.10),
            "top20pct_do_risco_social": _concentracao(d.risco_rs_social, 0.20)}
    return pd.DataFrame(linhas).T.rename_axis("distribuidora").reset_index()


def _concentracao(s: pd.Series, frac: float) -> float:
    s = s.sort_values(ascending=False)
    return float(s.head(round(len(s) * frac)).sum() / s.sum()) if s.sum() else float(np.nan)
