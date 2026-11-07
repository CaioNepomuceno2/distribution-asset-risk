"""Quanto o vínculo de circuitos com cadastros futuros inflava o backtest?

Roda o mesmo backtest (anos 2023-2025) em dois painéis que só diferem no vínculo de circuitos:

* ``sem_cortes``: crosswalk com todos os snapshots, inclusive posteriores à previsão (versão antiga);
* ``point_in_time``: features do ano y só com snapshots até y-1.

O clima entra igual nos dois (ou fica de fora nos dois, conforme `modelo.usar_clima`).
Saída: ``reports/ablacao_point_in_time.csv``.
"""
import logging

import pandas as pd

from gridrisk import features as F
from gridrisk import model as M
from gridrisk.config import carregar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("ablacao")
cfg = carregar("Quanto o vínculo de circuitos com cadastros futuros inflava o backtest?")
ANOS_TESTE = cfg.anos_teste
ANOS = list(range(cfg.ano_inicio_painel, max(ANOS_TESTE) + 1))

clima = F.carregar_clima(cfg.interim, cfg.usar_clima)
inter = cfg.interrupcoes_parquet
cortes = F.falhas_point_in_time(inter, cfg.interim)
paineis = {
    "sem_cortes": F.build_panel(cortes[max(cortes)], cfg.interim, clima, ANOS, cfg.excluir_circuitos_vazios),
    "point_in_time": F.build_panel(cortes, cfg.interim, clima, ANOS, cfg.excluir_circuitos_vazios),
}
linhas = []
for nome, panel in paineis.items():
    for alvo in ["n_falhas", "chi"]:
        bt = M.backtest(panel, alvo, ANOS_TESTE)
        media = bt.resumo.drop(columns="ano_teste").groupby("metodo").mean(numeric_only=True)
        linhas.append(media.assign(painel=nome, alvo=alvo).reset_index())
out = pd.concat(linhas, ignore_index=True).assign(com_clima=clima is not None)
cols = ["painel", "alvo", "metodo", "com_clima"]
out = out[cols + [c for c in out.columns if c not in cols]]
cfg.reports.mkdir(parents=True, exist_ok=True)
out.to_csv(cfg.reports / "ablacao_point_in_time.csv", index=False)
print(out.round(4).to_string(index=False))
