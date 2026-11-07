# Metodologia

> **Este documento descreve a Energisa MT.** A Energisa MS usa o mesmo método com a configuração [`configs/ems.yaml`](../configs/ems.yaml); as decisões e os resultados de MS estão em [`decisoes_ems.md`](decisoes_ems.md) e [`resultados_ems.md`](resultados_ems.md).

Este documento explica, passo a passo, como o projeto vai do dado bruto à carteira de investimento, quais
fórmulas e premissas entram em cada etapa e como ler cada resultado. As decisões de tratamento de dados estão
em [`dados.md`](dados.md), e as características do modelo de previsão, em [`model_card.md`](model_card.md).

## 1. Perguntas

1. **Onde está o risco?** Para cada alimentador da Energisa MT e cada modo de falha, quantas falhas e quanto
   CHI (consumidor-hora interrompido) esperar no próximo ano.
2. **Quanto vale esse risco?** Quanto cada hora de interrupção custa, em compensações pagas (visão de caixa) e em
   energia não suprida (visão social).
3. **O que fazer com um orçamento limitado?** Quais obras, em quais alimentadores, maximizam o valor presente
   do CHI evitado.

## 2. Dados e período

| Fonte | Uso | Período |
|---|---|---|
| ANEEL, interrupções nas redes de distribuição | alvo (falhas e CHI) e histórico; validação do DEC | 2018 a jul/2026 |
| ANEEL, BDGD (8 snapshots de 31/12) | atributos da rede por alimentador; vínculo de circuitos | 2018 a 2025 |
| ANEEL, indicadores coletivos e compensações | validação do DEC/FEC; R$ por CHI | 2020 a 2026 |
| INMET (testado, desligado) | climatologia por alimentador | 2018 a 2025 |
| `configs/intervencoes.yaml` | custos, eficácias e vida útil das intervenções | premissas |

## 3. Pipeline

| Etapa | Script | Funções principais | Saída |
|---|---|---|---|
| Interrupções | `scripts/build_interrupcoes.py` | `ingest.interrupcoes.download`, `harmonize` | `data/interim/interrupcoes_emt.parquet` |
| Cadastro da rede | `scripts/build_bdgd.py` | `ingest.bdgd.feeder_features`, `feeder_map` | `bdgd_feeders_{ano}`, `bdgd_map_{ano}` |
| Indicadores oficiais | `scripts/build_continuidade.py` | download CKAN | `data/raw/continuidade/` |
| Clima (desligado por padrão) | `scripts/build_clima.py` | `ingest.inmet.idw_to_feeders` | `clima_alimentador_mes.parquet` |
| Validação da base | `scripts/validate_dec.py` | DEC/FEC recalculados × oficiais | `reports/validacao_dec_fec.csv` |
| Painel e modelo | `scripts/run_pipeline.py` | `features.falhas_point_in_time`, `build_panel`, `model.backtest` | `reports/backtest_*.csv` |
| Risco e carteira | `scripts/run_pipeline.py` | `risco.valor_chi_alimentador`, `otimizacao.pacotes`, `fronteira` | `reports/fronteira_*.csv`, `carteira_20M_*.csv` |
| Robustez | `scripts/ablacao_point_in_time.py`, `scripts/sensibilidade_eficacias.py` | | `reports/ablacao_*.csv`, `sensibilidade_eficacias.csv` |

## 4. Definições e fórmulas

**CHI (consumidor-hora interrompido)** de uma interrupção: `UC afetadas × duração (h)`.

**DEC e FEC** de um conjunto no período: `DEC = Σ CHI / UC do conjunto` e `FEC = Σ UC afetadas / UC do conjunto`,
contando só interrupções sem expurgo e com duração ≥ 3 min. A recomposição a partir das interrupções individuais
bate com o DEC oficial (correlação de 1,0 por conjunto e mês, `reports/validacao_dec_fec.csv`). Essa validação
garante que o CHI usado no resto do projeto é o mesmo que a ANEEL usa.

**CHI regulatório** é o CHI sem expurgo. O CHI expurgado (dias críticos, situação de emergência) pesa para o
cliente, mas não entra no DEC nem gera compensação. As duas contas são separadas em todo o projeto.

**Modelos de previsão** (`model.py`), uma linha por alimentador × ano × modo:

* nº de falhas: LightGBM com objetivo Poisson;
* CHI: LightGBM com objetivo Tweedie (p = 1,4), porque o CHI tem muitos zeros e cauda longa.

**Deviance de Poisson**, a métrica principal do nº de falhas: `D = 2 · média[ y·ln(y/μ) − (y − μ) ]`. É a métrica
natural para contagens: penaliza errar muito em alimentadores com poucas falhas, o que o erro absoluto não faz.

**Captura do top-k%**: fração do CHI real do ano que estava nos k% de alimentadores com maior previsão. Mede o
uso real do modelo: se a lista de prioridade aponta para os alimentadores certos.

**R$ por CHI** (`risco.py`):

* visão de caixa: `R$/CHI do conjunto = compensações pagas (PG*) / CHI regulatório do conjunto`, média de
  2022 a 2025, com os extremos aparados nos percentis 5 e 95. O valor do alimentador é a média ponderada dos
  conjuntos que ele atende, pelo peso de cada conjunto no CHI do alimentador;
* visão social: `R$/CHI = kW médio por UC × custo da energia não suprida (R$/MWh) / 1000`, com o kW médio da
  BDGD limitado a 5 kW. O custo da energia não suprida (R$ 7.000/MWh) é parâmetro de cenário, não valor oficial.

**Risco anual** do alimentador f: `R(f) = Σ_modos E[CHI(f, modo)] × R$/CHI(f)`.

**Efeito de um pacote de intervenções** (`otimizacao.py`): por modo de falha,
`CHI_residual = E[CHI] × Π_i (1 − alcance_i × eficácia_i(modo))`. A combinação multiplicativa evita contar duas
vezes o mesmo CHI evitado quando duas obras atuam no mesmo modo.

**VPL do pacote**: `VPL = (benefício anual − capex anualizado − opex anual) × fator de anuidade(8%, 10 anos)`,
com `benefício anual = CHI evitado × R$/CHI` e o capex anualizado pela vida útil de cada item. Anualizar evita
penalizar obras de vida longa (rede compacta, 30 anos) num horizonte de 10 anos.

**Carteira ótima**: mochila de escolha múltipla resolvida por programação inteira (CBC):
`max Σ VPL(f,p)·y(f,p)` sujeito a `Σ custo(f,p)·y(f,p) ≤ orçamento` e no máximo um pacote por alimentador.

## 5. Desenho de validação

* **Por que point-in-time.** O planejamento é feito no fim do ano *y-1* para o ano *y*. Qualquer informação
  publicada depois disso (cadastro de *y*, vínculos de circuitos refeitos depois) dá ao modelo uma vantagem que
  ele não terá na prática. Por isso todas as features do ano *y* vêm de snapshots até *y-1*
  (`features.falhas_point_in_time`, testado em `tests/test_features.py`). A ablação mostra que a versão sem esse
  corte tinha erro de CHI 2,6% menor, ou seja, um resultado otimista.
* **Backtest de origem móvel.** Para testar 2023, o modelo treina até 2022; para 2024, até 2023; e assim por
  diante. Nenhum ano de teste é visto no treino.
* **Baselines de planejamento.** "Média dos últimos 3 anos" e "o ano passado se repete". São as regras que um
  planejamento sem modelo usaria; ganhar delas é o mínimo para o modelo ter utilidade.
* **Baselines de carteira.** "Pior primeiro + pacote padrão" (a regra tradicional) e "guloso por VPL/custo".
* **Checagem parcial de 2026.** Previsão de 2026 comparada com as falhas observadas de janeiro a julho
  (Spearman de 0,83), com cobertura de vínculo de 77%.

## 6. Premissas

| Premissa | Valor | Fonte | Peso no resultado |
|---|---|---|---|
| Custo da energia não suprida | R$ 7.000/MWh | cenário | define o tamanho da visão social |
| Taxa de desconto e horizonte | 8% a.a., 10 anos | cenário | escala o VPL |
| Religador: custo, alcance × eficácia | R$ 160 mil/un.; 0,5 × 0,45 = −22,5% no CHI | catálogo ilustrativo | alto; **medido no `automation-impact`: −16,6%** |
| Automação (telecomando + FLISR) | R$ 85 mil/un.; 0,6 × 0,35 = −21% | catálogo ilustrativo | alto; **medido: sem efeito (+1,7%)** |
| Rede compacta, para-raios, poda, preditiva | ver `configs/intervencoes.yaml` | catálogo ilustrativo | médio; ainda não medidos |
| R$/CHI de compensação | empírico por conjunto | dados ANEEL 2022-2025 | aproximação linear de uma regra não linear |

## 7. Sensibilidade

`scripts/sensibilidade_eficacias.py` troca as eficácias de religador e automação pelas medidas no
`automation-impact` (efeito central e limites do IC 95% do religador; automação sem efeito) e refaz a carteira de
R$ 20 mi. Resultado (`reports/sensibilidade_eficacias.csv`), visão social:

| Cenário | VPL ótima | VPL tradicional | Ótima ÷ tradicional |
|---|---|---|---|
| Catálogo | R$ 108 mi | R$ 46 mi | 2,3× |
| Medido (central) | R$ 53 mi | R$ 22 mi | 2,5× |
| Religador no limite inferior do IC | R$ 17 mi | R$ 2 mi | 7,7× |
| Religador no limite superior do IC | R$ 86 mi | R$ 39 mi | 2,2× |

O valor absoluto depende muito das eficácias; a vantagem relativa de otimizar não.

## 8. Como interpretar cada resultado

* **Validação do DEC:** garante que a base é a mesma da ANEEL. Não diz nada sobre a qualidade da previsão.
* **Backtest:** diz quanto a previsão erra em anos que o modelo não viu. O erro por alimentador × modo é o que
  importa para escolher a obra; o ranking total de alimentadores é quase o mesmo do histórico.
* **Risco em R$:** é a perda esperada se nada for feito, nas duas visões. A de caixa é medida; a social depende
  do custo da energia não suprida.
* **Carteira e VPL:** comparam estratégias com as mesmas premissas. O número absoluto não é orçamento; a
  diferença entre estratégias e o mix de obras é a informação útil.
* **Mix da carteira:** muda com as eficácias. Com as eficácias medidas, o telecomando sai da carteira; isso é
  uma hipótese a confirmar com o histórico de obras da distribuidora, não uma recomendação de desligar a
  automação existente.
