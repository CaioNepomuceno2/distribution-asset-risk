# Guarda de MT: a refatoração multi-distribuidora não mudou nada de MT

A mudança que acrescentou `--config`, `paths.reports`, `paths.app_data` e as janelas à configuração tinha uma regra
dura: **os caminhos e os resultados de MT ficam exatamente como estão**. Este documento mostra como isso foi conferido.
Os hashes e os scripts estão em [`guarda_mt/`](guarda_mt/).

## Método

1. **Antes** (código inalterado, `main`): regenerei dos zips de MT já no cache as interrupções harmonizadas, os 8
   snapshots da BDGD (feeders e mapas de códigos), os 8 crosswalks, as falhas (um conjunto por corte temporal e o
   conjunto final), o painel, o R$/CHI por conjunto e por alimentador e o DEC reconstruído, e guardei os hashes
   ([`guarda_mt/antes.json`](guarda_mt/antes.json)). O LightGBM ficou de fora: ele varia entre execuções.
2. **Depois** (código refatorado, **sem `--config`**, a configuração padrão): movi `data/interim/` de lado e refiz tudo do
   zero, inclusive a extração dos 8 snapshots, com `build_interrupcoes.py` e `build_bdgd.py` ([`depois.json`](guarda_mt/depois.json)).
3. **Comparação** arquivo a arquivo em três níveis: bytes iguais; conteúdo igual com a ordem das linhas ignorada
   (soma e XOR de um hash de 64 bits de cada linha, em todas as colunas); e, quando o conteúdo difere, a maior diferença
   relativa nas colunas de ponto flutuante, com todas as outras colunas idênticas
   ([`comparacao_antes_depois.csv`](guarda_mt/comparacao_antes_depois.csv)).

## O piso de ruído: o código inalterado também não repete os bytes

Antes de comparar, rodei o **mesmo código duas vezes** para saber o que "diferente" quer dizer:

| Execução repetida do código inalterado | Resultado |
|---|---|
| `harmonize` (DuckDB, interrupções de MT, 2.413.120 linhas) | bytes diferentes, **ordem das linhas diferente**, conteúdo idêntico |
| `guarda_det` (falhas, painel, crosswalks, R$/CHI; 22 arquivos) | 22 com bytes diferentes; 17 com conteúdo idêntico; 5 diferem só em ponto flutuante, até 6,6e-16 |
| `feeder_features` sobre o mesmo `.gdb` de 2025 | 3.024 células de ponto flutuante diferem, até 1,05e-15 |

Ou seja: o escritor de Parquet do DuckDB não é determinístico (a ordem das linhas muda entre execuções) e as somas em
paralelo mudam o último dígito dos números de ponto flutuante. **Igualdade de bytes não é um critério alcançável para
quase nenhum arquivo, nem entre duas execuções do código que não mudou.** O critério usado é o que sobra: mesmas
linhas, mesmas células não numéricas e diferença de ponto flutuante dentro do piso de ruído.

## Resultado (40 arquivos)

| Grupo | Arquivos | Resultado |
|---|---|---|
| `bdgd_map_<ano>` (8) e `validacao_dec_fec.csv` | 9 | **bytes idênticos** |
| `interrupcoes_emt.parquet` (2.413.120 linhas), `crosswalk_<ano>` (8), `falhas_corte_2018` a `2022` (5) | 14 | conteúdo idêntico, linha a linha (ordem ignorada); bytes diferem como no piso de ruído |
| `bdgd_feeders_<ano>` (8), `falhas`, `falhas_corte_2023` a `2025`, `panel`, `comp`, `pesos`, `valor_compensacao`, `valor_social` | 17 | todas as células não numéricas idênticas; ponto flutuante difere **no máximo 2,1e-15** (relativo), a mesma ordem do piso (1,05e-15) |

Nenhum arquivo difere acima de 2,1e-15. O DEC reconstruído de MT (2020 a 2026) saiu com os mesmos bytes.

## O pipeline de MT refatorado, até o fim

Com uma cópia da configuração de MT que só redireciona `processed`, `reports` e `app_data` para uma pasta de teste
(a configuração real grava em `reports/` e em `app/data/`, onde estão os resultados publicados), rodei
`validate_dec.py` e `run_pipeline.py`, inclusive o LightGBM:

* `falhas.parquet` e `panel.parquet` iguais aos de antes, com o mesmo critério acima (diferença máxima de 3,7e-16 e 2,1e-15).
* Os baselines (média de 3 anos e ano anterior) reproduzem `reports/backtest_media.csv` **com as quatro casas
  decimais**. O modelo difere dentro do ruído de semente do README (erro do CHI de 16.175 para 16.260, +0,5%; o
  desvio-padrão entre sementes é de 62, ou 0,4%).
* Carteira de R$ 20 milhões, visão social: VPL de R$ 107,8 mi (publicado: R$ 108,1 mi; ótima), R$ 97,1 mi (R$ 97,6 mi;
  gulosa) e R$ 45,8 mi (R$ 46,5 mi; tradicional), e Spearman parcial de 2026 de 0,830 (0,83 no README). Nenhum
  desses números foi gravado em `reports/`; eles ficaram na pasta de teste.

## Testes e o limite do diff

* [`tests/test_config.py`](../tests/test_config.py) falha se a configuração padrão deixar de resolver para exatamente
  `data/raw`, `data/interim`, `data/processed`, `reports`, `app/data`, `data/ref/mt_ibge.geojson`,
  `configs/intervencoes.yaml` e `interrupcoes_emt.parquet`; se as janelas de MT mudarem (2023 a 2025, 2026, 2022 a 2025,
  2019, 2022, 2023); se um YAML antigo, sem as chaves novas, não cair nesse mesmo padrão; e se algum script voltar a
  fixar `interrupcoes_emt`, `mt_ibge`, `ROOT / "reports"` ou `"MT"`.
* A suíte existente (48 testes) continua passando sem alteração.
* O diff da branch em relação à `main` **só toca `reports/ems/` e `app/data/ems/`**:
  `git diff --name-only main -- reports app/data` lista apenas arquivos dessas duas pastas, e não há arquivo novo
  fora delas.
