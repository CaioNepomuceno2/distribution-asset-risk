"""Reconstrói DEC/FEC a partir das interrupções individuais e compara com o oficial da ANEEL."""
import duckdb
import pandas as pd

from gridrisk.config import ROOT, Config

cfg = Config.load()
ind = cfg.raw / "continuidade" / "indicadores-continuidade-coletivos-2020-2029.parquet"
it = cfg.interim / "interrupcoes_emt.parquet"
con = duckdb.connect()
oficial = con.sql(f"""
    pivot (select IdeConjUndConsumidoras c, AnoIndice ano, NumPeriodoIndice mes, SigIndicador s, VlrIndiceEnviado v
           from read_parquet('{ind}') where trim(SigAgente) = '{cfg.sigla}' and SigIndicador in ('DEC', 'FEC', 'NumCon'))
    on s using first(v)
""").df()
calc = con.sql(f"""
    select conjunto_id c, ano, mes, sum(chi) chi, sum(uc_afetadas) ci from read_parquet('{it}')
    where expurgo = 'NAO HOUVE EXPURGO' and duracao_h >= 3.0/60 group by all
""").df()
m = oficial.merge(calc, on=["c", "ano", "mes"], how="left").fillna({"chi": 0, "ci": 0})
linhas = []
for ano, g in m.groupby("ano"):
    uc = g.groupby("mes").NumCon.sum().mean()
    linhas.append({"ano": ano, "DEC_oficial": (g.DEC * g.NumCon).sum() / uc, "DEC_calculado": g.chi.sum() / uc,
                   "FEC_oficial": (g.FEC * g.NumCon).sum() / uc, "FEC_calculado": g.ci.sum() / uc})
out = pd.DataFrame(linhas).round(2)
out["corr_mensal_conjunto_DEC"] = round(m[["DEC"]].assign(x=m.chi / m.NumCon).corr().iloc[0, 1], 4)
out.to_csv(ROOT / "reports" / "validacao_dec_fec.csv", index=False)
print(out.to_string(index=False))
