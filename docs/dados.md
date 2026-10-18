# Decisões de dados

Registro das escolhas de tratamento que afetam os resultados, com a evidência de cada uma.

## Interrupções (ANEEL)

**Fonte:** `dadosabertos.aneel.gov.br`, dataset *Interrupções de Energia Elétrica nas Redes de
Distribuição*, Parquet anual.

### Dois layouts
| | Legado (2017-2025) | Novo (2026+) |
|---|---|---|
| Fato gerador | `DscFatoGeradorInterrupcao` = `ORIGEM-TIPO-CAUSA-DETALHE` | 4 colunas separadas |
| Expurgo | `IdeMotivoInterrupcao` (código) | `DscMotivoExpurgo` (texto) |
| Alimentador | código operacional (`CTMT.NOME`, ex. `013014`, às vezes sem zero à esquerda) | `CTMT.COD_ID` |
| Elemento interrompido | não existe | `DscTipoElementoInterrompido` |

O dicionário publicado (v1.0, jul/2026) só descreve o layout novo.

### Domínio inferido de `IdeMotivoInterrupcao`
Para a mesma distribuidora, comparei o perfil de cada código legado (2025) com o layout novo (2026):

| Código | UCs afetadas (média) | % BT | Causa dominante | Mapeado para |
|---|---|---|---|---|
| 0 | 53 | 77% | falha de material | Não houve expurgo |
| 1 | 1,06 | 94% | não classificada | Falha nas instalações da UC sem afetar terceiros |
| 6 | 71 | 72% | descarga atmosférica | Dia crítico |
| 3 | 171 | 36% | descarga atmosférica | ISE por meio de CHI |
| 8 | 1.172 | 0% | externa | Origem externa ao sistema de distribuição |
| 7 | 1.709 | 24% | alívio de carga | Racionamento / alívio de carga |
| 2 | 1,2 | 18% | programada p/ melhoria | Obras de interesse exclusivo do usuário |

**Validação:** com esse mapeamento, o DEC/FEC recalculado bate com o oficial em todos os anos de 2020 a
2026 (ver `reports/validacao_dec_fec.csv`).

### Modos de falha
As grafias variam entre os anos (por exemplo, `FALHA MAT OU EQUIPA` e `FALHA DE MATERIAL OU EQUIPAMENTO`).
As causas foram agrupadas em: equipamento, descarga atmosférica, vegetação, vento, animais, terceiros e
outras/não identificada. O alvo do modelo são as **interrupções não programadas, de origem interna e
iniciadas na média tensão** (1 kV ≤ V < 69 kV).

## BDGD

**Fonte:** ArcGIS Hub da ANEEL (`dadosabertos-aneel.opendata.arcgis.com`). Um File Geodatabase por
distribuidora e ano. Os IDs dos itens usados estão em `configs/emt.yaml`.

* **Modelo M10 (até 2020) e V10/V11 (2021+):** `UNTRMT` se chamava `UNTRD`, `CTMT.NOME` se chamava `NOM` e
  `SSDMT.CT_COD_OP` não existia. O leitor trata os dois modelos.
* **Chave do alimentador:** o `CTMT.COD_ID` muda entre snapshots (nenhum ID de 2021-2022 aparece em 2025),
  enquanto o código operacional `CTMT.NOME` é estável (98,6% dos nomes de 2021 seguem em 2025). O painel usa
  o nome como chave canônica.
* **Mapa código operacional → circuito:** um CTMT pode agrupar vários códigos operacionais (ex.: o
  circuito `2014290` contém `092001`, `092002`, `092011` e `093013`). O mapa vem de `SSDMT.CT_COD_OP`: cada
  código vai para o CTMT com a maior extensão de rede com aquele código. Para eventos de anos sem
  `CT_COD_OP`, vale o snapshot mais próximo que tenha o campo.
* **Sem vazamento:** a linha do ano *y* usa o snapshot de 31/12/*y-1*.
* **Idade fora do modelo:** `DAT_CON` tem 7% de `01/01/1980` (data-padrão), um pico de 35 mil trafos em 2017
  (recadastramento) e idades médias de ~90 anos nos snapshots M10, o que é implausível. Usar essa coluna
  ensinaria o modelo a reconhecer o processo de cadastro, não o envelhecimento do ativo.
* **Domínios usados** (Manual BDGD rev. 5, anexo II): `TUNI` 32 = religador, 35/36 = seccionalizador,
  22-27 = chaves fusíveis; `TCABOGTCEOM` 1 = aérea compacta; `TCABOISO` 12 = nu; `TARE` NU = não urbano.

## Clima (INMET)

`portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip`, com as estações automáticas de MT (45 com dado no
período). Agregação mensal: chuva total, máxima horária, horas com chuva ≥ 10 mm, dias com ≥ 50 mm, rajada
máxima, dias com rajada ≥ 15 m/s, temperatura e umidade. Meses com menos de 60% das horas válidas são
descartados. A interpolação para o centróide do alimentador (mediana dos trafos) usa IDW das 3 estações mais
próximas com dado, num raio de até 250 km.

No modelo anual de planejamento entra só a **climatologia** (média dos 5 anos anteriores), porque o clima
realizado do ano-alvo não é conhecido na hora de decidir.

## Compensações

`indicadores-continuidade-coletivos-compensacao`: soma dos indicadores `PG*` (valor pago por violação
mensal, trimestral e anual de DIC/FIC/DMIC, DICRI e DISE) por conjunto, dividida pelo CHI regulatório do
conjunto (2022-2025). O valor do alimentador é a média ponderada pela participação de cada conjunto no CHI
dele. Média da empresa: **R$ 2,10 por CHI**.

## 2026
As interrupções de 2026 trazem IDs de circuito de um cadastro ainda não publicado. 23% dos eventos de MT
não encontram correspondência em nenhuma BDGD disponível, então 2026 serve só como checagem parcial de
ranking.
