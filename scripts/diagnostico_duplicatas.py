"""Linhas repetidas nos arquivos da ANEEL que o pipeline lê (interrupções e continuidade).

Para cada arquivo: ``count(*)`` contra ``count(distinct *)`` da distribuidora configurada (e do arquivo inteiro, nos
de continuidade), mais o número de chaves com valores diferentes depois do ``distinct``. Saída:
``<reports>/diagnostico/duplicatas_aneel.csv``. As interrupções podem estar fora de ``raw`` (por exemplo, num cache
compartilhado): use ``--interrupcoes-dir``.
"""
from pathlib import Path

import pandas as pd

from gridrisk.config import Config, parser
from gridrisk.ingest import duplicatas

ap = parser("Diagnóstico de linhas repetidas nos arquivos da ANEEL.")
ap.add_argument("--interrupcoes-dir", type=Path, default=None, help="pasta com os Parquet anuais de interrupções")
ap.add_argument("--continuidade-dir", type=Path, default=None, help="pasta com os Parquet de continuidade")
args = ap.parse_args()
cfg = Config.load(args.config)
dir_int = args.interrupcoes_dir or cfg.raw / "interrupcoes"
dir_con = args.continuidade_dir or cfg.raw / "continuidade"

linhas = []
for ano in cfg.anos_interrupcoes:
    p = dir_int / f"interrupcoes-energia-eletrica-{ano}.parquet"
    linhas.append(duplicatas.contar(p, cfg.sigla))
for nome, chave, valor in [
        ("indicadores-continuidade-coletivos-2020-2029.parquet",
         ["SigAgente", "IdeConjUndConsumidoras", "SigIndicador", "AnoIndice", "NumPeriodoIndice"], "VlrIndiceEnviado"),
        ("indicadores-continuidade-coletivos-compensacao-2020-2029.parquet",
         ["SigAgente", "IdeConjUndConsumidoras", "SigIndicador", "AnoIndice", "NumPeriodoIndice"], "VlrIndiceEnviado")]:
    p = dir_con / nome
    for sigla in (cfg.sigla, None):
        r = duplicatas.contar(p, sigla)
        r["chaves_com_valores_diferentes"] = duplicatas.chaves_com_valores_diferentes(p, chave, valor, sigla)
        linhas.append(r)
out = pd.DataFrame(linhas)
destino = cfg.reports / "diagnostico"
destino.mkdir(parents=True, exist_ok=True)
out.to_csv(destino / "duplicatas_aneel.csv", index=False)
print(out.round(4).to_string(index=False))
