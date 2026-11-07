"""Hash de arquivos: sha256 dos bytes + impressao digital do conteudo (parquet: ordem das linhas ignorada).
Uso: python -I hash_dir.py <saida.json> <arquivo_ou_glob>...
"""
import glob, hashlib, json, sys
import duckdb

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()

res = {}
for pat in sys.argv[2:]:
    for p in sorted(glob.glob(pat)):
        d = {"bytes": sha(p), "tamanho": __import__("os").path.getsize(p)}
        if p.endswith(".parquet"):
            r = duckdb.execute(f"select count(*), bit_xor(hash(t)), sum(hash(t)::hugeint) from (select t from read_parquet('{p}') t)").fetchall()[0]
            d["linhas"], d["xor"], d["soma"] = r[0], str(r[1]), str(r[2])
        res[p.replace("\\", "/").split("/")[-1]] = d
json.dump(res, open(sys.argv[1], "w"), indent=1)
print(len(res), "arquivos ->", sys.argv[1])
