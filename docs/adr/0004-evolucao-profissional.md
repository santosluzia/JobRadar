# ADR 0004 — Minha Evolução Profissional

- **Status:** aceito (Etapa 4)
- **Data:** 2026-11-12

## Contexto

O diagnóstico da Etapa 3 mostra onde você está. A Etapa 4 pede um plano contínuo, com cinco requisitos:
- priorizar sem recomendar todas as lacunas;
- classificar as competências em 7 grupos;
- dar recomendações práticas ligadas às vagas;
- controlar o progresso;
- atualizar o diagnóstico quando o perfil muda.

Já existiam recomendações de estudo (`recommendations/study.py`), com amostra mínima e tendência de
90 contra 90 dias, mas elas tinham 4 classes, liam só o perfil e marcavam como prioritária toda lacuna
acima de 15%. O progresso de estudos guardava só o estado atual e não afetava nada.

## Decisão

1. **Prioridade explicável** (`evolucao/plano.py`): soma ponderada de 7 fatores entre 0 e 1, com pesos
   em `scoring.yaml → evolucao` e a decomposição sempre exposta.

   | Fator | Como é medido |
   |---|---|
   | frequência | % das vagas-alvo que pedem a competência |
   | exigência obrigatória | % das vagas-alvo que a pedem como requisito |
   | crescimento | variação contra o período anterior; vale 0 enquanto não há amostra nos dois |
   | compatibilidade com o cargo | % no objetivo ÷ (% no objetivo + % nas demais vagas) |
   | senioridade | frequência nas vagas das senioridades do objetivo |
   | esforço | menor esforço estimado pesa mais |
   | comprovação prática | dá para demonstrar num projeto de portfólio |

   Frequência, exigência e senioridade são **relativas à competência mais pedida no objetivo** (ela
   vale 1). Na escala absoluta, quase tudo ficava perto de 0 e o ranking era decidido por esforço e
   projeto, que são constantes por competência.
2. **Não recomenda tudo:** só as `max_prioritarias` lacunas (5) de maior prioridade, acima de
   `prioridade_minima` (0,25) e com amostra suficiente. As demais vão para "baixa relevância" com o
   motivo explícito (pouco pedida, abaixo do corte, fora das N primeiras ou amostra pequena).
3. **7 classes sem sobreposição**, avaliadas nesta ordem:

   | Classe | Regra |
   |---|---|
   | 1. Consolidada | profissional no perfil **e** comprovada no currículo |
   | 2. Comprovada em experiência profissional | comprovada no currículo, ou progresso "comprovada em experiência" com evidência |
   | 3. Demonstrada em projeto | em projeto (perfil, currículo ou progresso) |
   | 4. Declarada sem evidência suficiente | profissional no perfil sem respaldo no currículo, ou só listada no currículo |
   | 5. Em desenvolvimento | em estudo, em prática, ou só curso/conceito |
   | 6. Prioritária para aprender | as N lacunas de maior prioridade |
   | 7. Baixa relevância para o objetivo atual | demais lacunas, com o motivo |

4. **Recomendações práticas** para cada prioritária:
   - **Dos dados:** por que importa (percentual, requisito, tendência, compatibilidade), quantas vagas,
     em quais cargos (títulos sem senioridade), famílias e senioridades, e tecnologias associadas
     (coocorrência com lift de pelo menos 1,2).
   - **De `config/evolucao.yaml`**, sugestão editável e **rotulada assim**: o que estudar, o projeto e
     a evidência para o currículo. O projeto é completado com as competências que você já tem e que
     mais se associam à lacuna.
5. **Progresso** com os status da especificação, mais `pausada` como auxiliar:
   - histórico em `private/study_events`; status antigos convertidos;
   - o **perfil efetivo** é o perfil declarado mais o progresso, e **só sobe, nunca rebaixa** o nível declarado:
     - "em estudo" e "em prática" valem como em desenvolvimento;
     - "demonstrada em projeto" com evidência vale como projeto;
     - "comprovada em experiência" com evidência vale como profissional; é declaração sua, o sistema nunca infere.
   - Curso concluído **não** vira experiência profissional.
   - O perfil efetivo entra no hash do perfil: mudar o progresso faz a próxima execução recalcular
     os scores. O plano e o diagnóstico são recalculados a cada consulta.
6. **Privacidade:** o plano e o histórico ficam em `$JOBRADAR_HOME/evolucao` (fora do git). O progresso
   fica no lake privado, como antes, porque o CI precisa dele para o score.

## Consequências

- Até haver amostra no período anterior (por volta de abril de 2027, com o histórico iniciado em
  16/10/2026), o fator crescimento vale 0, e isso aparece nas notas de cada item.
- O conteúdo de estudo é opinião editável, não dado. A tela e a CLI marcam isso.
- `jobradar estudo` continua funcionando, com os status novos e os antigos convertidos.
- A página "Minha aderência e estudos" virou "Minha Evolução Profissional": Plano, Classificação,
  Progresso e Vagas pontuadas.
