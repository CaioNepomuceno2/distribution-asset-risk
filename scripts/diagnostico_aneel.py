"""Tabelas de diagnóstico das interrupções, da continuidade e do cadastro (ver ``docs/decisoes_ems.md``).

Grava CSV em ``<reports>/diagnostico/``: registros por mês, perfil e códigos do expurgo, linhas repetidas das
interrupções, falhas por expurgo e por grupo de causa, CHI por modo, correlação do DEC sem os meses com buraco, ISE do
pior mês, compensações por ano, circuitos vazios, elegibilidade do catálogo, cobertura do vínculo de circuitos e
comparação descritiva com outra distribuidora.

Pré-requisitos: ``build_interrupcoes.py``, ``build_bdgd.py`` e ``run_pipeline.py`` (que grava ``falhas.parquet`` e o
risco). As tabelas que leem os Parquet anuais brutos da ANEEL usam ``--interrupcoes-dir`` (padrão
``<raw>/interrupcoes``). A distribuidora de comparação (``--comparar-config``, padrão MT) é lida **só para leitura**: os
Parquet publicados de ``app/data`` e, se existirem, os intermediários de ``interim`` (o vínculo de circuitos usa uma cópia
temporária, para não gravar crosswalks na pasta dela). Nada é gravado fora de ``<reports>/diagnostico/``.
"""
import logging
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from gridrisk import otimizacao as O
from gridrisk.config import CONFIG_PADRAO, Config, parser
from gridrisk.ingest import diagnostico_aneel as D
from gridrisk.ingest.diagnostico_vinculo import cobertura_vinculo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("diagnostico_aneel")
ap = parser("Tabelas de diagnóstico das interrupções, da continuidade e do cadastro.")
ap.add_argument("--interrupcoes-dir", type=Path, default=None, help="pasta com os Parquet anuais de interrupções")
ap.add_argument("--comparar-config", type=Path, default=CONFIG_PADRAO,
                help="configuração da distribuidora de comparação (leitura apenas; padrão configs/emt.yaml)")
args = ap.parse_args()
cfg = Config.load(args.config)
ref = Config.load(args.comparar_config)
comparar = ref.sigla != cfg.sigla
saida = cfg.reports / "diagnostico"
saida.mkdir(parents=True, exist_ok=True)
dir_int = args.interrupcoes_dir or cfg.raw / "interrupcoes"
ind = cfg.raw / "continuidade" / "indicadores-continuidade-coletivos-2020-2029.parquet"
comp = cfg.raw / "continuidade" / "indicadores-continuidade-coletivos-compensacao-2020-2029.parquet"
anos_brutos = [a for a in cfg.anos_interrupcoes if (dir_int / f"interrupcoes-energia-eletrica-{a}.parquet").exists()]
distribuidoras = [cfg, ref] if comparar else [cfg]


def gravar(nome: str, tabela: pd.DataFrame) -> None:
    tabela.to_csv(saida / nome, index=False, float_format="%.10g")
    log.info("%s: %d linhas", nome, len(tabela))


def por_distribuidora(funcao, quando=lambda c: True) -> pd.DataFrame:
    """Aplica ``funcao(c)`` a cada distribuidora com os arquivos disponíveis e empilha, com a coluna ``distribuidora``."""
    partes = [funcao(c).assign(distribuidora=c.sigla) for c in distribuidoras if quando(c)]
    t = pd.concat(partes, ignore_index=True)
    return t[["distribuidora", *[c for c in t.columns if c != "distribuidora"]]]


# ---- interrupções (as da distribuidora de comparação só entram se os intermediários dela existirem)
gravar("interrupcoes_por_mes.csv", por_distribuidora(lambda c: D.interrupcoes_por_mes(c.interrupcoes_parquet),
                                                     lambda c: c.interrupcoes_parquet.exists()))
if anos_brutos:
    gravar("expurgo_perfil.csv", D.perfil_expurgo(dir_int, cfg.sigla, cfg.anos_teste[-1], cfg.ano_previsao))
    legado = [a for a in anos_brutos if a < cfg.ano_previsao]
    gravar("expurgo_codigos_por_ano.csv", por_distribuidora(lambda c: D.codigos_expurgo_por_ano(dir_int, c.sigla, legado)))
    gravar("duplicatas_interrupcoes.csv",
           por_distribuidora(lambda c: D.duplicatas_interrupcoes(dir_int, c.sigla, anos_brutos)))
else:
    log.warning("sem os Parquet brutos de interrupções em %s: expurgo e duplicatas não gerados", dir_int)
gravar("falhas_por_expurgo.csv", D.falhas_por_expurgo(cfg.interrupcoes_parquet))
gravar("falhas_por_grupo_causa.csv", D.falhas_por_grupo_causa(cfg.interrupcoes_parquet))
gravar("chi_por_modo.csv",
       D.chi_por_modo(pd.read_parquet(cfg.interim / "falhas.parquet"), min(cfg.anos_teste), max(cfg.anos_teste)))

# ---- DEC, compensações e conjuntos
gravar("dec_correlacao.csv", D.dec_sem_buracos(ind, cfg.interrupcoes_parquet, cfg.sigla))
ano, mes = D.mes_de_menor_razao(ind, cfg.interrupcoes_parquet, cfg.sigla)
gravar("ise_mes_menor_razao.csv", D.ise_acima_de_limite(ind, cfg.interrupcoes_parquet, cfg.sigla, ano, mes))
gravar("compensacoes_por_ano.csv", D.compensacoes_por_ano(comp, cfg.sigla))
gravar("conjuntos_compensacao.csv", D.conjuntos_compensacao(comp, cfg.interrupcoes_parquet, cfg.sigla))

# ---- cadastro e vínculo de circuitos
gravar("circuitos_vazios.csv", por_distribuidora(lambda c: D.circuitos_vazios(c.interim),
                                                 lambda c: any(c.interim.glob("bdgd_feeders_*.parquet"))))
fin, catalogo = O.carregar_catalogo(cfg.catalogo)
tabelas = {}
for c in distribuidoras:
    arq = c.interim / f"bdgd_feeders_{max(c.bdgd_snapshots)}.parquet"
    if arq.exists():
        tabelas[c.sigla] = D.elegibilidade(pd.read_parquet(arq), catalogo).set_index("intervencao")
    else:
        log.warning("sem %s: elegibilidade de %s não calculada", arq, c.sigla)
elegibilidade = pd.concat(tabelas, axis=1)
elegibilidade.columns = [f"{a}_{b}" for a, b in elegibilidade.columns]
gravar("elegibilidade_catalogo.csv", elegibilidade.reset_index())


def vinculo(c: Config) -> pd.DataFrame:
    with tempfile.TemporaryDirectory() as tmp:  # cópia: o vínculo grava crosswalks e não gravamos na pasta de ``c``
        for p in [*c.interim.glob("bdgd_map_*.parquet"), *c.interim.glob("bdgd_feeders_*.parquet")]:
            shutil.copy(p, tmp)
        return cobertura_vinculo(c.interrupcoes_parquet, Path(tmp))


gravar("vinculo_circuitos_comparacao.csv", por_distribuidora(
    vinculo, lambda c: c.interrupcoes_parquet.exists() and any(c.interim.glob("bdgd_map_*.parquet"))))

# ---- comparação descritiva (MT vem dos Parquet publicados em app/data)
riscos = {cfg.sigla: pd.read_parquet(cfg.processed / "risco_alimentador.parquet")}
if comparar and (ref.app_data / "risco_alimentador.parquet").exists():
    riscos[ref.sigla] = pd.read_parquet(ref.app_data / "risco_alimentador.parquet")
gravar("comparacao_descritiva.csv", D.comparacao_descritiva(riscos))
