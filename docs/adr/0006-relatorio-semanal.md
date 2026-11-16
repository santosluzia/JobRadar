# ADR 0006 — Relatório Semanal de Evolução Profissional

- **Status:** aceito (Etapa 6)
- **Data:** 2026-11-15

## Contexto

A Etapa 6 pede um relatório semanal mais aprofundado que o Radar diário:
- 10 seções;
- comparações históricas, sempre que houver dados;
- as três principais oportunidades de evolução, sem lista excessiva de cursos;
- envio por e-mail e consulta na área privada.

## Decisão

1. **Um e-mail separado** do Radar, configurado em `private/radar.yaml → semanal` (ativo, dia, horário,
   objetivo e limite). O padrão é segunda-feira, 12:00. O `notify` o envia no turno e no dia dele, sem
   substituir o Radar nem o alerta de vagas. Falha do semanal não impede o e-mail do turno.
2. **Conteúdo** (`notifications/semanal.py`), todas as seções sempre presentes, ditas vazias quando não há dados:

   | # | Seção | Conteúdo |
   |---|---|---|
   | 1 | Resumo do mercado | vagas novas no mercado de dados e no objetivo (semana × semana anterior) e vagas encerradas |
   | 2 | Vagas analisadas | o `n` de cada recorte e o mínimo usado para comparar proporções |
   | 3 | Mais exigidas | últimos 30 dias, **objetivo × mercado de dados** (barras em HTML) |
   | 4 | Em crescimento | semana × semana (objetivo e mercado) e 30 × 30 dias, cada uma só com o mínimo de vagas nas duas janelas; senão, o motivo |
   | 5 | Combinações | pares de maior Jaccard no objetivo (90 dias) e "pontes": algo que você tem associado a uma prioridade, com lift de pelo menos 1,2 |
   | 6 | Perfil | aderência do perfil e do currículo e contagem por classe, comparadas com o relatório anterior |
   | 7 | Lacunas prioritárias | as do plano, e quais entraram ou saíram desde a semana passada |
   | 8 | Currículo | documentar o que você declara e o currículo não mostra; citar pelo nome o que só aparece de forma indireta; versão atual × anterior do resumo de níveis |
   | 9 | Projetos sugeridos | só os das 3 oportunidades |
   | 10 | Progresso das recomendações anteriores | ações do Radar dos últimos 7 dias e as 3 oportunidades da semana passada, cruzadas com `study_events` posteriores ("avançou" ou "sem progresso registrado") |

   **Fechamento:** as **3 principais oportunidades** (as primeiras prioritárias do plano), com o porquê,
   o projeto e a evidência para o currículo. Quando uma se repete, o relatório diz há quantas semanas e
   se houve progresso.
3. **Histórico** em `private/relatorios_semanais`, com semana ISO, objetivo, status, as 3 oportunidades
   e um resumo de métricas. Ele é a base das comparações "contra a semana passada" e do acompanhamento.
   Sai um relatório por semana e por objetivo; falha fica registrada e não conta como envio.
4. **Versões do currículo no CI:** `compartilhar-resumo` passa a acumular um resumo por versão em
   `private/curriculo_resumos_historico.json`, sempre só níveis e por adesão. `remover-resumo` apaga
   também o histórico.
5. **Área privada:** a página **Relatório semanal** do painel gera o relatório da semana sob demanda,
   permite baixar o HTML e mostra o histórico com a evolução da aderência.

## Consequências

- Com o volume atual, a comparação semana × semana costuma ter amostra no mercado de dados, mas nem
  sempre no objetivo. A de 30 × 30 dias fica disponível por volta de meados de dezembro de 2026.
- O relatório leva cerca de 8 s no CI e tem cerca de 20 KB.
- Como o Radar, roda no workflow atual, não lê `~/.jobradar` (há teste) e o log recebe só contagens.
