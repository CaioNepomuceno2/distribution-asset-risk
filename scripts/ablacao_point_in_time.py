"""Quanto o vínculo de circuitos com cadastros futuros inflava o backtest?

Roda o mesmo backtest (anos 2023-2025) em dois painéis que só diferem no vínculo de circuitos:

* ``sem_cortes``: crosswalk com todos os snapshots, inclusive posteriores à previsão (versão antiga);
* ``point_in_time``: features do ano y só com snapshots até y-1.

O clima entra igual nos dois (ou fica de fora nos dois, se não houver o arquivo do INMET).
Saída: ``reports/ablacao_point_in_time.csv``.
"""
import logging

import pandas as pd

from gridrisk import features as F
from gridrisk import model as M
from gridrisk.config import ROOT, Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("ablacao")
cfg = Config.load()
ANOS_TESTE = [2023, 2024, 2025]
ANOS = list(range(2019, max(ANOS_TESTE) + 1))

clima_path = cfg.interim / "clima_alimentador_mes.parquet"
clima = pd.read_parquet(clima_path) if clima_path.exists() else None
inter = cfg.interim / "interrupcoes_emt.parquet"
cortes = F.falhas_point_in_time(inter, cfg.interim)
paineis = {
    "sem_cortes": F.build_panel(cortes[max(cortes)], cfg.interim, clima, ANOS),
    "point_in_time": F.build_panel(cortes, cfg.interim, clima, ANOS),
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
out.to_csv(ROOT / "reports" / "ablacao_point_in_time.csv", index=False)
print(out.round(4).to_string(index=False))
