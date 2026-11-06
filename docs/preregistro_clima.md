# Pré-registro: o clima do INMET entra no modelo?

**Escrito em 06/11/2026 e enviado ao GitHub antes de treinar qualquer modelo com as colunas de clima.** O
horário do envio (histórico do repositório) é a evidência de que a regra não foi ajustada depois do resultado.

## Pergunta
O README dizia que o clima do INMET ficou de fora porque o portal recusou conexões, e que bastava rodar
`scripts/build_clima.py` para incluí-lo. O portal respondeu nesta execução. A pergunta agora é se o clima
**melhora a validação** a ponto de justificar entrar no modelo, ou se é só mais coluna.

## O que já foi feito antes deste registro
* Baixei os 8 anos do INMET (2018 a 2025) e rodei `scripts/build_clima.py` sem alterar o código: 45 estações de
  MT, 3.614 estação-mês, 461.856 linhas alimentador x mês. A cobertura de chuva válida por alimentador-mês vai de
  75% (2021) a 99,6% (2019). Nenhuma estatística de clima foi cruzada com falhas.
* Medi o ruído do modelo **sem clima**: 10 sementes do LightGBM (0 a 9) no backtest 2023-2025, com os arquivos
  da ANEEL de 06/11/2026 e a correção das linhas repetidas (branch `melhoria/dedup-continuidade`).
* **Nenhum modelo foi treinado com clima.**

## O experimento
Só uma coisa muda entre os dois lados: a presença das 8 colunas `clim_*` que `features._climatologia` já
calcula (média dos 5 anos anteriores ao ano alvo, nas coordenadas do snapshot *y-1*). Painel, hiperparâmetros,
backtest (origem móvel, anos de teste 2023, 2024 e 2025) e métricas são os do pipeline atual. Nada é ajustado
para o clima. Cada lado roda nas sementes 0 a 9. O script é `scripts/experimento_clima.py` e a regra está em
`src/gridrisk/regra_clima.py` (com testes em `tests/test_regra_clima.py`).

## Linha de base (sem clima, 10 sementes, média dos anos de teste)
| Métrica (README) | Média das 10 sementes | Desvio-padrão entre sementes | Semente 0 (a do pipeline) |
|---|---|---|---|
| Deviance de Poisson (falhas) | 6,1278 | 0,0138 | 6,1460 |
| Erro absoluto do CHI por alimentador | 16.193 | 61,5 | 16.257 |
| Spearman do ranking de CHI | 0,9059 | 0,0005 | 0,9062 |
| CHI capturado pelos 10% priorizados | 0,4570 | 0,0019 | 0,4572 |

O desvio-padrão entre sementes é o ruído do modelo: mudar só a semente (ou a ordem das linhas) move o erro do
CHI em ~0,4%. O número que o README publicava antes (16,2 mil) está dentro dessa faixa.

## Regra de decisão (todas as condições valem ao mesmo tempo)
Seja Δ a diferença entre a média das 10 sementes com clima e sem clima.

1. **Deviance de Poisson:** melhora de pelo menos max(1% da linha de base; 2 desvios-padrão), isto é,
   Δ ≤ -0,0613 (com clima ≤ 6,066).
2. **Erro absoluto do CHI:** melhora de pelo menos max(1%; 2 desvios-padrão), isto é, Δ ≤ -161,9 (com clima ≤ 16.031).
3. **Spearman:** não pode piorar mais que 2 desvios-padrão (Δ ≥ -0,0010).
4. **CHI capturado no top 10%:** não pode piorar mais que 2 desvios-padrão (Δ ≥ -0,0038).
5. **Consistência:** deviance e erro absoluto do CHI melhoram (média das sementes) em pelo menos 2 dos 3 anos
   de teste.
6. **Sentido do pipeline:** com a semente 0, que é a que o pipeline publica, deviance e erro absoluto do CHI
   também ficam menores com clima.

Se todas valerem, o clima entra no modelo por padrão. Se alguma falhar, o padrão continua sem clima.

A checagem parcial de 2026 (Spearman de jan a jul) é só informativa: usa um cadastro incompleto e não entra na
decisão.

## O que será publicado em qualquer resultado
* `reports/experimento_clima_sementes.csv` (todas as linhas) e `reports/experimento_clima.json` (a conta de cada
  critério), gerados pelo script acima.
* O README passa a dizer o que foi testado e o resultado, **mesmo que o clima não ajude**.
* Se o clima **não** passar: o padrão continua sem clima, agora por uma chave explícita de configuração (rodar
  `build_clima.py` deixa de mudar o modelo em silêncio) e os números canônicos de `reports/` não mudam.
* Se o clima passar: o pipeline inteiro (backtest, ablação, SHAP, carteira, sensibilidade, resumo e figuras) é
  regenerado com clima, e todo número do README sai desses arquivos. A tabela mostrará a versão publicada antes,
  a regenerada sem clima e a regenerada com clima, para não misturar o efeito do clima com a variação do modelo.

Qualquer outra variante do experimento (outras colunas de clima, outros hiperparâmetros, mais sementes) exige um
novo pré-registro.
