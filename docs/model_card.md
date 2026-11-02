# Model card: frequência de falhas e CHI por alimentador

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
As fontes diretas são anteriores ao ano previsto, mas a construção atual do crosswalk de circuitos e
das coordenadas para interpolação climática pode usar snapshots posteriores. Portanto, a disponibilidade
de todas as features na data de previsão ainda não está garantida.
* **Rede (BDGD y-1):** extensão MT, fração rural, monofásica, compacta, subterrânea e de cabo nu; nº de
  trafos, kVA, fração MRT; religadores, seccionalizadores, chaves fusíveis e telecomandadas; consumidores,
  fração rural, GD; centróide e extensão geográfica; densidades por km.
* **Histórico até y-1:** falhas e CHI do mesmo modo (1 e 3 anos), totais em 3 anos, tendência, duração
  mediana de restabelecimento.
* **Climatologia:** médias dos 5 anos anteriores (chuva, rajadas, temperatura, umidade).
* **Excluídas de propósito:** idades da BDGD (ver `docs/dados.md`) e qualquer informação do ano-alvo.

## Avaliação
Origem móvel: os anos de teste 2023, 2024 e 2025 são previstos, cada um, com treino apenas nos anos
anteriores. Os números abaixo foram registrados em uma execução anterior e são exploratórios: o pipeline
de pré-processamento pode usar cadastros futuros, e esta revisão não reproduziu a execução completa.

| | Modelo | Média 3 anos | Ano anterior |
|---|---|---|---|
| Deviance de Poisson (falhas) | 6,0 | 15,2 | 22,7 |
| MAE do CHI por alimentador | 16,0 mil | 17,9 mil | 17,1 mil |
| Spearman do CHI por alimentador | 0,90 | 0,89 | 0,89 |
| Captura do top-10% (CHI) | 46% | 46% | 45% |
| Viés total médio (CHI) | -5,5% | +11,9% | +5,4% |

Por ano, o viés total do CHI oscila entre -19% e +11% por causa do clima (2025 teve mais falhas que 2024). Isso é
esperado, porque o modelo não vê o clima do ano-alvo.

## Limitações e riscos
* **Informação futura no pré-processamento:** o crosswalk usa outros snapshots, inclusive futuros, e as
  coordenadas de clima vêm do snapshot mais recente. Refazer por origem temporal e comparar os resultados.
* **Associação, não causalidade:** o SHAP mostra o que o modelo usa, não o efeito de mudar a rede. As
  eficácias das intervenções são premissas de engenharia (`configs/intervencoes.yaml`).
* **Qualidade cadastral:** classificação de causa (40% do CHI em "falha de material ou equipamento") e
  cadastro de equipamentos dependem dos processos da distribuidora.
* **Mudanças de topologia:** alimentadores criados ou divididos ficam com histórico curto. O modelo cai
  para atributos da rede, com maior incerteza.
