"""Fixtures compartilhadas: uma BDGD sintética minúscula, no estilo de Mato Grosso do Sul.

Os códigos de alimentador de MS são alfanuméricos de 5 caracteres (``AJO51``), e não os 6 dígitos de MT (``013014``).
O arquivo é um GeoPackage com as camadas e os campos que o extrator lê; o File Geodatabase real é só leitura, mas o
extrator usa o GDAL, que lê os dois do mesmo jeito.
"""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

CTMT = pd.DataFrame({
    "COD_ID": ["9001", "9002"], "NOME": ["AJO51", "MIM01"], "SUB": ["S1", "S2"], "TEN_NOM": ["49", "72"],
    **{f"ENE_{m:02d}": [1000.0, 2000.0] for m in range(1, 13)}})
SSDMT = pd.DataFrame({
    "CTMT": ["9001", "9001", "9002"], "CT_COD_OP": ["AJO51", "AJO52", "MIM01"], "ARE_LOC": ["NU", "UB", "NU"],
    "TIP_CND": ["C1", "C2", "C1"], "FAS_CON": ["ABC", "A", "AB"], "COMP": [1000.0, 500.0, 2000.0]})
SEGCON = pd.DataFrame({"COD_ID": ["C1", "C2"], "GEOM_CAB": ["3", "1"], "ISO_FAS_1": ["12", "17"], "MAT_FAS_1": ["1", "1"]})
UNSEMT = pd.DataFrame({
    "COD_ID": ["S1", "S2", "S3", "S4"], "CTMT": ["9001", "9001", "9001", "9002"], "TIP_UNID": ["32", "22", "19", "32"],
    "TLCD": ["1", "0", "0", "0"], "DAT_CON": ["01/06/2012", "01/01/1980", "05/05/2015", "10/10/2020"],
    "PAC_1": ["42721345758317862MT", "40773811759956094MT", "123456789", "42721345758317863MT"],
    "CAP_ELO": ["", "25K", "25K", ""], "COR_NOM": [35.0, 12.0, 35.0, 35.0]})
EQSE = pd.DataFrame({"UN_SE": ["S1", "S2", "S3", "S9"], "TUC": ["345", "000", "160", "000"],
                     "DAT_IMO": ["01/01/2012", None, "05/05/2015", "01/01/2000"]})
UCBT = pd.DataFrame({"CTMT": ["9001", "9001", "9002"], "CLAS_SUB": ["RE1", "RU1", "RE1"]})
UCMT = pd.DataFrame({"CTMT": ["9002"]})
UGBT = pd.DataFrame({"CTMT": ["9001"], "POT_INST": [5.0]})
UGMT = pd.DataFrame({"CTMT": ["9002"], "POT_INST": [100.0]})
# três trafos dentro de MS (SIRGAS 2000, lon/lat)
UNTRMT = gpd.GeoDataFrame({
    "CTMT": ["9001", "9001", "9002"], "POT_NOM": [75.0, 45.0, 30.0], "DAT_CON": ["01/01/2010", "01/01/1980", "15/06/2018"],
    "MRT": [0, 0, 1]}, geometry=[Point(-54.6, -20.5), Point(-54.7, -20.6), Point(-55.0, -21.0)], crs=4674)


@pytest.fixture(scope="session")
def gdb_ms(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("bdgd") / "Energisa_MS_404_2025-12-31_sintetico.gpkg"
    for nome, tabela in {"CTMT": CTMT, "SSDMT": SSDMT, "SEGCON": SEGCON, "UNSEMT": UNSEMT, "EQSE": EQSE,
                         "UCBT_tab": UCBT, "UCMT_tab": UCMT, "UGBT_tab": UGBT, "UGMT_tab": UGMT}.items():
        gpd.GeoDataFrame(tabela, geometry=[None] * len(tabela), crs=4674).to_file(caminho, layer=nome, driver="GPKG")
    UNTRMT.to_file(caminho, layer="UNTRMT", driver="GPKG")
    return caminho
