# ADR 0013 — Qualidade por fonte e detecção de mudança de formato

- **Status:** aceito (PR E da evolução para inteligência de mercado)
- **Data:** 2026-11-18

## Contexto

O monitoramento (`analytics/saude.py`, Etapa 8) já via falhas de execução, cobertura da extração e
registros inválidos. Mas não comparava as fontes entre si e só percebia uma mudança de formato depois do
estrago, quando a silver já tinha campos vazios ou registros inválidos. A Gupy é o caso de risco: não
tem API documentada, e em 2026-10 a rota mudou sem aviso.

A análise de 2026-11-18 mostrou o tamanho do problema. A Adzuna era 92% do volume, mas só 31% das vagas
dela eram de dados, e todas vinham com descrição truncada. Uma nota por fonte deixa isso visível sem
depender de investigação manual.

## Decisão

1. **Assinatura de formato** (`collectors/assinatura.py`): a cada execução e fonte, os caminhos de campo
   dos registros brutos (`location.name`, `departments[].name`…) com tipo e presença. Só nomes e tipos,
   nunca valores. Fica em `meta/schema_assinaturas`.
2. **Mudança grave** é quando um **campo essencial** some, cai 30 pontos de presença ou troca de tipo.
   Campo essencial é o que o `to_raw_job` usa (`CAMPOS_ESSENCIAIS` em cada coletor).
   - Campos novos, removidos ou com tipo trocado fora dos essenciais ficam registrados, sem alerta.
   - **Faixa de tolerância:** novo = estava abaixo de 5% e passou a ter ao menos 25% de presença;
     removido = o contrário. Sem a faixa, os campos de salário e de contrato da Adzuna (~9% das vagas)
     geravam 32 "mudanças" falsas em 90 dias de bronze. Com ela, nenhuma.
   - Amostra com menos de 5 registros não é comparada.
3. **Alerta:** mudança grave aparece em `jobradar saude` (resumo do Actions e rodapé do Radar) por 24 horas
   e no log da execução. O relatório da execução ganha `formatos_alterados`. Na execução seguinte, o formato
   novo vira a referência: o alerta não se repete para sempre.
4. **Referência inicial:** sem histórico, a 1ª execução monta a referência com a bronze dos últimos 14 dias
   (cerca de 30 s, uma vez só). `jobradar qualidade reconstruir-formato` refaz tudo com os 90 dias.
5. **Qualidade por fonte** (`analytics/qualidade_fontes.py`): indicadores calculados sobre as vagas vistas
   pela primeira vez nos últimos 30 dias (padrão), sempre com n.
   - **Indicadores:** disponibilidade, registros válidos, relevância (família de dados), descrição completa
     (≥ 1.000 caracteres), campos (empresa, data, local e modalidade) e extração (ao menos uma competência).
   - **Exclusivas:** % das vagas que só aquela fonte trouxe. Fica fora da nota: mede contribuição, não
     qualidade.
   - **Nota de 0 a 100:** média ponderada. Pesos: relevância 25, disponibilidade 20, descrição 15,
     campos 15, extração 15 e válidos 10.
   - **Amostra pequena:** com menos de 30 vagas, a nota fica marcada como `amostra_pequena`.
6. **Onde aparece:** `jobradar qualidade [fontes|formato|reconstruir-formato]` e a seção nova do
   `jobradar saude`. Ela já vai para o resumo do Actions, sem mudar o workflow.

## Consequências

- **Retrato de 2026-11-18** (30 dias, antes do PR #10 fazer efeito):

  | Fonte | Nota | Vagas | Relevância | Descrição completa |
  |---|---|---|---|---|
  | Lever | 93,2 | 38 | 79% | 97% |
  | Gupy | 92,6 | 343 | 77% | 98% |
  | Greenhouse | 85,4 | 32 | 50% | 100% |
  | Adzuna | 52,8 | 9.464 | 31% | 0% |

  A relevância de 50% no Greenhouse vem das vagas de ciência de dados, que passam no filtro de título e
  caem em `outra` (fora do escopo das famílias).
- **Custo:** a tabela ocupa ~25 KB para 90 dias; cada execução custa alguns milissegundos. A
  reconstrução completa leva ~70 s e só roda sob comando.
- **Ajuste de essenciais:** coletor novo precisa declarar `CAMPOS_ESSENCIAIS`. Um teste garante que todos
  declaram ao menos `id`.
- **Limites:** a nota resume, não substitui os indicadores. Os pesos são uma escolha e podem ser revistos
  quando houver mais fontes. Mudança de **semântica** sem mudança de campo (exemplo: a fonte passa a
  mandar outra data em `publishedDate`) não é detectada.
