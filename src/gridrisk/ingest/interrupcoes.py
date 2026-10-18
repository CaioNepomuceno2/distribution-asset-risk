"""Ingestão das interrupções da ANEEL (dataset "Interrupções de Energia Elétrica nas
Redes de Distribuição").

Os arquivos anuais têm dois layouts:

* **legado** (2017-2025): fato gerador concatenado em ``DscFatoGeradorInterrupcao``
  e expurgo codificado em ``IdeMotivoInterrupcao``; alimentador pelo nome
  operacional (``CTMT.NOME`` da BDGD).
* **novo** (2026+): fato gerador em quatro colunas, expurgo descrito por extenso,
  alimentador pelo ``CTMT.COD_ID`` da BDGD e tipo de elemento interrompido.

Este módulo baixa os arquivos e devolve um único esquema harmonizado.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import duckdb
import requests

log = logging.getLogger(__name__)

CKAN = "https://dadosabertos.aneel.gov.br/api/3/action/package_show"
DATASET = "interrupcoes-de-energia-eletrica-nas-redes-de-distribuicao"

# Códigos de IdeMotivoInterrupcao do layout legado. A ANEEL não publica mais o
# domínio; o mapeamento foi inferido comparando, para a mesma distribuidora,
# a distribuição de cada código (UCs afetadas, nível de tensão, causa dominante)
# com o campo DscMotivoExpurgo do layout novo. Ver docs/dados.md.
EXPURGO_LEGADO = {
    0: "NAO HOUVE EXPURGO",
    1: "FALHA NAS INSTALACOES DA UC SEM AFETAR TERCEIROS",
    2: "OBRAS DE INTERESSE EXCLUSIVO DO USUARIO",
    3: "ISE POR MEIO DE CHI",
    5: "ISE POR MEIO DE DECRETO",
    6: "DIA CRITICO",
    7: "RACIONAMENTO OU ALIVIO DE CARGA",
    8: "ORIGEM EXTERNA AO SISTEMA DE DISTRIBUICAO",
}

EXPURGO_NOVO = {
    "Não houve Expurgo": "NAO HOUVE EXPURGO",
    "Falha nas instalações da unidade consumidora sem afetar terceiros": "FALHA NAS INSTALACOES DA UC SEM AFETAR TERCEIROS",
    "Obras de interesse exclusivo do usuário": "OBRAS DE INTERESSE EXCLUSIVO DO USUARIO",
    "Interrupção em Situação de Emergência (ISE) por meio de CHI": "ISE POR MEIO DE CHI",
    "Interrupção em Situação de Emergência (ISE) por meio de decreto": "ISE POR MEIO DE DECRETO",
    "Interrupção ocorrida em Dia Crítico": "DIA CRITICO",
    "Interrupção vinculada a programa de racionamento instituído pela União": "RACIONAMENTO OU ALIVIO DE CARGA",
    "Interrupção de origem externa ao sistema de distribuição": "ORIGEM EXTERNA AO SISTEMA DE DISTRIBUICAO",
}


def _resource_urls() -> dict[int, str]:
    r = requests.get(CKAN, params={"id": DATASET}, timeout=60)
    r.raise_for_status()
    out = {}
    for res in r.json()["result"]["resources"]:
        if res["format"].upper() == "PARQUET":
            ano = int(res["name"].split("-")[-1].split(".")[0])
            out[ano] = res["url"]
    return out


def download(anos: list[int], dest: Path, retries: int = 4) -> list[Path]:
    """Baixa os Parquet anuais que ainda não existem (ou estão incompletos)."""
    dest.mkdir(parents=True, exist_ok=True)
    urls = _resource_urls()
    paths = []
    for ano in anos:
        url = urls[ano]
        path = dest / Path(url).name
        expected = int(requests.head(url, timeout=60).headers.get("content-length", -1))
        if path.exists() and path.stat().st_size == expected:
            paths.append(path)
            continue
        for attempt in range(retries):
            try:
                log.info("baixando %s", url)
                with requests.get(url, stream=True, timeout=1200) as r:
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        f.writelines(r.iter_content(1 << 20))
                break
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** (attempt + 1))
        paths.append(path)
    return paths


def _norm(col: str) -> str:
    """Maiúsculas, sem acento e sem espaços nas pontas."""
    return f"upper(trim(strip_accents({col})))"


def _expurgo_case(mapping: dict, col: str) -> str:
    whens = " ".join(
        f"when {col} = {k!r} then {v!r}" if isinstance(k, str) else f"when {col} = {k} then {v!r}"
        for k, v in mapping.items()
    )
    return f"case {whens} else 'OUTRO' end"


def _sql_legado(path: Path, sigla: str) -> str:
    fato = "string_split(DscFatoGeradorInterrupcao, '-')"
    return f"""
    select
        NumOrdemInterrupcao                          as cod_interrupcao,
        DatInicioInterrupcao                         as inicio,
        DatFimInterrupcao                            as fim,
        IdeConjuntoUnidadeConsumidora                as conjunto_id,
        {_norm('DscConjuntoUnidadeConsumidora')}     as conjunto_nome,
        lpad(trim(DscAlimentadorSubestacao), 6, '0') as alimentador_nome,
        cast(null as varchar)                        as alimentador_cod_id,
        trim(DscSubestacaoDistribuicao)              as subestacao,
        {_norm(f'{fato}[1]')}                        as origem,
        {_norm(f'{fato}[2]')}                        as tipo,
        {_norm(f'{fato}[3]')}                        as causa,
        {_norm(f"array_to_string({fato}[4:], '-')")} as detalhe,
        cast(NumNivelTensao as integer)              as nivel_tensao_v,
        cast(NumUnidadeConsumidora as integer)       as uc_afetadas,
        cast(NumConsumidorConjunto as integer)       as uc_conjunto,
        {_expurgo_case(EXPURGO_LEGADO, 'IdeMotivoInterrupcao')} as expurgo,
        cast(null as varchar)                        as elemento,
        cast(null as varchar)                        as localizacao
    from read_parquet('{path}')
    where trim(SigAgente) = '{sigla}'
    """


def _sql_novo(path: Path, sigla: str) -> str:
    return f"""
    select
        CodInterrupcao                           as cod_interrupcao,
        DatInicioInterrupcao                     as inicio,
        DatFimInterrupcao                        as fim,
        cast(CodConjUnidadeConsumidora as bigint) as conjunto_id,
        {_norm('DscConjuntoUnidadeConsumidora')} as conjunto_nome,
        cast(null as varchar)                    as alimentador_nome,
        trim(cast(CodAlimentador as varchar))    as alimentador_cod_id,
        trim(cast(CodSubestacao as varchar))     as subestacao,
        {_norm('DscFatoGeradorOrigem')}          as origem,
        {_norm('DscFatoGeradorTipo')}            as tipo,
        {_norm('DscFatoGeradorCausa')}           as causa,
        {_norm('DscFatoGeradorDetalhe')}         as detalhe,
        cast(NumNivelTensao as integer)          as nivel_tensao_v,
        cast(QtdConsumidoresAfetados as integer) as uc_afetadas,
        cast(QtdConsumidoresAtivos as integer)   as uc_conjunto,
        {_expurgo_case(EXPURGO_NOVO, 'DscMotivoExpurgo')} as expurgo,
        {_norm('DscTipoElementoInterrompido')}   as elemento,
        {_norm('DscLocalizacaoInterrupcao')}     as localizacao
    from read_parquet('{path}')
    where trim(SigAgente) = '{sigla}'
    """


# Agrupamento das causas em famílias de modo de falha. Os dois layouts usam a
# mesma taxonomia do PRODIST Módulo 8, mas com grafias diferentes (abreviações,
# acentos), por isso o casamento é feito por padrão no detalhe.
GRUPO_CAUSA_SQL = """
case
    when origem = 'EXTERNA'                                  then 'EXTERNA'
    when tipo = 'PROGRAMADA'                                 then 'PROGRAMADA'
    when detalhe like 'FALHA%MAT%'                          then 'EQUIPAMENTO'
    when detalhe in ('SOBRECARGA', 'SUBTENSAO', 'SOBRETENSAO') then 'SOBRECARGA_TENSAO'
    when detalhe like 'DESCARGA ATMOSF%'                     then 'DESCARGA_ATMOSFERICA'
    when detalhe like 'ARVORE%' or detalhe like '%VEGETA%'   then 'VEGETACAO'
    when detalhe = 'VENTO'                                   then 'VENTO'
    when detalhe = 'ANIMAIS'                                 then 'ANIMAIS'
    when detalhe in ('INUNDACAO', 'EROSAO', 'POLUICAO', 'QUEIMADA', 'INCENDIO') then 'MEIO_AMBIENTE_OUTROS'
    when causa = 'TERCEIROS' or detalhe in ('VANDALISMO', 'INTERFERENCIA DE TERCEIROS') then 'TERCEIROS'
    when causa = 'FALHA OPERACIONAL' or detalhe in ('ERRO DE OPERACAO', 'SERVICO MAL EXECUTADO') then 'FALHA_OPERACIONAL'
    when detalhe like 'NAO IDENTIFICADA%' or causa = 'NAO CLASSIFICADA' or detalhe in ('NAO CLASSIFICADA', 'SEM DETALHAMENTO') then 'NAO_IDENTIFICADA'
    else 'OUTROS'
end
"""


def harmonize(paths: list[Path], sigla: str, out: Path) -> Path:
    """Une os anos num único Parquet com esquema harmonizado e métricas derivadas."""
    con = duckdb.connect()
    parts = []
    for p in paths:
        cols = {c[0] for c in con.sql(f"describe select * from read_parquet('{p}')").fetchall()}
        parts.append(_sql_novo(p, sigla) if "CodAlimentador" in cols else _sql_legado(p, sigla))
    union = "\nunion all\n".join(parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"""
    copy (
        select *,
            year(inicio)  as ano,
            month(inicio) as mes,
            date_diff('second', inicio, fim) / 3600.0 as duracao_h,
            date_diff('second', inicio, fim) / 3600.0 * uc_afetadas as chi,
            nivel_tensao_v >= 1000 and nivel_tensao_v < 69000 as origem_mt,
            {GRUPO_CAUSA_SQL} as grupo_causa
        from ({union})
        where inicio is not null and fim >= inicio
    ) to '{out}' (format parquet, compression zstd)
    """)
    n = con.sql(f"select count(*) from read_parquet('{out}')").fetchone()[0]
    log.info("%s: %d interrupções -> %s", sigla, n, out)
    return out
