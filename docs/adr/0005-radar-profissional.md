# ADR 0005 — JobRadar — Seu Radar Profissional (e-mail diário)

- **Status:** aceito (Etapa 5)
- **Data:** 2026-11-12

## Contexto

O e-mail existente avisa vagas novas a cada turno de 6 h. A Etapa 5 pede um resumo diário em 4 blocos
(mercado, relação com o perfil, oportunidade e uma ação do dia), personalizado e com histórico, sem
repetição e com configuração privada.

O problema central é que o currículo vive só na sua máquina (`~/.jobradar`), mas o e-mail sai do CI.

## Decisão

1. **Onde roda:** no workflow atual, no turno configurado.
   - O Radar **substitui** o e-mail desse turno e já leva as vagas novas; os outros turnos continuam
     como alerta de vagas.
   - A mudança de todas as partes privadas para um workflow no repositório privado fica para a Etapa 8.
   - O log só recebe contagens (há teste).
2. **Currículo no CI só por adesão:** `jobradar curriculo compartilhar-resumo` grava em
   `private/curriculo_resumo.json` apenas `{competência: nível}`, a versão, a data e a versão da taxonomia.
   Não grava texto, empresa, frase nem período, e `remover-resumo` apaga.
   - Sem o resumo, o Radar usa o perfil e o progresso, e avisa isso no próprio e-mail.
   - O Radar nunca lê `~/.jobradar` (há teste).
3. **Conteúdo**, a partir do plano da Etapa 4:

   | Bloco | O que mostra |
   |---|---|
   | 1. Mercado | vagas novas do objetivo (com o score dele) e volume da semana × semana anterior; tendência de 14 dias contra os 28 anteriores, só com pelo menos 30 vagas em cada janela e variação de 5 p.p. (senão o e-mail diz por quê); competências que não apareciam nos 30 dias anteriores, com pelo menos 2 vagas; requisitos que se repetem |
   | 2. Perfil | das competências pedidas nas vagas de referência (as novas, ou a última semana se forem menos de 3): o que você demonstra, o que precisa de melhor apresentação (só com o resumo do currículo), lacunas prioritárias e novas exigências |
   | 3. Oportunidade | uma vaga concreta, com link, em que faltam 1 ou 2 requisitos e o que falta é prioridade sua |
   | 4. Ação do dia | **uma** ação: estudar um conceito, fazer uma pequena atividade, atualizar um projeto, melhorar o currículo ou documentar uma experiência |

4. **Regras da ação do dia:**
   - respeita o progresso: em estudo recebe prática; em prática recebe publicar e registrar;
   - não repete o mesmo par (tipo, competência) dentro de `nao_repetir_dias`;
   - evita repetir o tipo de ontem;
   - roda os tópicos de estudo, e "documentar" só aparece com o resumo do currículo.
5. **Contra repetição:**
   - tendência ou tecnologia nova apontada nos últimos 3 dias não volta sem mudança;
   - seção sem conteúdo é omitida;
   - a fila de candidatas (Etapa 1) ficou **fora** do e-mail: o teste com dados reais trouxe termos
     como "pessoa engenheira" e "tables", ruído que fere a regra de enviar só o que é relevante.
6. **Configuração privada** em `private/radar.yaml` (modelo em `config/radar.example.yaml`), validada
   por Pydantic: ativo, horário (precisão de turno), dias da semana, frequência (diária, dias úteis ou
   semanal), objetivo, limite de itens, intervalo sem repetição e janelas de tendência.
7. **Histórico e falhas** em `private/radar_envios`:
   - um Radar por dia e por objetivo;
   - falha de envio fica registrada como `falha` e não marca as vagas como enviadas, então o próximo
     turno do mesmo dia tenta de novo;
   - `--forcar` ignora horário e duplicidade, e `--dry-run` gera a prévia sem enviar nem registrar.

## Consequências

- **Primeiro deploy:** sem `private/radar.yaml`, valem os padrões (ativo, 06:00, todos os dias). O
  e-mail da manhã passa a ser o Radar. Para manter o e-mail antigo, use `ativo: false`.
- **Horário:** tem precisão de turno de 6 h, porque os disparos são os do cron-job.org (00, 06, 12, 18).
- **Tendência:** com o volume atual (cerca de 120 vagas de engenharia em 14 dias), a tendência sai
  quando a variação passa de 5 p.p.; o e-mail informa quando não há variação ou não há amostra.
- **Custo:** o Radar leva cerca de 10 s no CI, com o mesmo SMTP e o mesmo custo zero.
