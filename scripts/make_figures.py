"""Figuras estáticas para o README e para divulgação (reports/figures/*.png)."""
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from gridrisk.config import ROOT, Config

cfg = Config.load()
REP = ROOT / "reports"
FIG = REP / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# paleta de referência (validada: 3 primeiros slots passam CVD em todos os pares)
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
NOME_METODO = {"modelo": "Modelo (LightGBM)", "media_3a": "Média de 3 anos", "ano_anterior": "Ano anterior",
               "otimo": "Carteira ótima (MILP)", "guloso": "Guloso (VPL/custo)",
               "tradicional": "Pior primeiro + pacote padrão"}
COR_METODO = {"modelo": S1, "otimo": S1, "media_3a": S2, "guloso": S3, "ano_anterior": S3, "tradicional": S2}
NOME_MODO = {"EQUIPAMENTO": "Falha de equipamento", "VENTO": "Vento", "DESCARGA_ATMOSFERICA": "Descarga atmosférica",
             "VEGETACAO": "Vegetação", "OUTRAS": "Outras / não identificada", "TERCEIROS": "Terceiros",
             "ANIMAIS": "Animais"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "axes.spines.top": False,
    "axes.spines.right": False, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "axes.titlelocation": "left", "legend.frameon": False, "legend.labelcolor": INK2,
})
mil = FuncFormatter(lambda v, _: f"{v / 1e3:,.0f} mil".replace(",", "."))
mi = FuncFormatter(lambda v, _: f"R$ {v / 1e6:,.0f} mi".replace(",", "."))


def salvar(fig, nome):
    fig.savefig(FIG / nome, dpi=180, bbox_inches="tight")
    plt.close(fig)


# 1) backtest -----------------------------------------------------------------
bt = pd.read_csv(REP / "backtest_media.csv")
fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
for ax, (alvo, metrica, titulo, fmt) in zip(axes, [
        ("n_falhas", "deviance_poisson", "Deviance de Poisson (nº de falhas)\nmenor é melhor", "{:.1f}"),
        ("chi", "mae_alimentador", "Erro absoluto médio do CHI por alimentador\nmenor é melhor", "{:,.0f}")]):
    d = bt[bt.alvo == alvo].set_index("metodo").loc[["modelo", "media_3a", "ano_anterior"]]
    y = np.arange(len(d))
    ax.barh(y, d[metrica], height=0.5, color=[COR_METODO[m] for m in d.index])
    ax.set_yticks(y, [NOME_METODO[m] for m in d.index], color=INK2)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_title(titulo, fontsize=10.5)
    for yi, v in zip(y, d[metrica], strict=True):
        ax.text(v, yi, "  " + fmt.format(v).replace(",", "."), va="center", color=INK, fontsize=9.5)
    ax.set_xlim(0, d[metrica].max() * 1.25)
    if alvo == "chi":
        ax.xaxis.set_major_formatter(mil)
        ax.xaxis.set_major_locator(plt.MaxNLocator(4))
fig.suptitle("Backtest temporal 2023-2025 (treino só com anos anteriores)", x=0.01, ha="left",
             color=INK, fontweight="bold", y=1.04)
salvar(fig, "01_backtest.png")

# 2) fronteira de investimento -------------------------------------------------
for cen, rotulo in [("social", "visão social (compensação + energia não suprida)"),
                    ("compensacao", "visão de caixa (só compensações)")]:
    fr = pd.read_csv(REP / f"fronteira_{cen}.csv")
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    for m in ["otimo", "guloso", "tradicional"]:
        d = fr[fr.metodo == m]
        ax.plot(d.orcamento, d.vpl, color=COR_METODO[m], lw=2, marker="o", ms=6,
                mec=SURFACE, mew=2, label=NOME_METODO[m])
    ax.axhline(0, color=AXIS, lw=1)
    ax.xaxis.set_major_formatter(mi)
    ax.yaxis.set_major_formatter(mi)
    ax.set_xlabel("Orçamento de investimento")
    ax.set_ylabel("VPL da carteira (10 anos, 8% a.a.)")
    ax.set_title(f"Mesmo orçamento, mais valor: carteira otimizada vs. priorização tradicional\n{rotulo}",
                 fontsize=11)
    ax.legend(loc="upper left")
    salvar(fig, f"02_fronteira_{cen}.png")

# 3) CHI por modo de falha -----------------------------------------------------
fal = pd.read_parquet(cfg.interim / "falhas.parquet")
m = fal[fal.ano.between(2023, 2025)].groupby("modo")[["chi", "chi_regulatorio"]].sum() / 3
m = m.sort_values("chi")
fig, ax = plt.subplots(figsize=(8, 3.8))
y = np.arange(len(m))
ax.barh(y, m.chi_regulatorio, height=0.55, color=SEQ[5], label="CHI regulatório (entra no DEC)")
gap = m.chi.max() * 0.004  # 2px de superfície entre os segmentos
ax.barh(y, m.chi - m.chi_regulatorio - gap, left=m.chi_regulatorio + gap, height=0.55, color=SEQ[2],
        label="CHI expurgado (dia crítico, emergência)")
ax.set_yticks(y, [NOME_MODO[i] for i in m.index], color=INK2)
ax.grid(axis="y", visible=False)
ax.xaxis.set_major_formatter(mil)
for yi, c in enumerate(m.chi):
    ax.text(c, yi, f"  {c / 1e6:.1f} mi".replace(".", ","), va="center", color=INK, fontsize=9)
ax.set_xlim(0, m.chi.max() * 1.18)
ax.set_xlabel("Consumidor-hora interrompido por ano (média 2023-2025)")
ax.set_title("Falhas na média tensão da Energisa MT por modo de falha")
ax.legend(loc="lower right")
salvar(fig, "03_chi_por_modo.png")

# 4) SHAP ----------------------------------------------------------------------
NOMES = {
    "chi_media_3a": "CHI médio 3 anos (mesmo modo)", "chi_media_1a": "CHI do ano anterior (mesmo modo)",
    "n_falhas_media_3a": "Falhas/ano 3 anos (mesmo modo)", "chi_total_media_3a": "CHI total médio 3 anos",
    "modo": "Modo de falha", "n_uc": "Nº de consumidores", "rede_mt_km": "Extensão da rede MT (km)",
    "duracao_mediana_3a_h": "Duração mediana de restabelecimento", "n_falhas_media_1a": "Falhas no ano anterior",
    "uc_por_km": "Consumidores por km", "frac_rural": "Fração rural da rede", "lat": "Latitude",
    "lon": "Longitude", "extensao_km": "Extensão geográfica (km)", "n_falhas_total_media_3a": "Falhas totais 3 anos",
    "frac_compacta": "Fração de rede compacta", "frac_cabo_nu": "Fração de cabo nu",
    "n_chaves_fusiveis": "Nº de chaves fusíveis", "n_trafos": "Nº de transformadores",
    "tendencia_falhas_total": "Tendência de falhas", "kva_instalado_mva": "Potência instalada (MVA)",
    "religadores_por_100km": "Religadores por 100 km", "n_religadores": "Nº de religadores",
    "frac_monofasica": "Fração monofásica", "energia_mwh_ano": "Energia (MWh/ano)", "gd_mw": "Geração distribuída (MW)",
    "fusiveis_por_km": "Chaves fusíveis por km", "n_segmentos_mt": "Nº de segmentos MT",
    "clim_dias_rajada_15ms_ano": "Clima: dias com rajada > 15 m/s", "kva_mediano": "Potência mediana do trafo (kVA)",
    "frac_uc_rurais": "Fração de consumidores rurais", "clim_dist_estacao_km": "Distância à estação INMET",
    "frac_trafos_mrt": "Fração de trafos MRT", "carga_media_mw": "Carga média (MW)", "clim_precip_anual_mm": "Clima: chuva anual",
}
imp = pd.read_csv(REP / "shap_importancia_chi.csv", index_col=0).iloc[:, 0].head(15)[::-1]
fig, ax = plt.subplots(figsize=(8, 5))
ax.barh(np.arange(len(imp)), imp.values, height=0.55, color=S1)
ax.set_yticks(np.arange(len(imp)), [NOMES.get(i, i) for i in imp.index], color=INK2)
ax.grid(axis="y", visible=False)
ax.set_xlabel("|SHAP| médio no CHI previsto (log)")
ax.set_title("O que mais pesa na previsão de CHI por alimentador")
salvar(fig, "04_shap.png")

# 5) mapa de risco -------------------------------------------------------------
rk = pd.read_parquet(cfg.processed / "risco_alimentador.parquet").dropna(subset=["lat"])
rk = rk.sort_values("risco_rs_social")
fig, ax = plt.subplots(figsize=(7, 7.5))
uf = json.loads((ROOT / "data" / "ref" / "mt_ibge.geojson").read_text())  # malha IBGE de MT
for feat in uf["features"]:
    geom = feat["geometry"]
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        xy = np.array(poly[0])
        ax.fill(xy[:, 0], xy[:, 1], color="#f0efec", ec=AXIS, lw=1, zorder=1)
ax.grid(False)
q = pd.qcut(rk.risco_rs_social.rank(method="first"), 5, labels=False)
cores = [SEQ[i] for i in [0, 2, 3, 5, 6]]
rot = ["1º quintil (menor risco)", "2º quintil", "3º quintil", "4º quintil", "5º quintil (maior risco)"]
for k in range(5):
    d = rk[q == k]
    ax.scatter(d.lon, d.lat, s=8 + 60 * np.sqrt(d.n_uc / rk.n_uc.max()), color=cores[k], ec=SURFACE, lw=0.6,
               label=rot[k], zorder=2 + k)
ax.set_aspect(1 / np.cos(np.radians(rk.lat.mean())))
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_title("Risco previsto para 2026 por alimentador (R$/ano)\ntamanho = nº de consumidores")
ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), markerscale=1.2)
for _, r in rk.tail(3).iterrows():
    ax.annotate(f"alimentador {r.alimentador}", (r.lon, r.lat), xytext=(10, 10), textcoords="offset points",
                color=INK, fontsize=8.5, zorder=10, arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.8},
                bbox={"boxstyle": "round,pad=0.2", "fc": SURFACE, "ec": "none", "alpha": 0.9})
salvar(fig, "05_mapa_risco.png")

# 6) calibração ----------------------------------------------------------------
cal = pd.read_csv(REP / "calibracao_chi.csv")
fig, ax = plt.subplots(figsize=(5, 4.6))
lim = [0, max(cal.previsto.max(), cal.observado.max()) * 1.08]
ax.plot(lim, lim, color=AXIS, lw=1)
ax.plot(cal.previsto, cal.observado, color=S1, lw=2, marker="o", ms=7, mec=SURFACE, mew=2)
ax.xaxis.set_major_formatter(mil)
ax.yaxis.set_major_formatter(mil)
ax.xaxis.set_major_locator(plt.MaxNLocator(5))
ax.set_xlabel("CHI previsto (média do decil)")
ax.set_ylabel("CHI observado (média do decil)")
ax.set_title("Calibração por decil de risco\n(backtest 2023-2025)")
salvar(fig, "06_calibracao.png")

print(json.dumps(sorted(p.name for p in FIG.glob("*.png"))))
