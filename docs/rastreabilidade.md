# Rastreabilidade e monitoramento

Como responder "de onde veio este número?" e "a operação está saudável?".

## 1. De onde veio cada dado

| Pergunta | Onde olhar |
|---|---|
| Qual execução trouxe esta vaga? | `silver/jobs.ultima_execucao` e `silver/observations` (uma linha por vaga e execução) |
| Qual resposta bruta originou a vaga? | `bronze/<fonte>/` da execução (90 dias) |
| Por que esta competência foi extraída? | `silver/job_skills`: `evidencia` (a frase), `metodo` (termo · conceito), `confianca`, `posicoes`, `taxonomia_versao` |
| Qual régua de taxonomia valia? | `silver/jobs.taxonomia_versao`; versões e mudanças em `config/skills.yaml` e docs/taxonomia.md |
| Qual perfil gerou este score? | `gold/job_scores.perfil_hash` e `objetivo_id`; `calculado_em` |
| O que foi validado nesta execução? | `meta/validacoes` (contrato público, taxonomia) e `private/validacoes` (perfil, radar.yaml) |
| O que foi enviado e quando? | `meta/notifications`, `private/radar_envios`, `private/relatorios_semanais`, `private/diagnosticos_mensais` |
| O que mudou no lake? | o histórico de commits do `jobradar-data` (um commit por execução) |
| Qual versão do contrato público? | `manifest.json` (`schema_version`, `run_id`, `generated_at`) |

## 2. Validações registradas

Cada execução grava uma linha por artefato validado:

| Artefato | Quando | Tabela |
|---|---|---|
| `taxonomia` | `jobradar run` e `jobradar pontuar` | `meta/validacoes` |
| `contrato_publico` | `jobradar publish` (passou ou não; com contagem de erros) | `meta/validacoes` |
| `perfil`, `radar_config` | fluxo que usa dado pessoal (`run` sem `--sem-pontuacao`, `pontuar`) | `private/validacoes` |

Colunas: `run_id`, `artefato`, `versao`, `ok`, `erros`, `detalhe`, `em`.
O `detalhe` é curto e mascarado. Para o perfil, guarda só a contagem de erros e o primeiro campo com
problema, nunca o valor.

As tabelas pública e privada são separadas para que os dois workflows nunca gravem o mesmo arquivo
(sem conflito de push).

## 3. Saúde da operação

```bash
jobradar saude          # tabela em Markdown
jobradar saude --json   # indicadores e alertas
```

Também aparece no resumo de cada execução do Actions, na Visão geral do painel e, quando há alerta, no
rodapé do Radar.

| Indicador | Cálculo |
|---|---|
| Tempo de execução | duração da última e mediana de 7 dias (`meta/runs`) |
| Volume | observadas e novas na última execução; vagas no histórico |
| Taxa de falha | % de execuções com status `falha` em 7 e 30 dias |
| Custo de IA | US$ 0,00: extração por regras e embeddings locais (ADR 0002) |
| Extração por fonte | % das vagas canônicas dos últimos 30 dias com ao menos uma competência técnica, e média de competências por vaga |
| Duplicação | duplicatas entre fontes (última) e % de vagas não canônicas |
| Qualidade dos indicadores | % de registros inválidos (7 dias), vagas sem data de publicação e sem empresa |
| Validações | quantas e quais falharam em 7 dias |

### Alertas (`config/sources.yaml → saude`)

| Alerta | Padrão |
|---|---|
| Sem execução bem-sucedida há mais de N horas | 14 h |
| Taxa de falha em 7 dias acima de | 25% |
| Última execução mais longa que | 900 s |
| Registros inválidos em 7 dias acima de | 10% |
| Mesma fonte falhou nas últimas N execuções | 3 |
| Cobertura da extração abaixo de (fonte com 10+ vagas) | 50%; Adzuna 25%, porque a API entrega só um trecho da descrição |
| Alguma validação falhou em 7 dias | qualquer falha |

Os alertas são só agregados (nada pessoal), por isso podem aparecer no resumo público do Actions.
