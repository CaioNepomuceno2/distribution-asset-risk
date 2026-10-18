import numpy as np
import pandas as pd

from gridrisk.ingest import inmet

CSV = """REGIÃO:;CO
UF:;MT
ESTAÇÃO:;CUIABA
CODIGO (WMO):;A901
LATITUDE:;-15,55916666
LONGITUDE:;-56,72944443
ALTITUDE:;240
DATA DE FUNDAÇÃO (YYYY-MM-DD):;2002-12-08
DATA (YYYY-MM-DD);HORA (UTC);PRECIPITAÇÃO TOTAL, HORÁRIO (mm);TEMPERATURA DO AR - BULBO SECO, HORARIA (°C);UMIDADE RELATIVA DO AR, HORARIA (%);VENTO, RAJADA MAXIMA (m/s);VENTO, VELOCIDADE HORARIA (m/s);
2018-01-01;00:00;-9999;25,1;80;5,2;1,1;
2018-01-01;01:00;12,4;24,0;90;16,0;3,0;
"""


def test_parse_station():
    meta, df = inmet._parse_station(CSV.encode("latin-1"))
    assert meta["CODIGO (WMO)"] == "A901"
    assert np.isnan(df.precip_mm.iloc[0])
    assert df.precip_mm.iloc[1] == 12.4
    assert df.rajada_ms.max() == 16.0
    assert df.ts.iloc[1] == pd.Timestamp("2018-01-01 01:00")


def test_idw_prefere_estacao_proxima():
    clima = pd.DataFrame({"ano": [2020, 2020], "mes": [1, 1], "estacao": ["A", "B"],
                          "precip_total_mm": [100.0, 300.0], "cobertura_horas": [1.0, 1.0]})
    est = pd.DataFrame({"estacao": ["A", "B"], "lat": [-15.0, -10.0], "lon": [-56.0, -56.0]})
    feeders = pd.DataFrame({"alimentador_cod_id": ["f"], "lat": [-14.9], "lon": [-56.0]})
    out = inmet.idw_to_feeders(clima, est, feeders, k=2, max_km=1000)
    assert 100 < out.precip_total_mm.iloc[0] < 110
