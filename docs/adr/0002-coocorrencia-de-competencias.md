# ADR 0002 — Coocorrência de competências

- **Status:** aceito (Etapa 2)
- **Data:** 2026-11-12

## Contexto

A pergunta é "quem pede A também pede B?". Ela serve à análise de mercado e, nas Etapas 3 e 4, à
análise de lacunas ("das vagas-alvo que pedem Airflow, 88% pedem ETL").

O histórico (taxonomia 2.0.0, janela de 90 dias, famílias de dados) tem estas características:

- **Volume:** 2.182 vagas, das quais 37% sem nenhuma competência técnica (trechos curtos da Adzuna) e 17% com uma só.
- **Pares:** 743 pares; 521 com pelo menos 10 vagas juntas.
- **Segmentos esparsos:** júnior de engenharia de dados tem 12 vagas com competência.

## Decisão

1. **Só pares**, calculados direto da silver: auto-junção em pandas/DuckDB, abaixo de 1 s.
   Apriori/FP-growth seriam desnecessários neste volume, e conjuntos de 3 ou mais competências
   ficariam com amostra pequena demais.
2. **Base = vagas com ao menos uma competência técnica.** Vaga sem competência extraída não informa
   nada sobre pares e inflaria o lift. Exemplo: Airflow+dbt sairia com lift 9,4 em vez de 5,9.
3. **Mesma menção não é par.** O mesmo trecho pode casar duas competências:
   - "Snowflake" → snowflake + data_warehouse;
   - "PySpark" → python + spark;
   - "Azure Data Factory" → azure + data_factory.

   A extração passa a guardar todas as menções de cada competência (`silver/job_skills.posicoes`).
   O par conta na vaga se A tem uma menção não colada a nenhuma de B, ou vice-versa. "Colada" é na
   mesma frase, com trechos sobrepostos ou separados por no máximo um caractere. Efeito no histórico:

   | Regra | Sem o ajuste | Com o ajuste |
   |---|---|---|
   | Snowflake → Data Warehouse | 100% | 34% |
   | Spark → Python | 92% | 81% |
   | Data Factory → Azure | 95% | 88% (as vagas citam Azure em outro trecho) |
4. **Métricas:**
   - suporte, confiança nos dois sentidos com **intervalo de Wilson 95%**, lift e Jaccard;
   - par com menos de `min_vagas_par` (10) vagas juntas, ou base com menos de 30 vagas, sai como amostra pequena.
5. **Gold incremental** `gold/skill_pairs`:
   - contagens por mês de coorte, família, senioridade e par, recalculadas nos mesmos meses da `skill_monthly`;
   - como as contagens são somáveis, qualquer janela sai delas;
   - a base de cada grupo é a nova coluna `vagas_com_competencia`, nas linhas `__total__` da `skill_monthly`.
6. **Público:** campo opcional `skill-trends.data.co_occurrence` (contrato **1.1.0**, minor):
   - só pares técnicos fora de amostra pequena, das famílias de dados e da janela das recomendações;
   - os 100 de maior **Jaccard**: lift sozinho favorece pares raros, como Java+Scala com 17 vagas e lift 33;
   - o portfólio usa zod no modo padrão, que ignora o campo até alguém decidir exibi-lo.
7. **Privado:** comando `jobradar coocorrencia` e a seção "Competências que aparecem juntas" na página Mercado.

## Consequências

- Todo texto sobre o tema diz "aparecem juntas". Nenhuma métrica é apresentada como causa, exigência
  ou caminho de aprendizado.
- Os pares vêm sobretudo das descrições completas (ATS). Os trechos da Adzuna têm poucas
  competências, então pesam pouco. Isso é um viés de cobertura, e a base publicada mostra o `n`.
- A reextração do histórico passa de ~30 s para ~60 s, por causa do registro de todas as menções.
- O recorte por segmento fino (senioridade × família) fica quase sempre como amostra pequena, até o histórico crescer.
