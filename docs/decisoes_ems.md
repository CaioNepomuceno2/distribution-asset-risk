# Decisões de dados da Energisa MS (EMS)

Este documento foi escrito e commitado **antes** de qualquer resultado do modelo de MS (backtest, previsão, risco ou
carteira). Cada decisão sai de um diagnóstico dos dados abertos de MS, e não de um resultado. Os diagnósticos são
reproduzíveis com `scripts/diagnostico_bdgd.py`, `scripts/diagnostico_vinculo.py`, `scripts/diagnostico_duplicatas.py`
e `scripts/validate_dec.py --alinhar-meses --mensal`, e as saídas ficam em
[`reports/ems/diagnostico/`](../reports/ems/diagnostico/). Execução de 06/11/2026.

O pipeline foi escrito e validado com a Energisa MT (EMT). Aqui cada suposição herdada de MT foi medida em MS antes de
ser mantida. As decisões de MT continuam em [`dados.md`](dados.md) e **não mudam**.

> Projeto independente, sem vínculo com a Energisa ou com a ANEEL. Só dados abertos (ANEEL e IBGE).

## Resumo das decisões

| # | Tema | O que os dados de MS mostram | Decisão |
|---|---|---|---|
| 1 | Snapshots da BDGD | 8 itens do ArcGIS Hub, títulos conferidos um a um (seção 1) | Versão mais recente de cada 31/12; item avulso de 31/10/2022 e versão de 17/12/2024 do snapshot de 2023 ficam de fora |
| 2 | Código do alimentador | `CTMT.NOME` tem 5 caracteres alfanuméricos (`AJO51`), e não 6 dígitos como em MT | Mantém a chave de MT: nome completado com zeros até 6 caracteres nos dois lados do vínculo (`0AJO51`); testado com BDGD sintética |
| 3 | Vínculo de circuitos | 99,5% a 100% das falhas de 2021 a 2025 casam com um circuito; 2018 a 2020 casam 79% (snapshots M10); 2026 casa 85,8% | Mesmo desenho de MT, com cortes temporais; 2026 só como checagem parcial |
| 4 | `TIP_UNID` | Código 32 é religador (68% telecomandados no snapshot de 2025, TUC 345 só nele); 22 a 27 são chaves fusíveis; 35 e 36 são seccionalizadores | Mapeamento de MT mantido |
| 5 | Idade dos ativos | `DAT_CON` dos trafos é o valor-padrão `01/01/1920` até 2020 e plausível desde 2021; `DAT_IMO` das chaves só tem 28% a 33% de datas reais | A idade continua **fora do modelo**, como em MT; os números ficam documentados para os outros repositórios |
| 6 | Expurgo | Os 7 códigos de MS têm o mesmo perfil dos de MT; o DEC reconstruído bate com o oficial em 2020 a 2025 | Mapeamento de MT mantido |
| 7 | Linhas repetidas | Continuidade: 50% das linhas repetidas, sem chave com dois valores. Interrupções: 0,28% das linhas em 2018, 0,24% em 2019, 0,05% em 2020 e nada depois | Continuidade lida sem as repetidas (leitor de MT). Interrupções lidas como publicadas (CHI repetido abaixo de 0,03%) |
| 8 | Buracos no arquivo de interrupções | Arquivo de interrupções sem nenhum registro de março de 2026; em outubro de 2021 o regulador conta CHI de emergência que o arquivo marca como expurgado | Nada é inventado nem excluído; os dois meses ficam sinalizados (seção 3.4) |
| 9 | Categoria "falha nas instalações da UC" | Só existe nas interrupções de 2025 em diante (3,5% das falhas de MT em 2025, 0,4% do CHI) | Mantida como em MT; a quebra de série fica registrada |
| 10 | Circuitos vazios | 105 dos 423 circuitos do snapshot de 2019 não têm rede MT nem consumidor (nos outros anos, de 0 a 10) | Painel de MS exclui circuito sem rede e sem consumidor (`qualidade.excluir_circuitos_vazios`); MT segue sem filtro |
| 11 | Janelas (teste, previsão, compensação) | Snapshots de 2018 a 2025 completos; compensações pagas em 2022 a 2025 para 60 ou 61 conjuntos; DEC reconstruído bate com o oficial nesses anos | Iguais às de MT: teste 2023 a 2025, previsão de 2026, compensação de 2022 a 2025 |
| 12 | Clima | O INMET só foi testado em MT, e o clima piorou o backtest lá | Não roda em MS (`usar_clima: false`, sem `clima.uf`) |
| 13 | Catálogo de intervenções | Premissas ilustrativas, as mesmas de MT; a elegibilidade muda (seção 5) | Mesmo catálogo e mesmos orçamentos, sem recalibrar |
| 14 | Eficácias medidas | As de MT vêm do `automation-impact` de MT | Não se aplicam a MS: a sensibilidade de eficácias fica de fora até o `automation-impact` rodar para MS |

## 1. Fonte e snapshots

A BDGD vem do ArcGIS Hub da ANEEL, um File Geodatabase por ano em 31/12. O título de cada item foi conferido em
`https://www.arcgis.com/sharing/rest/content/items/<id>?f=json` antes do download; os 8 conferem com a configuração
([`configs/ems.yaml`](../configs/ems.yaml)).

| Ano | Item | Título | Zip |
|---|---|---|---|
| 2018 | `5382c59d7cc7494a9a1f8cd865187457` | Energisa_MS_404_2018-12-31_M10_20191023-2327 | 364 MB |
| 2019 | `b83ad867a35b43189f41b68988f7f0b6` | Energisa_MS_404_2019-12-31_M10_20200323-1921 | 370 MB |
| 2020 | `fe56dce0714f4b6795d3b23130f5898a` | Energisa_MS_404_2020-12-31_M10_20210628-1527 | 357 MB |
| 2021 | `933af69c57dd41ea8f6048118b8d07e7` | Energisa_MS_404_2021-12-31_V10_20230315-1800 | 444 MB |
| 2022 | `ff5242147c86428e88971941a35c7cd1` | Energisa_MS_404_2022-12-31_V11_20240422-2036 | 459 MB |
| 2023 | `975f18dfdb0c479cb237893c5b296ca9` | Energisa_MS_404_2023-12-31_V11_20250923-1616 | 485 MB |
| 2024 | `b7fad4cd388845a08a01643599ec747b` | Energisa_MS_404_2024-12-31_V11_20250730-1637 | 511 MB |
| 2025 | `9a1ce360865f4358b31e9fb2d016aac9` | Energisa_MS_404_2025-12-31_V11_20260830-0339 | 480 MB |

Ficam de fora: `c3585ae516f340b596617827d60da5ef` (item avulso `EMS_404_2022-10-31_V10`, de outubro de 2022) e
`b8c585ae35224ac8aa0648587ec61bcb` (snapshot de 2023 de 17/12/2024, substituído pelo de 23/09/2025). Em MT a política é
a mesma: a versão mais recente de cada ano. Os zips ficam no cache compartilhado (somente leitura) com `MANIFESTO.json`
e `DOWNLOAD_DONE.txt`, que trazem tamanho e SHA-256 de cada arquivo.

## 2. Qualidade da BDGD de MS

Medida em cada um dos 8 snapshots por `scripts/diagnostico_bdgd.py` (um JSON por ano em
`reports/ems/diagnostico/bdgd_<ano>.json`). A coluna "2025" é a base do cadastro usado na previsão de 2026.

### 2.1 Camadas, modelo e circuitos

Os snapshots de 2018 a 2020 seguem o modelo antigo (M10, camada de trafos `UNTRD`) e os de 2021 em diante, o V10/V11
(`UNTRMT`). As camadas que o extrator lê existem nos 8 anos, e os apelidos de camada e de campo que já tratam o M10
em MT (`UNTRD`, `NOM`) servem para MS. Nenhuma camada-chave falta.

| | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| Modelo | M10 | M10 | M10 | V10 | V11 | V11 | V11 | V11 |
| Camadas no `.gdb` | 45 | 45 | 45 | 43 | 43 | 43 | 43 | 43 |
| Circuitos (CTMT) | 315 | 423 | 318 | 320 | 349 | 354 | 359 | 362 |
| `SSDMT.CT_COD_OP` existe | não | não | não | sim | sim | sim | sim | sim |
| Códigos operacionais no mapa | 315 | 423 | 318 | 397 | 420 | 428 | 464 | 440 |
| Rede MT (km) | 85.174 | 85.813 | 86.428 | 86.952 | 88.305 | 89.366 | 90.414 | 91.453 |
| `SSDMT.CTMT` existe em `CTMT` | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| Cabo nu (% do km) | 98,5 | 98,4 | 98,3 | 98,1 | 97,9 | 97,7 | 97,5 | 97,3 |
| Rede compacta (% do km) | 1,4 | 1,5 | 0,9 | 1,8 | 2,0 | 2,1 | 2,2 | 2,3 |

* **Mesmo desenho de chave, nome diferente.** Em MT, `CTMT.NOME` tem 6 dígitos (`013014`). Em MS tem 5 caracteres
  alfanuméricos (`CGP01`, `DOI06`, `RBR01`) e `SSDMT.CT_COD_OP` também (`PMU01`). O extrator completa com zeros à
  esquerda até 6 caracteres (`0CGP01`) nos dois lados do vínculo, as interrupções (`DscAlimentadorSubestacao`, ex.:
  `AJO51`) e o cadastro, então a chave continua consistente. O teste `tests/test_ems_fumaca.py` cobre `AJO51`, `AJO52`
  (segundo código operacional do mesmo circuito) e o `COD_ID` de 2026.
* **O snapshot de 2019 tem 98 circuitos de 3 caracteres** (`ACA`, `AJO`...), que são o código da subestação, não do
  alimentador. Esses e mais alguns somam 105 circuitos **sem rede MT e sem consumidor** (de 423). Nos outros anos há de
  0 a 10 (em MT, de 1 a 6 por snapshot). Decisão 10: o painel de MS tira esses circuitos vazios; eles só existiriam como
  linhas de zeros no treino de 2020. Os arquivos `bdgd_feeders_<ano>.parquet` guardam todos os circuitos, vazios
  incluídos.
* **Redes quase todas nuas e rurais.** 97% do km é cabo nu (98% em MT) e só 2% é rede compacta.

### 2.2 Equipamentos de manobra e proteção (`TIP_UNID`)

O domínio de `TIP_UNID` não vem dentro do `.gdb` (não há tabela de domínio). A evidência de que o mapeamento de MT vale
em MS é indireta, mas consistente:

* o código 32 (religador) tem **68% das unidades telecomandadas** (`TLCD = 1`) no snapshot de 2025 (36% a 46% nos
  anos anteriores), contra 0% a 0,1% das chaves fusíveis (22 a 27) e dos demais;
* o código de unidade construtiva `TUC` 345 aparece em 2.654 equipamentos de `EQSE`, **todos** de `TIP_UNID` 32 (98% dos
  equipamentos de religador), e o `TUC` 210 está em todos os 139 disjuntores (29);
* a densidade de religadores é de 2,9 por 100 km em 2025, contra 1,9 em MT, plausível para a rede.

| | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| Chaves (`UNSEMT`) | 137.052 | 136.158 | 113.217 | 116.909 | 121.063 | 125.633 | 137.493 | 161.148 |
| Religador (32) | 1.730 | 1.839 | 1.936 | 2.000 | 2.144 | 2.211 | 2.295 | 2.646 |
| Seccionalizador (35, 36) | 302 | 377 | 433 | 419 | 334 | 290 | 268 | 456 |
| Chave fusível (22 a 27) | 118.517 | 120.267 | 93.649 | 98.091 | 101.832 | 105.182 | 116.315 | 139.480 |
| Fora do mapeamento | 12,0% | 10,0% | 15,1% | 13,9% | 13,7% | 14,2% | 13,4% | 11,4% |

O que fica fora do mapeamento são os códigos 19 (17 mil chaves em 2025, 11% do total), 33, 47, 49 e outros pequenos.
Não achei rótulo para eles nos dados, e o extrator os ignora, como faz em MT com o 34 (28 mil chaves em 2025). O salto de
religadores telecomandados em 2025 (de 36% para 68%) está no cadastro e entra como mudança de feature, não como erro de
mapeamento.

### 2.3 Datas (`DAT_CON` e `DAT_IMO`)

"Data real" é a que não é o valor-padrão e se lê como `dd/mm/aaaa`.

| | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| Trafos: `DAT_CON` igual a `01/01/1920` | 100% | 99,3% | 67,8% | 0% | 0% | 0% | 0% | 0% |
| Trafos: `DAT_CON` igual a `01/01/1980` | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 0% |
| Trafos: ano mediano de `DAT_CON` | 1920 | 1920 | 1920 | 2013 | 2014 | 2015 | 2015 | 2017 |
| Chaves (`EQSE`): `DAT_IMO` com data real | 0% | 0% | 28,3% | 31,4% | 31,6% | 32,6% | 30,4% | 29,4% |
| Trafos (`EQTRD`/`EQTRMT`): `DAT_IMO` com data real | 0% | 0% | 85,2% | 90,8% | 90,5% | 90,1% | 90,2% | 89,7% |

* Em MS a data-padrão de MT (`01/01/1980`) não existe. O M10 usa **`01/01/1920`** em `DAT_CON` e `DAT_IMO` (100% em 2018,
  99% em 2019 e 68% de `DAT_CON` em 2020) e, em 2020, o texto `0` em `DAT_IMO` (72% das chaves e 15% dos trafos).
* **Snapshots com data utilizável:** `DAT_CON` dos trafos a partir de 2021 (V10), com 32% de datas reais já em 2020;
  `DAT_IMO` dos trafos a partir de 2020; `DAT_IMO` das chaves a partir de 2020, mas só com 28% a 33% de datas reais
  em todos os anos. No snapshot de 2025, a data das chaves está preenchida em cerca de 15% das fusíveis (`TIP_UNID` 22)
  e em 79% a 100% das demais. Quem usar a idade de chaves (`switchgear-survival`) precisa tratar isso.
* Mesmo com `DAT_CON` limpa, 9,1% dos trafos de 2025 têm ano de conexão 2017 (lote de recadastramento, como em MT).
  **Decisão:** a idade segue fora do modelo de MS, como em MT. Três dos 8 snapshots (M10) não têm data utilizável, e
  provar que a idade ajuda em MS exigiria olhar o resultado do modelo.

### 2.4 Coordenadas e consumidores

* **CRS:** `EPSG:4674` (SIRGAS 2000, graus) em todas as camadas dos 8 snapshots, o mesmo de MT.
* **100%** dos trafos de cada snapshot caem dentro da caixa do estado (longitude de -58,17 a -50,92 e latitude de -24,07
  a -17,17, da malha do IBGE) e nenhum fica sem geometria.
* `UCBT.CTMT` existe em `CTMT` para 99,2% a 100% dos consumidores de BT; 6% a 8% são rurais (`CLAS_SUB` `RU*`).
* **Para o `recloser-performance`:** em `UNSEMT.PAC_1`, 96% a 98% das chaves têm PAC de 19 ou 20 caracteres, como em MT
  (exemplo de 2025: `42721345758317862MT`, 17 dígitos mais o sufixo do nível de tensão). Se esses dígitos são
  coordenada UTM e em qual fuso (MS cruza o 21S e o 22S) é verificação do repositório que usa o PAC; esta etapa só
  registra que o formato é o mesmo.

## 3. Interrupções e continuidade (ANEEL)

### 3.1 Linhas repetidas

`count(*)` contra `count(distinct *)` em **todos** os arquivos lidos (tabela completa em
[`reports/ems/diagnostico/duplicatas_aneel.csv`](../reports/ems/diagnostico/duplicatas_aneel.csv)):

| Arquivo | Escopo | Linhas | Distintas | Repetidas | % | CHI repetido | Chaves com 2 valores |
|---|---|---|---|---|---|---|---|
| interrupções 2018 | EMS | 137.841 | 137.460 | 381 | 0,28 | 0,026% | |
| interrupções 2019 | EMS | 146.020 | 145.668 | 352 | 0,24 | 0,015% | |
| interrupções 2020 | EMS | 140.072 | 140.006 | 66 | 0,05 | 0,005% | |
| interrupções 2021 a 2026 | EMS | 1.042.949 | 1.042.949 | 0 | 0,00 | 0 | |
| indicadores 2020-2029 | EMS | 197.212 | 98.606 | 98.606 | 50,00 | | 0 |
| indicadores 2020-2029 | nacional | 10.456.656 | 5.228.328 | 5.228.328 | 50,00 | | 0 |
| compensações 2020-2029 | EMS | 441.408 | 220.704 | 220.704 | 50,00 | | 0 |
| compensações 2020-2029 | nacional | 20.702.542 | 10.344.506 | 10.358.036 | 50,03 | | 170 |

* **Continuidade (indicadores e compensações):** cada linha da EMS aparece duas vezes e nenhuma chave tem dois valores
  diferentes, então o `distinct` é exato (mesmo achado de MT, em `dados.md`). Toda leitura passa por
  `gridrisk.ingest.continuidade` e conta cada registro idêntico uma vez. As 170 chaves com dois valores são de outras
  distribuidoras e não atingem a EMS.
* **Interrupções:** as linhas idênticas de 2018 a 2020 afetam 1 a 2 UC cada, o que é compatível com consumidores
  diferentes de uma mesma ordem; não dá para distinguir isso de erro. Elas pesam menos de 0,03% do CHI de cada ano, e
  o DEC reconstruído de 2020 bate com o oficial sem remover nada. **Decisão:** ler as interrupções como
  publicadas, o mesmo tratamento de MT (que tem 1 linha repetida em 2.413.120, em 2022).

### 3.2 Domínio do expurgo (`IdeMotivoInterrupcao`)

O mapeamento de MT foi inferido comparando o perfil de cada código legado (2025) com o texto do layout novo (2026).
Refiz a comparação com os dados de MS:

| Código | Linhas 2025 | UC por linha | % BT | Causa modal | Categoria do layout novo com o mesmo perfil (2026) |
|---|---|---|---|---|---|
| 0 | 142.870 | 47,3 | 48,2 | próprias do sistema | Não houve expurgo (58,5 UC) |
| 1 | 34.366 | 2,4 | 72,5 | não classificada | Falha nas instalações da UC (2,8 UC) |
| 2 | 136 | 3,6 | 0 | não classificada | Obras de interesse exclusivo do usuário (1,1 UC) |
| 3 | 65.071 | 86,6 | 12,4 | meio ambiente | ISE por meio de CHI (67,9 UC, meio ambiente) |
| 6 | 5.846 | 87,8 | 39,5 | próprias do sistema | Dia crítico (66,2 UC) |
| 7 | 43 | 2.153,8 | 0 | próprias do sistema (origem externa) | Origem externa (949,7 UC) |
| 8 | 35 | 1.447,8 | 0 | não classificada (origem externa) | Origem externa |

Os 7 códigos de MS (0, 1, 2, 3, 6, 7, 8) existem no dicionário de MT, nenhum cai em `OUTRO`. Os códigos 7 e 8 têm perfil
de origem externa em MS (em MT o 7 é alívio de carga); como todo código diferente de 0 fica fora do DEC e do CHI
regulatório, o rótulo não muda nenhum número. O código 5 (ISE por decreto) não aparece em nenhum ano legado de MS, mas
766 linhas de 2026 trazem essa categoria no layout novo. **Decisão:** manter o mapeamento de MT.

### 3.3 DEC e FEC reconstruídos contra o oficial

Pelo mesmo método de MT (`scripts/validate_dec.py`, sem expurgo e com 3 minutos ou mais), com `--alinhar-meses`, que
em 2026 compara só os meses que existem no arquivo de interrupções:

| Ano | DEC oficial | DEC recalculado | FEC oficial | FEC recalculado |
|---|---|---|---|---|
| 2020 | 10,00 | 10,00 | 4,31 | 4,31 |
| 2021 | 10,23 | 9,01 | 4,27 | 3,92 |
| 2022 | 9,62 | 9,61 | 4,23 | 4,23 |
| 2023 | 9,29 | 9,28 | 3,99 | 3,99 |
| 2024 | 9,03 | 9,03 | 4,25 | 4,25 |
| 2025 | 9,13 | 9,12 | 4,33 | 4,32 |
| 2026 (jan a jul) | 4,74 | 3,94 | 2,25 | 1,94 |

Em 2020 e de 2022 a 2025 a diferença é de no máximo 0,01 h no DEC. A razão mensal (calculado ÷ oficial,
[`reports/ems/validacao_dec_fec_mensal.csv`](../reports/ems/validacao_dec_fec_mensal.csv)) fica entre 0,99 e 1,01 em
todos os meses de 2020, 2022, 2023, 2024 e 2025 e de janeiro a julho de 2021. As exceções são agosto a dezembro de 2021
(a pior é outubro, 0,03; as outras ficam entre 0,96 e 0,99), janeiro de 2026 (1,04) e março de 2026 (0). Os dois piores
meses, outubro de 2021 e março de 2026, estão na seção 3.4; sem eles, a correlação mensal por conjunto sobe de 0,9596
para 0,9994.

### 3.4 Dois buracos nos dados de interrupções

* **Março de 2026: nenhum registro.** O arquivo de 2026 tem janeiro, fevereiro e abril a julho; março não tem uma única
  linha (em MT, março de 2026 existe). O DEC oficial de março de 2026 é 0,83 h. Consequência: os números observados de
  2026 de MS (a checagem parcial) não incluem março. **Nada foi inventado**; a checagem de 2026 de MS fica registrada
  como parcial e com esse buraco.
* **Outubro de 2021: o regulador conta CHI que o arquivo marca como expurgado.** O arquivo tem 12.288 registros em
  outubro de 2021, 12.096 deles com o código 3 (ISE por meio de CHI, 4,3 milhões de CHI, 7,6 h de duração mediana).
  Meu cálculo, que exclui todo CHI de ISE, dá DEC de 0,03 h; o oficial é 1,23 h. A diferença (1,19 milhão de CHI) é
  compatível com o regulador contar só a parcela de ISE acima de um limite de tempo de restabelecimento (a parcela
  acima de 12 h vale 1,57 milhão e a acima de 24 h, 0,87 milhão), mas essa leitura é uma **hipótese não verificada**.
  Fica registrado que o `chi_regulatorio` de MS em outubro de 2021 está subestimado. Isso só afeta o ano de 2021, que
  não entra nas janelas de compensação (2022 a 2025) nem na fração regulatória (2023 a 2025).

### 3.5 Composição das falhas e quebra de 2025

Falhas de MT, internas e não programadas (a definição do painel, igual à de MT), por categoria:

| Grupo de causa (% das falhas) | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| Descarga atmosférica | 46,4 | 41,0 | 38,6 | 35,5 | 39,3 | 39,2 | 32,4 | 29,9 | 15,9 |
| Vento | 7,6 | 13,2 | 13,3 | 13,7 | 20,6 | 28,7 | 31,2 | 33,3 | 21,8 |
| Equipamento | 11,7 | 14,4 | 15,2 | 17,4 | 12,9 | 10,0 | 12,2 | 10,6 | 28,0 |
| Vegetação | 12,4 | 14,2 | 14,4 | 13,3 | 11,0 | 7,9 | 8,0 | 7,2 | 4,7 |
| Animais | 8,8 | 10,1 | 11,4 | 12,1 | 8,9 | 6,5 | 8,0 | 4,8 | 1,6 |
| Terceiros | 2,7 | 1,4 | 1,6 | 2,2 | 1,9 | 1,4 | 2,0 | 2,6 | 10,0 |
| Não identificada | 9,3 | 4,0 | 3,3 | 3,4 | 3,3 | 2,3 | 2,8 | 6,7 | 12,2 |
| Outros (sobrecarga, operacional etc.) | 0,9 | 1,7 | 2,3 | 2,5 | 2,2 | 3,9 | 3,2 | 4,9 | 5,8 |

* O peso de cada grupo muda muito de ano para ano (vento sobe de 8% para 33%; descarga cai de 46% para 30%), e o
  layout novo de 2026 reclassifica (equipamento, terceiros e não identificada sobem). O modelo usa o histórico por
  modo, então herda essas mudanças; isso é uma limitação, e não algo que eu tenha ajustado.
* **Quebra de série em 2025.** A categoria de expurgo "Falha nas instalações da unidade consumidora sem afetar
  terceiros" só existe no arquivo a partir de 2025: 4.095 das 118.385 falhas de MT (3,5%) e 0,4% do CHI em 2025, e 9.089
  das 103.373 (8,8%) em 2026. Nos anos anteriores, zero. Em MT o código existe em todos os anos (de 34 mil a 110 mil linhas por ano). **Decisão:** manter, como em MT
  (não filtrar por expurgo); o efeito sobre o último ano de treino é pequeno, e a checagem parcial de 2026 fica
  registrada com esse viés.
* **O CHI expurgado pesa mais em MS.** O CHI de ISE por meio de CHI é 50% a 58% do CHI das falhas de MS em 2023 a 2025,
  e o regulatório (sem nenhum expurgo) é 38% a 46%. Em MT, 74% do CHI é regulatório. A visão de caixa (compensações)
  usa só a parte regulatória, então fica proporcionalmente menor em MS.

## 4. Vínculo interrupção -> circuito da BDGD

% das **falhas** (MT, internas, não programadas) que casam com um circuito, por ano do evento e por corte temporal
(`scripts/diagnostico_vinculo.py`; tabela completa, com CHI e com todos os eventos de MT, em
[`vinculo_circuitos.csv`](../reports/ems/diagnostico/vinculo_circuitos.csv)):

| Ano | Todos os snapshots | Corte `y-1` (features) | Corte `y` (alvo) |
|---|---|---|---|
| 2018 | 99,5 | 0,0 | 79,4 |
| 2019 | 99,5 | 78,8 | 79,4 |
| 2020 | 99,5 | 79,1 | 79,4 |
| 2021 | 99,5 | 78,5 | 99,5 |
| 2022 | 100,0 | 98,4 | 100,0 |
| 2023 | 100,0 | 100,0 | 100,0 |
| 2024 | 100,0 | 99,7 | 100,0 |
| 2025 | 100,0 | 99,9 | 100,0 |
| 2026 | 85,8 | 85,8 | 85,8 |

* O padrão é o mesmo de MT (79% a 80% de 2018 a 2020 por corte; 99,5% a partir de 2021): os snapshots M10 não têm
  `CT_COD_OP` e só casam pelo nome do circuito. Nos anos de teste (2023 a 2025) a cobertura é de 99,7% a 100%.
  **Decisão:** manter as janelas de MT; os alvos de 2019 e 2020 (anos só de treino) ficam subestimados em ~21%, como em
  MT.
* **2026:** **85,8% das falhas de MT (84,1% do CHI) casam com um circuito de alguma BDGD publicada**, contra 79,9% em
  MT (76,8% do CHI). O resto usa `COD_ID` de um cadastro ainda não publicado. **Decisão:** 2026 serve só de checagem
  parcial de ranking, como em MT, e agora com o buraco de março (seção 3.4).

## 5. Compensações, janelas e catálogo

* **Compensações pagas (R$, indicadores `PG*`, sem repetidas):** 2020: 11,1 mi; 2021: 13,4 mi; 2022: 19,1 mi; 2023:
  22,2 mi; 2024: 18,6 mi; 2025: 23,0 mi, para 60 conjuntos (61 em 2024 em diante). Todos os 67 conjuntos que recebem
  compensação aparecem nas interrupções. A janela de MT (2022 a 2025) tem os 4 anos completos em MS.
* **Janelas mantidas:** backtest em 2023, 2024 e 2025; previsão para 2026; compensação média de 2022 a 2025; início do
  painel em 2019; peso dos conjuntos por alimentador com eventos a partir de 2022; SHAP com dados a partir de 2023.
  Motivo: todos os snapshots (2018 a 2025) existem; o DEC reconstruído bate com o oficial nos anos de teste; a cobertura
  do vínculo nos anos de teste é de 99,7% a 100%. Os anos do treino que o vínculo atinge menos (2019 e 2020) são os
  mesmos de MT.
* **Catálogo de intervenções e orçamento:** iguais aos de MT (`configs/intervencoes.yaml`, orçamentos de R$ 5 a 80 mi, com
  R$ 20 mi como referência). São premissas ilustrativas, não de MS. O que muda com o cadastro de MS é a elegibilidade
  (snapshot de 2025):

| Intervenção | Alimentadores elegíveis em MS (de 362) | em MT (de 697) |
|---|---|---|
| Religador | 102 (28%) | 240 (34%) |
| Automação | 79 (22%) | 327 (47%) |
| Rede compacta | 336 (93%) | 612 (88%) |
| Para-raios | 320 (88%) | 586 (84%) |
| Poda | 210 (58%) | 449 (64%) |
| Manutenção preditiva | 341 (94%) | 631 (91%) |

  A automação fica menos elegível (22% contra 47%): a regra exige menos de 3 chaves telecomandadas e pelo menos 500
  consumidores, e o cadastro de 2025 de MS tem 1.814 chaves telecomandadas em 362 circuitos, contra 1.649 em 697 de MT.
  Não recalibrei a regra, para não ajustar premissa olhando o resultado.

## 6. O que fica igual a MT, e por quê

Definição de falha (MT, interna, não programada), os 7 modos de falha, a janela de 3 anos do histórico, o LightGBM
(Poisson e Tweedie, mesmos hiperparâmetros), as 5 sementes na previsão final, o R$/CHI a partir das compensações e do
custo social (R$ 7.000/MWh, premissa), o catálogo e o otimizador. Nada disso depende de um parâmetro que os dados de MS
contradigam. **Nenhum parâmetro foi calibrado em MS olhando métrica de modelo.**

## 7. O que não foi feito

* **Clima do INMET:** não roda em MS (decisão 12). `build_clima.py` e `experimento_clima.py` recusam rodar sem a chave
  `clima.uf`.
* **Sensibilidade com eficácias medidas:** depende do efeito do religador medido pelo `automation-impact` **em MS**,
  que ainda não existe. `sensibilidade_eficacias.py` recusa rodar sem `eficacias_medidas` na configuração.
* **Hipótese de ISE parcial em outubro de 2021:** não verificada (seção 3.4).
* **Tratamento do buraco de março de 2026:** nenhum; só registro.

## 8. Suposições de MT encontradas e como foram tratadas

| Onde | Suposição de MT | Tratamento |
|---|---|---|
| `scripts/ablacao_point_in_time.py`, `build_interrupcoes.py`, `experimento_clima.py`, `run_pipeline.py` (2 usos), `validate_dec.py` | arquivo `interrupcoes_emt.parquet` fixo | `Config.interrupcoes_parquet`: `interrupcoes_<sigla em minúsculas>.parquet`; o de MT segue `interrupcoes_emt.parquet` |
| `scripts/make_figures.py` | `data/ref/mt_ibge.geojson` | `paths.malha_ibge`; MS usa `data/ref/ms_ibge.geojson` (IBGE, UF 50, abaixo) |
| `scripts/build_clima.py` | UF `"MT"` do INMET | `clima.uf` na configuração; sem a chave, recusa rodar |
| `app/app.py`, `scripts/make_figures.py` | textos "Energisa MT / Mato Grosso", "2026", "2023-2025" | `Config.nome`, `nome_curto`, `ano_previsao` e `anos_teste` |
| `scripts/*.py` (7 scripts) | `ROOT / "reports"`; `run_pipeline.py`: `app/data` | `paths.reports` e `paths.app_data` (padrão igual ao caminho de MT) |
| `scripts/run_pipeline.py`, `ablacao`, `experimento_clima` | anos fixos (`[2023, 2024, 2025]`, `2026`, `[2022..2025]`, `2019`, `>= 2023`) | bloco `janelas` da configuração; padrão igual a MT |
| `risco.conjunto_do_alimentador` | `ano >= 2022` fixo | parâmetro `ano_min` (padrão 2022) |
| `scripts/run_pipeline.py` | chave `spearman_parcial_jan_jul` | mês final calculado dos dados (`jan_jul` em MT, igual) |
| `scripts/sensibilidade_eficacias.py` | efeito do religador medido em MT (16,6%) | lido de `eficacias_medidas` na configuração; MS não tem |
| `scripts/*.py` | `configs/intervencoes.yaml` fixo | `paths.catalogo` |
| `ingest/bdgd.py` | `CTMT.NOME` de 6 dígitos, `TIP_UNID`, `ISO_FAS_1`, `GEOM_CAB`, `01/01/1980` | medidos em MS (seções 2.1 a 2.3); mantidos |
| `ingest/interrupcoes.py` | domínio do expurgo e taxonomia de causas inferidos de MT | medidos em MS (seções 3.2 e 3.5); mantidos |
| `.gitignore` | só ignora `data/raw`, `data/interim`, `data/processed/*.parquet` | `data/ems/` ignorado |

**Malha do IBGE de MS.** `data/ref/ms_ibge.geojson` vem da API de malhas do IBGE
(`https://servicodados.ibge.gov.br/api/v3/malhas/estados/50?formato=application/vnd.geo+json&qualidade=intermediaria`),
a mesma chamada com a UF 51 e `qualidade=intermediaria` que reproduz `mt_ibge.geojson` byte a byte. É dado aberto do IBGE.
Códigos IBGE de MS começam com 50; os de MT, com 51.

## Como reproduzir os diagnósticos

```bash
python scripts/build_interrupcoes.py --config configs/ems.yaml
python scripts/build_bdgd.py --config configs/ems.yaml          # extrai, processa e apaga cada .gdb (menos o de 2025)
python scripts/diagnostico_bdgd.py --config configs/ems.yaml    # roda sobre o .gdb extraído, antes de build_bdgd apagá-lo
python scripts/diagnostico_vinculo.py --config configs/ems.yaml
python scripts/diagnostico_duplicatas.py --config configs/ems.yaml --interrupcoes-dir <pasta dos Parquet anuais>
python scripts/validate_dec.py --config configs/ems.yaml --alinhar-meses --mensal
```
