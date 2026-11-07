# Saídas de MS que os outros repositórios consomem

O pipeline de MS grava tudo em subpastas `ems`; **nada disso vai para o git** (`data/ems/` está no `.gitignore`), e os
arquivos ficam no clone do `distribution-asset-risk` para os repositórios irmãos lerem. Em MT, os irmãos leem
`../distribution-asset-risk/data/interim` e `/processed`; em MS, leem **`../distribution-asset-risk/data/ems/interim`** e
**`../distribution-asset-risk/data/ems/processed`**. Execução de 06/11/2026, a partir da configuração
[`configs/ems.yaml`](../configs/ems.yaml).

> Projeto independente, sem vínculo com a Energisa ou com a ANEEL. Só dados abertos (ANEEL e IBGE).

## Chaves e convenções (leia antes de juntar tabelas)

* **Alimentador canônico = `CTMT.NOME` com zeros à esquerda até 6 caracteres**, em coluna `alimentador` (ou
  `alimentador_nome`): `AJO51` vira `0AJO51`. Em MT são 6 dígitos (`013014`); em MS são 5 caracteres alfanuméricos
  completados com um zero. Os nomes são estáveis entre snapshots; o `COD_ID` do circuito (`alimentador_cod_id`) **não é**.
* **Vínculo de uma interrupção com o alimentador:** `coalesce(alimentador_cod_id, alimentador_nome)` da interrupção casa
  com `codigo` de `crosswalk_<ano>.parquet`, que devolve o alimentador canônico. Interrupções até 2025 trazem o código
  operacional (`alimentador_nome`); as de 2026 trazem o `COD_ID` (`alimentador_cod_id`). Use só crosswalks de snapshots
  até o ano que a análise pode conhecer (cortes temporais, `gridrisk.features.falhas_point_in_time`).
* **Conjunto:** `conjunto_id` das interrupções é o `IdeConjUndConsumidoras` dos arquivos de continuidade.
* **Média tensão:** `origem_mt` = tensão de 1 kV a menos de 69 kV. O alvo do painel é MT, `origem = 'INTERNA'` e
  `tipo = 'NAO PROGRAMADA'`. O CHI regulatório é o de `expurgo = 'NAO HOUVE EXPURGO'` com `duracao_h >= 3/60`.
* **Anos de snapshot:** 2018 a 2025 (31/12 de cada ano). **2018 a 2020 são do modelo M10 (sem `CT_COD_OP`, `DAT_CON` de
  trafos igual a `01/01/1920`); 2021 em diante são V10/V11.** Ver `decisoes_ems.md`.
* **Duas coisas que não estão nos arquivos e que os irmãos precisam saber:** março de 2026 não tem registro nas
  interrupções, e outubro de 2021 tem CHI de emergência que o regulador conta e o arquivo marca como expurgado
  (`decisoes_ems.md`, seção 3.4).

## `data/ems/interim/`

| Arquivo | O que é | Linhas | Quem lê (em MT) |
|---|---|---|---|
| `interrupcoes_ems.parquet` | Interrupções da EMS (2018 a jul/2026) nos dois layouts da ANEEL, num esquema só | 1.466.882 | `automation-impact`, `recloser-performance`, `substation-health-index` |
| `falhas.parquet` | Falhas de MT por alimentador × ano × mês × modo, ligadas com **todos** os snapshots (corte 2025) | 132.345 | `automation-impact`, `recloser-performance` |
| `bdgd_feeders_<ano>.parquet` (2018 a 2025) | Um registro por circuito (CTMT) com rede, proteção, carga, clientes, GD e geografia | 315, 423, 318, 320, 349, 354, 359, 362 | `automation-impact` (usa 2024) |
| `bdgd_map_<ano>.parquet` | Código operacional do alimentador → `CTMT.COD_ID` | 315, 423, 318, 397, 420, 428, 464, 440 | via crosswalk |
| `crosswalk_<ano>.parquet` | `codigo` (operacional ou `COD_ID`) → `alimentador` canônico | 630, 844, 636, 717, 769, 782, 791, 802 | `substation-health-index`, `automation-impact` |

### `interrupcoes_ems.parquet`
`cod_interrupcao` (string), `inicio`, `fim` (timestamp), `conjunto_id` (int), `conjunto_nome`, `alimentador_nome`
(código operacional, completado a 6 caracteres; nulo no layout novo), `alimentador_cod_id` (`COD_ID`; nulo no layout
legado), `subestacao`, `origem` (`INTERNA`/`EXTERNA`), `tipo` (`PROGRAMADA`/`NAO PROGRAMADA`), `causa`, `detalhe`,
`nivel_tensao_v` (int, volts), `uc_afetadas`, `uc_conjunto` (int), `expurgo` (texto normalizado; só `NAO HOUVE EXPURGO`
conta para o DEC), `elemento`, `localizacao` (só no layout novo), `ano`, `mes`, `duracao_h`, `chi` (= `duracao_h` ×
`uc_afetadas`), `origem_mt` (bool) e `grupo_causa` (`EQUIPAMENTO`, `DESCARGA_ATMOSFERICA`, `VEGETACAO`, `VENTO`,
`ANIMAIS`, `TERCEIROS`, `SOBRECARGA_TENSAO`, `FALHA_OPERACIONAL`, `MEIO_AMBIENTE_OUTROS`, `NAO_IDENTIFICADA`,
`EXTERNA`, `PROGRAMADA`, `OUTROS`). Linhas repetidas **não** foram removidas (menos de 0,03% do CHI; `decisoes_ems.md`).

### `falhas.parquet`
`alimentador`, `ano`, `mes`, `modo` (7 modos: `EQUIPAMENTO`, `DESCARGA_ATMOSFERICA`, `VEGETACAO`, `VENTO`, `ANIMAIS`,
`TERCEIROS`, `OUTRAS`), `n_falhas` (registros da ANEEL), `chi`, `chi_regulatorio`, `ci` (consumidores interrompidos) e
`duracao_mediana_h`. Só entram falhas que casam com um circuito (99,5% a 100% de 2021 a 2025; 85,8% em 2026).

### `bdgd_feeders_<ano>.parquet`
`alimentador_cod_id`, `alimentador_nome` (canônico), `subestacao_bdgd`, `ten_nom_cod`, `energia_mwh_ano`,
`pico_sazonal_energia`, `rede_mt_km`, `n_segmentos_mt`, `frac_rural` (`ARE_LOC = 'NU'`), `frac_monofasica`,
`frac_compacta`, `frac_subterranea`, `frac_cabo_nu`, `maior_vao_km`, `n_trafos`, `kva_instalado_mva`, `kva_mediano`,
`frac_trafos_mrt`, `idade_media_trafos`, `idade_p90_trafos`, `frac_trafos_25anos`, `frac_trafos_sem_data`,
`n_religadores` (`TIP_UNID` 32), `n_seccionalizadores` (35, 36), `n_chaves_fusiveis` (22 a 27),
`n_chaves_telecomandadas` (`TLCD = 1`), `idade_media_chaves`, `n_uc`, `frac_uc_rurais`, `n_gd`, `gd_mw`, `lat`, `lon`
(medianas dos trafos, graus), `extensao_km`, `religadores_por_100km`, `fusiveis_por_km`, `uc_por_km`, `carga_media_mw`,
`ano_snapshot`. **Estão todos os circuitos do cadastro, inclusive os vazios** (sem rede MT e sem consumidor: 10 em 2018,
105 em 2019, 2 em 2020, 6 em 2021 e nenhum depois); o painel de modelagem os exclui, estes arquivos não. As colunas de
idade **não são confiáveis nos snapshots M10** (2018 a 2020).

## `data/ems/processed/`

| Arquivo | O que é | Linhas |
|---|---|---|
| `risco_alimentador.parquet` | Previsão e risco de 2026 por alimentador (362) | 362 |
| `previsao_2026.parquet` | `pred_n_falhas`, `pred_chi`, `prob_ao_menos_1_falha` por alimentador × modo, com o observado parcial de 2026 | 2.534 |
| `panel.parquet` | Painel alimentador × ano × modo (2019 a 2026), features e alvos | 18.739 |
| `backtest_chi.parquet`, `backtest_n_falhas.parquet` | Previsões do backtest 2023-2025 (modelo e dois baselines) | 7.434 cada |
| `candidatos_social.parquet`, `candidatos_compensacao.parquet` | Pacotes de intervenção por alimentador, com custo, CHI evitado e VPL | 5.408 cada |
| `shap_chi.parquet`, `shap_amostra_X.parquet` | Valores SHAP do modelo de CHI e a amostra de features | 6.000 cada |

### `risco_alimentador.parquet` (o que `automation-impact` lê em MT)
`alimentador`, `chi_previsto`, `chi_reg_previsto`, `n_falhas_previsto`, `rs_por_chi_compensacao`,
`risco_rs_compensacao`, `rs_por_chi_social`, `risco_rs_social`, `modo_dominante`, `chi_historico_3a`, `lat`, `lon`,
`rede_mt_km`, `n_uc`, `frac_rural`, `frac_cabo_nu`, `subestacao_bdgd`, `dec_contribuicao_h`.
`rs_por_chi_compensacao` e `rs_por_chi_social` são R$ por CHI (medianas de R$ 1,88 e R$ 4,75 por alimentador em MS; o
custo da energia não suprida, de R$ 7.000/MWh, é premissa).

### `panel.parquet`
Uma linha por alimentador × ano alvo (2019 a 2026) × modo, com as colunas de `bdgd_feeders_<ano-1>`, o histórico de
falhas só com anos anteriores (`n_falhas_media_1a`, `chi_media_1a`, `n_falhas_media_3a`, `chi_media_3a`,
`n_falhas_total_media_3a`, `chi_total_media_3a`, `tendencia_falhas_total`, `duracao_mediana_3a_h`) e os alvos
(`n_falhas`, `chi`, `chi_regulatorio`, `ci`). O painel de MS **não inclui** circuitos sem rede e sem consumidor.

## Outros arquivos em `data/ems/`

* `data/ems/raw/bdgd/2025/Energisa_MS_404_2025-12-31_V11_20260830-0339.gdb` (2,1 GB): o File Geodatabase de 2025,
  mantido depois do processamento. **Os dos outros anos são apagados** por `build_bdgd.py`: extraia o zip do cache
  compartilhado (`bdgd-cache/ems/bdgd_<ano>_<item>.gdb.zip`) para uma pasta do **seu** clone, e nunca aponte
  `data/raw/bdgd/<ano>` para o cache (os `build_snapshot` apagam esse caminho).
* `data/ems/raw/continuidade/`: os dois Parquet nacionais da ANEEL, **com cada linha repetida duas vezes**. Leia sempre
  com `gridrisk.ingest.continuidade` (`select distinct *`).

## `reports/ems/` e `app/data/ems/` (estes vão para o git)

`resultados.json`, `resumo_decisao.json`, `backtest_media.csv`, `backtest_resumo.csv`, `calibracao_*.csv`,
`fronteira_social.csv`, `fronteira_compensacao.csv`, `carteira_20M_*.csv`, `frac_chi_regulatorio_modo.csv`,
`shap_importancia_chi.csv`, `validacao_dec_fec.csv`, `validacao_dec_fec_mensal.csv`, `variacao_sementes.{csv,json}`,
`ablacao_point_in_time.csv`, `figures/*.png` e `diagnostico/` (BDGD por ano, vínculo de circuitos, linhas repetidas).
`app/data/ems/` tem os 4 Parquet do painel.

## O que muda para quem lê em MT e passa a ler em MS

| Item | MT | MS |
|---|---|---|
| Pasta | `data/interim`, `data/processed` | `data/ems/interim`, `data/ems/processed` |
| Interrupções | `interrupcoes_emt.parquet` | `interrupcoes_ems.parquet` (nome da sigla em minúsculas) |
| Código do alimentador | 6 dígitos (`013014`) | 5 caracteres alfanuméricos com zero à esquerda (`0AJO51`) |
| Snapshots M10 | 2018 a 2020 | 2018 a 2020 (mesmos anos) |
| Configuração | `configs/emt.yaml` | `configs/ems.yaml`, com `--config` ou `GRIDRISK_CONFIG` |
| Circuitos do cadastro de 2025 | 697 | 362 |
