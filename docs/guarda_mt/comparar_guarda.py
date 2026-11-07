"""Compara antes x depois da guarda de MT, arquivo a arquivo, em tres niveis:
bytes iguais / conteudo igual (ordem das linhas ignorada) / so diferenca numerica de ponto flutuante (maior diferenca relativa).
Uso: python -I comparar_guarda.py   (cwd = guard_mt)
"""
import json, subprocess, sys
import numpy as np
import pandas as pd

A, B = json.load(open("antes.json")), json.load(open("depois.json"))
PASTAS = {"antes_interim": "depois_interim", "antes_det": "depois_det", "antes_csv": "depois_csv"}
def achar(nome, base):
    import os
    for pa, pd_ in PASTAS.items():
        if os.path.exists(f"{pa}/{nome}"):
            return f"{pa}/{nome}", f"{pd_}/{nome}"
rows = []
for nome in sorted(set(A) & set(B)):
    a, b = A[nome], B[nome]
    mesmo_byte = a["bytes"] == b["bytes"]
    mesmo_cont = all(a.get(c) == b.get(c) for c in ("linhas", "xor", "soma")) if "xor" in a else mesmo_byte
    maxrel = None
    if not mesmo_cont and nome.endswith(".parquet"):
        pa, pb = achar(nome, None)
        x, y = pd.read_parquet(pa), pd.read_parquet(pb)
        assert list(x.columns) == list(y.columns) and len(x) == len(y), nome
        chaves = [c for c in x.columns if x[c].dtype.kind not in "f"]
        x = x.sort_values(chaves, kind="stable").reset_index(drop=True); y = y.sort_values(chaves, kind="stable").reset_index(drop=True)
        nao_num_ok = all(x[c].equals(y[c]) for c in chaves)
        mx = 0.0
        for c in x.columns:
            if x[c].dtype.kind == "f":
                u, v = x[c].to_numpy(float), y[c].to_numpy(float)
                ig = (u == v) | (np.isnan(u) & np.isnan(v))
                if not ig.all():
                    mx = max(mx, float((np.abs(u - v)[~ig] / np.maximum(np.abs(u[~ig]), 1e-300)).max()))
        maxrel = mx if nao_num_ok else float("nan")
    rows.append({"arquivo": nome, "bytes_iguais": mesmo_byte, "conteudo_igual": mesmo_cont, "maior_dif_relativa": maxrel})
df = pd.DataFrame(rows)
print(df.to_string(index=False))
print()
print(f"arquivos: {len(df)} | bytes iguais: {int(df.bytes_iguais.sum())} | conteudo igual (ordem ignorada): {int(df.conteudo_igual.sum())} | "
      f"conteudo diferente so por ponto flutuante: {int((~df.conteudo_igual).sum())} (maior dif. relativa {df.maior_dif_relativa.max():.2e})")
print("so em antes:", sorted(set(A) - set(B)), "| so em depois:", sorted(set(B) - set(A)))
df.to_csv("comparacao_antes_depois.csv", index=False)
