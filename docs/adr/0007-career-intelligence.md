# ADR 0007 — Diagnóstico mensal e área Career Intelligence

- **Status:** aceito (Etapa 7)
- **Data:** 2026-11-15

## Contexto

A Etapa 7 pede uma área privada "Career Intelligence", com radar de mercado, compatibilidade, plano de
evolução e um diagnóstico mensal que responda 7 perguntas. Tudo com indicadores históricos e sem
confundir aumento de pontuação com garantia de empregabilidade.

Antes desta etapa, nada guardava, mês a mês, a sua aderência por objetivo.

## Decisão

1. **Retrato mensal automático** (`evolucao/mensal.py`), gravado em `private/diagnosticos_mensais` no
   dia e turno configurados (`private/radar.yaml → mensal`; padrão: dia 1, 12:00).
   - **Conteúdo:** por objetivo, aderência do perfil e do currículo, demanda do mês (peso por
     competência), níveis do perfil efetivo e do resumo do currículo, classes, prioritárias e projetos.
     Só agregados e níveis, nenhum texto de currículo.
   - **Quando grava:** sempre, mesmo com o e-mail desativado, porque é o histórico.
   - **E-mail:** sai se `ativo`. Em caso de falha, o retrato fica gravado e o envio é tentado de novo.
2. **"Minha aderência melhorou?" com decomposição exata.**

   Notação: `A(D, C)` = Σ peso × cobertura ÷ Σ peso, onde D é a demanda e C a cobertura pelos seus
   níveis (0 = mês anterior, 1 = mês atual).

   | Termo | Fórmula | Leitura |
   |---|---|---|
   | efeito do mercado | `A(D₁, C₀) − A(D₀, C₀)` | o seu perfil de antes, medido contra a demanda de agora |
   | efeito do perfil | `A(D₁, C₁) − A(D₁, C₀)` | a demanda de agora, medida contra o seu perfil de agora |

   A soma dos dois é exatamente a variação total (há teste). A aderência pode subir só porque o mercado
   passou a pedir o que você já tinha, e o diagnóstico mostra isso.
3. **As 7 perguntas:**

   | Pergunta | Como é respondida |
   |---|---|
   | 1. A aderência melhorou? | decomposição acima |
   | 2. Que competências desenvolvi? | níveis que subiram e progresso registrado no mês |
   | 3. Que lacunas continuam? | prioritárias persistentes, novas e resolvidas |
   | 4. O que mudou nas exigências? | variação ≥ 5 p.p., só com amostra mínima nos dois meses |
   | 5. Quais projetos agregam mais? | os das 3 prioridades, combinados com o que você tem |
   | 6. O currículo demonstra melhor? | aderência do resumo do currículo medida contra a **mesma** demanda, e "declaradas sem evidência" |
   | 7. Quais objetivos são mais compatíveis? | ranking dos objetivos, com amostra pequena por último |

   Todas trazem o aviso de que pontuação não é garantia de emprego.
4. **Painel reorganizado em duas seções:**
   - **Mercado:**
     - Visão geral;
     - Vagas;
     - **Radar de mercado**: a página Mercado de antes, mais competências emergentes (30 × 30 dias e
       primeiras aparições), comparação por cargo (mapa de calor família × competência, com n ≥ 10) e
       distribuição dos requisitos (requisito × desejável e competências por vaga).
   - **Career Intelligence:**
     - **Minha compatibilidade** (nova): objetivos lado a lado, por senioridade e por família, o que somou e
       o que faltou, evolução entre versões do currículo (cada versão contra a mesma demanda) e "como o mercado
       mudou em relação ao que você sabe hoje";
     - **Minha Evolução Profissional**: nova aba com atividades planejadas, projetos em andamento,
       evidências adquiridas e recomendações futuras;
     - **Meu currículo**;
     - **Relatório semanal**;
     - **Diagnóstico mensal** (nova): o mês corrente sob demanda, o histórico de retratos e o gráfico de
       aderência por objetivo.
5. **Sem passado pessoal inventado.**
   - A série pessoal começa no primeiro retrato.
   - A série de mercado recalculada para meses passados usa o **perfil atual** e é rotulada assim: mostra
     só a mudança da demanda.

## Consequências

- A primeira comparação mês × mês completa sai em 01/12/2026 (novembro × outubro, este parcial desde 16/10).
- Os números do diagnóstico mensal usam a demanda dos últimos 30 dias; os do plano usam 90 dias. Os
  dois aparecem rotulados.
- **Privacidade:**
  - o retrato vive no repositório privado;
  - o painel é local, e a página "Minha compatibilidade" lê as versões locais do currículo;
  - o diagnóstico no CI não lê `~/.jobradar` (há teste), e o log só recebe contagens.
