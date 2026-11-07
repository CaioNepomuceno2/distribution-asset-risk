"""Reconstrói DEC/FEC a partir das interrupções individuais e compara com o oficial da ANEEL.

Com ``--alinhar-meses``, cada ano só compara os meses que existem nas interrupções (o arquivo de indicadores da
ANEEL pode ir mais longe que o de interrupções no ano corrente). Sem a opção, o comportamento é o publicado para MT.
"""
import duckdb
import pandas as pd

from gridrisk.config import Config, parser
from gridrisk.ingest.continuidade import dec_fec_oficial

ap = parser("Reconstrói DEC/FEC a partir das interrupções e compara com o oficial da ANEEL.")
ap.add_argument("--alinhar-meses", action="store_true",
                help="compara só os meses presentes nas interrupções de cada ano")
args = ap.parse_args()
cfg = Config.load(args.config)
ind = cfg.raw / "continuidade" / "indicadores-continuidade-coletivos-2020-2029.parquet"
it = cfg.interrupcoes_parquet
con = duckdb.connect()
oficial = dec_fec_oficial(ind, cfg.sigla)  # lê sem as linhas repetidas do arquivo da ANEEL
if args.alinhar_meses:
    ate = con.sql(f"select ano, max(mes) as mes_max from read_parquet('{it}') group by ano").df()
    oficial = oficial.merge(ate, on="ano").query("mes <= mes_max").drop(columns="mes_max")
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
cfg.reports.mkdir(parents=True, exist_ok=True)
out.to_csv(cfg.reports / "validacao_dec_fec.csv", index=False)
print(out.to_string(index=False))
