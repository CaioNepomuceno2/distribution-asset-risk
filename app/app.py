"""Painel de gestão de ativos baseada em risco: Energisa MT.

    streamlit run app/app.py
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from gridrisk.otimizacao import guloso, otimizar, priorizacao_tradicional

DATA = Path(__file__).parent / "data"
MODOS = {"EQUIPAMENTO": "Equipamento", "DESCARGA_ATMOSFERICA": "Descarga atmosférica", "VEGETACAO": "Vegetação",
         "VENTO": "Vento", "ANIMAIS": "Animais", "TERCEIROS": "Terceiros", "OUTRAS": "Outras"}
CENARIOS = {"social": "Social (compensação + energia não suprida)", "compensacao": "Caixa (só compensações)"}

FMT = {
    "capex": st.column_config.NumberColumn("capex (R$)", format="%.0f"),
    "opex_ano": st.column_config.NumberColumn("opex (R$/ano)", format="%.0f"),
    "chi_evitado_ano": st.column_config.NumberColumn("CHI evitado/ano", format="%.0f"),
    "vpl": st.column_config.NumberColumn("VPL (R$)", format="%.0f"),
    "chi_previsto": st.column_config.NumberColumn("CHI previsto", format="%.0f"),
    "chi_historico_3a": st.column_config.NumberColumn("CHI médio 3a", format="%.0f"),
    "rede_mt_km": st.column_config.NumberColumn("rede MT (km)", format="%.0f"),
    "risco_rs_ano": st.column_config.NumberColumn("risco (R$/ano)", format="%.0f"),
}

st.set_page_config(page_title="Risco de ativos | Energisa MT", page_icon="⚡", layout="wide")


@st.cache_data
def carregar():
    risco = pd.read_parquet(DATA / "risco_alimentador.parquet")
    prev = pd.read_parquet(DATA / "previsao_2026.parquet")
    cands = {c: pd.read_parquet(DATA / f"candidatos_{c}.parquet") for c in CENARIOS}
    return risco, prev, cands


def brl(v: float) -> str:
    if abs(v) >= 1e6:
        return f"R$ {v / 1e6:,.1f} mi".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {v / 1e3:,.0f} mil".replace(",", ".")


risco, prev, cands = carregar()
n_uc = int(risco.n_uc.sum())

st.title("Gestão de ativos baseada em risco — Energisa Mato Grosso")
st.caption("Dados abertos ANEEL (interrupções, BDGD, compensações) e INMET. Previsão para 2026 com modelos "
           "treinados até 2025. Custos e eficácias das intervenções são premissas ilustrativas (configs/).")

c1, c2, c3 = st.columns([1, 1, 2])
cenario = c1.radio("Visão de valor", list(CENARIOS), format_func=CENARIOS.get)
orcamento = c2.slider("Orçamento (R$ milhões)", 1, 80, 20) * 1e6
col_risco = f"risco_rs_{cenario}"

k1, k2, k3, k4 = st.columns(4)
k1.metric("Alimentadores", f"{len(risco):,}".replace(",", "."))
k2.metric("CHI previsto 2026", f"{risco.chi_previsto.sum() / 1e6:,.1f} mi".replace(".", ","))
k3.metric("DEC por falhas MT (previsto)", f"{risco.dec_contribuicao_h.sum():.1f} h".replace(".", ","))
k4.metric("Risco anual", brl(risco[col_risco].sum()))

tab_mapa, tab_carteira, tab_alim = st.tabs(["Mapa de risco", "Carteira de investimento", "Alimentador"])

with tab_mapa:
    d = risco.dropna(subset=["lat"]).copy()
    d["modo"] = d.modo_dominante.map(MODOS)
    fig = px.scatter_map(d, lat="lat", lon="lon", size="n_uc", color=col_risco, size_max=22, zoom=5.4,
                         center={"lat": float(d.lat.mean()), "lon": float(d.lon.mean())},
                         color_continuous_scale=["#9ec5f4", "#3987e5", "#184f95", "#0d366b"], hover_name="alimentador",
                         hover_data={"chi_previsto": ":,.0f", "modo": True, "rede_mt_km": ":,.0f",
                                     col_risco: ":,.0f", "lat": False, "lon": False},
                         map_style="carto-positron", height=620)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0}, coloraxis_colorbar_title="R$/ano")
    st.plotly_chart(fig, use_container_width=True)
    top = risco.sort_values(col_risco, ascending=False).head(25)
    st.subheader("25 alimentadores de maior risco")
    st.dataframe(top[["alimentador", "subestacao_bdgd", "n_uc", "rede_mt_km", "chi_previsto", "chi_historico_3a",
                      "modo_dominante", col_risco]].rename(columns={col_risco: "risco_rs_ano"}),
                 hide_index=True, use_container_width=True, column_config=FMT)

with tab_carteira:
    c = cands[cenario]
    hist = risco.set_index("alimentador").chi_historico_3a
    sel = {"Ótima (MILP)": otimizar(c, orcamento), "Gulosa (VPL/custo)": guloso(c, orcamento),
           "Tradicional (pior primeiro)": priorizacao_tradicional(c, hist, orcamento)}
    resumo = pd.DataFrame([{"método": k, "investido": brl(v.custo_inicial.sum()), "alimentadores": len(v),
                            "DEC evitado (h)": round(v.chi_reg_evitado_ano.sum() / n_uc, 2),
                            "VPL 10 anos": brl(v.vpl.sum())} for k, v in sel.items()])
    st.dataframe(resumo, hide_index=True, use_container_width=True)
    otima = sel["Ótima (MILP)"]
    mix = otima.pacote.str.split("+").explode().value_counts().rename_axis("intervenção").reset_index()
    a, b = st.columns([1, 2])
    a.subheader("Mix de intervenções")
    a.dataframe(mix, hide_index=True, use_container_width=True)
    b.subheader("Carteira ótima")
    b.dataframe(otima[["alimentador", "pacote", "capex", "opex_ano", "chi_evitado_ano", "vpl"]],
                hide_index=True, use_container_width=True, column_config=FMT)
    st.download_button("Baixar carteira (CSV)", otima.to_csv(index=False).encode(), "carteira_otima.csv")

with tab_alim:
    alim = st.selectbox("Alimentador", risco.sort_values(col_risco, ascending=False).alimentador)
    r = risco.set_index("alimentador").loc[alim]
    a, b, cc = st.columns(3)
    a.metric("CHI previsto 2026", f"{r.chi_previsto:,.0f}".replace(",", "."))
    b.metric("CHI médio 2023-2025", f"{r.chi_historico_3a:,.0f}".replace(",", "."))
    cc.metric("Risco anual", brl(r[col_risco]))
    p = prev[prev.alimentador == alim].assign(modo=lambda x: x.modo.astype(str).map(MODOS))
    fig = px.bar(p.sort_values("pred_chi"), x="pred_chi", y="modo", orientation="h",
                 labels={"pred_chi": "CHI previsto 2026", "modo": ""}, color_discrete_sequence=["#2a78d6"])
    fig.update_traces(marker_cornerradius=4)
    fig.update_layout(bargap=0.45)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(cands[cenario][cands[cenario].alimentador == alim].sort_values("vpl", ascending=False)
                 [["pacote", "capex", "opex_ano", "chi_evitado_ano", "vpl"]], hide_index=True,
                 use_container_width=True, column_config=FMT)
