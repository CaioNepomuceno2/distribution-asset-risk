"""Cobertura do vínculo interrupção -> circuito da BDGD, por ano de evento e por corte temporal.

Pré-requisitos: ``build_interrupcoes.py`` e ``build_bdgd.py``. Saída: ``<reports>/diagnostico/vinculo_circuitos.csv``.
"""
from gridrisk.config import carregar
from gridrisk.ingest.diagnostico_vinculo import cobertura_vinculo

cfg = carregar("Cobertura do vínculo interrupção -> circuito da BDGD.")
tabela = cobertura_vinculo(cfg.interrupcoes_parquet, cfg.interim)
destino = cfg.reports / "diagnostico"
destino.mkdir(parents=True, exist_ok=True)
tabela.round(3).to_csv(destino / "vinculo_circuitos.csv", index=False)
print(tabela[tabela.escopo == "falhas"].round(2).to_string(index=False))
