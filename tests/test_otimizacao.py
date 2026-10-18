import pandas as pd

from gridrisk import otimizacao as O
from gridrisk.features import MODOS


def _cands():
    # alimentador A: dois pacotes alternativos; B: um pacote caro
    return pd.DataFrame([
        {"alimentador": "A", "pacote": "religador", "n_itens": 1, "custo_inicial": 100, "vpl": 50,
         "chi_evitado_ano": 10, "chi_reg_evitado_ano": 8},
        {"alimentador": "A", "pacote": "religador+automacao", "n_itens": 2, "custo_inicial": 180, "vpl": 80,
         "chi_evitado_ano": 18, "chi_reg_evitado_ano": 14},
        {"alimentador": "B", "pacote": "automacao", "n_itens": 1, "custo_inicial": 150, "vpl": 70,
         "chi_evitado_ano": 12, "chi_reg_evitado_ano": 9},
    ])


def test_otimizar_respeita_orcamento_e_escolha_unica():
    sel = O.otimizar(_cands(), orcamento=250)
    assert sel.custo_inicial.sum() <= 250
    assert sel.alimentador.is_unique
    # melhor combinação viável: religador em A (50) + automação em B (70) = 120 > 80 sozinho
    assert sel.vpl.sum() == 120


def test_pacotes_combinam_eficacia_multiplicativa():
    itv = O.Intervencao("x", "", "capex", 100.0, "1", "1", 10, 1.0, {"todos": 0.5})
    feeders = pd.DataFrame({"rede_mt_km": [10.0]}, index=["A"])
    chi = pd.DataFrame([[100.0] * len(MODOS)], index=["A"], columns=MODOS)
    fin = {"taxa_desconto": 0.08, "horizonte_anos": 10}
    c = O.pacotes(feeders, chi, pd.Series({"A": 1.0}), [itv, O.Intervencao("y", "", "opex", 1.0, "1", "1", 1, 1.0,
                                                                         {"todos": 0.5})], fin)
    combo = c[c.pacote == "x+y"].iloc[0]
    assert abs(combo.chi_evitado_ano - 0.75 * 100 * len(MODOS)) < 1e-6  # 1 - 0.5*0.5
