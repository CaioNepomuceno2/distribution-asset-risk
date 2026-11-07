# Model card: frequência de falhas e CHI por alimentador

> **Este documento descreve a Energisa MT.** A Energisa MS usa o mesmo método com a configuração [`configs/ems.yaml`](../configs/ems.yaml); as decisões e os resultados de MS estão em [`decisoes_ems.md`](decisoes_ems.md) e [`resultados_ems.md`](resultados_ems.md).

## Uso pretendido
Priorizar alimentadores e modos de falha para o **planejamento anual** de investimento e manutenção em
redes de média tensão. O modelo **não** foi feito para prever o DEC do ano, que depende do clima realizado,
nem para operação em tempo real.

## Unidade e alvo
* Linha: alimentador (código operacional) × ano × modo de falha (7 modos).
* `n_falhas`: nº de interrupções não programadas, internas e originadas na MT. LightGBM com objetivo Poisson.
* `chi`: consumidor-hora interrompido dessas falhas. LightGBM com objetivo Tweedie (p = 1,4).
* A previsão de produção é a média de 5 sementes.

## Features e disponibilidade temporal
Todas as features do ano *y* usam só informação disponível em 31/12 de *y-1*: o cadastro, o crosswalk de
circuitos e as coordenadas da interpolação climática vêm de snapshots até *y-1* (ver `tests/test_features.py`).
* **Rede (BDGD y-1):** extensão MT, fração rural, monofásica, compacta, subterrânea e de cabo nu; nº de
  trafos, kVA, fração MRT; religadores, seccionalizadores, chaves fusíveis e telecomandadas; consumidores,
  fração rural, GD; centróide e extensão geográfica; densidades por km.
* **Histórico até y-1:** falhas e CHI do mesmo modo (1 e 3 anos), totais em 3 anos, tendência, duração
  mediana de restabelecimento.
* **Climatologia:** médias dos 5 anos anteriores (chuva, rajadas, temperatura, umidade). **Desligada** por
  padrão (`modelo.usar_clima: false`): no experimento pré-registrado ela piorou o backtest (README, seção 6).
* **Excluídas de propósito:** idades da BDGD (ver `docs/dados.md`) e qualquer informação do ano-alvo.

## Avaliação
Origem móvel: os anos de teste 2023, 2024 e 2025 são previstos, cada um, com treino apenas nos anos
anteriores. Execução de nov/2026, reproduzida das fontes brutas com cortes temporais e sem a climatologia do INMET
(testada e descartada pela regra pré-registrada em `docs/preregistro_clima.md`).

| | Modelo | Média 3 anos | Ano anterior |
|---|---|---|---|
| Deviance de Poisson (falhas) | 6,1 | 15,5 | 23,0 |
| MAE do CHI por alimentador | 16,2 mil | 17,9 mil | 17,1 mil |
| Spearman do CHI por alimentador | 0,91 | 0,88 | 0,89 |
| Captura do top-10% (CHI) | 46% | 46% | 45% |
| Viés total médio (CHI) | -0,4% | +11,9% | +5,4% |

Sem os cortes temporais no crosswalk, o mesmo modelo tinha deviance 6,07 e MAE de 15,8 mil: o vazamento
inflava o erro do CHI em ~2,6% e não mudava a conclusão.

Por ano, o viés total do CHI oscila entre -18% e +13% por causa do clima (2025 teve mais falhas que 2024). Isso é
esperado, porque o modelo não vê o clima do ano-alvo.

## Limitações e riscos
* **Sem climatologia:** testada e descartada (piorou deviance, erro do CHI e Spearman; `reports/experimento_clima.json`).
  Para ligá-la, rodar `build_clima.py` e trocar `modelo.usar_clima` em `configs/emt.yaml`.
* **Associação, não causalidade:** o SHAP mostra o que o modelo usa, não o efeito de mudar a rede. As
  eficácias das intervenções são premissas de engenharia (`configs/intervencoes.yaml`).
* **Qualidade cadastral:** classificação de causa (40% do CHI em "falha de material ou equipamento") e
  cadastro de equipamentos dependem dos processos da distribuidora.
* **Mudanças de topologia:** alimentadores criados ou divididos ficam com histórico curto. O modelo cai
  para atributos da rede, com maior incerteza.
