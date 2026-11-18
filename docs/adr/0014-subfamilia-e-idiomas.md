# ADR 0014 — Subfamília, títulos em espanhol e idiomas da vaga

- **Status:** aceito (PR F da evolução para inteligência de mercado)
- **Data:** 2026-11-18

## Contexto

A família de cargo (`normalize.familia`) separa sete grupos, mas não diz, dentro de engenharia de dados, o que
é arquitetura ou plataforma, nem, dentro de análise, o que é BI. Também não havia nada sobre idioma. Os
problemas eram três:

- **Títulos em espanhol:** com a cobertura de LatAm (ADR 0010), eles começaram a chegar, como "Ingeniero Big
  Data" e "Desarrollador ETL", e caíam em `outra`. "Semi Senior" virava `senior`.
- **Lacunas em português:** "Analista de Inteligência de Dados", "Analista Sr. de Dados", "Estágio em Análise
  de Dados", "Arquitetura de Dados" e "Gestão de Dados" também caíam em `outra`.
- **Idioma:** 13% das vagas de dados do histórico estão escritas em inglês, e o perfil não tinha como cruzar
  isso com o que a pessoa domina (fase J–K).

## Decisão

1. **Família (taxonomia 2.2.0):** os padrões de título passam a aceitar o espanhol e cobrem as lacunas acima.
   A senioridade ganha "Semi Senior"/"SSr" (→ `pleno`), "Practicante"/"Pasante" (→ `estagio`) e "Jefe"
   (→ `lideranca`). O `reextrair` reaplica a família ao histórico, como nas versões anteriores.
   - Os enums **não mudam**: nenhuma família nova. O contrato público v1, o score e o filtro de relevância
     ficam como estavam.
2. **Subfamília** (`transformations/classificacao.py`): é derivada do título dentro da família. Sem regra
   que case, vale a subfamília geral da família.

   | Família | Subfamílias |
   |---|---|
   | engenharia_dados | arquitetura_dados · plataforma_dados · dataops · engenharia_dados (geral) |
   | analytics_engineering | analytics_engineering |
   | desenvolvimento_dados | bi_desenvolvimento · banco_dados · etl_integracao · desenvolvimento_dados |
   | analise_dados | bi_visualizacao · analise_dados |
   | governanca_qualidade | mdm · qualidade_dados · integracao_dados · governanca_dados |
   | administracao_dados | administracao_dados (AD) · dba |
   | outra | ciencia_dados · machine_learning · produto_dados · lideranca_dados · fora_de_dados |

   Em `outra`, as subfamílias marcam **cargos adjacentes a dados**. Ciência de dados, ML, liderança e
   produto ficam fora do escopo das famílias de dados, mas a análise de mercado consegue vê-los.
3. **Idioma da vaga** (`pt | en | es | indeterminado`): contagem de palavras funcionais exclusivas de cada
   idioma na descrição (ou no título, sem descrição). A decisão exige ao menos 8 palavras e que o
   primeiro idioma tenha 1,5 vez as ocorrências do segundo. Fora disso, o idioma fica `indeterminado`.
   Não usa biblioteca nem serviço externo.
4. **Idiomas exigidos** (JSON):
   - **Formato:** `[{idioma, nivel, importancia, origem, evidencia}]`.
     - **Nível:** fluente, avançado, intermediário, básico ou não informado.
     - **Importância:** requisito ou desejável, pela mesma leitura de seções da taxonomia.
     - **Origem:** `descricao`, `titulo` ou `idioma_da_vaga`.
   - **Menção explícita:** frase de empresa ou de benefícios não conta, e "reembolso de curso de idiomas"
     não vira exigência. Frase que nega ("inglês não é necessário") também não. Requisito vence desejável e,
     depois, vale o nível mais alto.
   - **Exigência inferida:** vaga escrita num idioma que não é o do país (inglês numa vaga do Brasil) gera
     exigência com origem `idioma_da_vaga` e nível não informado.
   - A taxonomia ganha `espanhol` (tipo `idioma`, privado, como `ingles`).
5. **Versão e migração:** `classificacao_versao` (1.0.0) em cada linha. Na execução seguinte,
   `classificacao.atualizar` preenche o histórico, como a geografia. Vaga sem descrição (já saiu pela
   retenção) mantém o idioma calculado antes. O `reextrair` refaz a subfamília das vagas cuja família mudou.
6. **Conjunto-ouro de classificação:** `ItemOuro.classificacao` traz família, subfamília, idioma da vaga
   e idiomas exigidos, com `revisado` próprio. Os comandos são `jobradar avaliacao amostrar-classificacao`
   (estratos: cada família, cargos adjacentes e vagas fora do português) e `medir-classificacao`, com F1
   macro de família, acurácia de subfamília e de idioma e precisão/recall de idioma exigido.
7. **Leitura:** `jobradar classificacao` mostra os agregados (subfamílias, idioma das vagas, % que exige
   inglês e nível), sempre com n.

## Consequências

- **Histórico** (cópia de 2026-11-18, 10.821 vagas):
  - **Família:** 287 vagas mudaram, incluindo as regras do #10, que ainda não tinham sido reaplicadas.
    Só 2 trocaram entre famílias de dados: eram `engenharia_dados` pelas competências e o título agora
    diz análise.
  - **Competências técnicas:** nenhuma mudou.
  - **Custo:** a migração leva ~25 s, uma vez só. O `reextrair` completo leva ~67 s.
- **Retrato** (90 dias, 2.928 vagas de dados): 86,6% em português, 13,0% em inglês e 0,2% em espanhol.
  17,8% exigem inglês, sendo 11,3% só pelo idioma da vaga. Cargos adjacentes: ciência de dados 250,
  liderança 56, ML 29 e produto 25.
- **Conjunto-ouro:** 74 vagas novas, lote `ajuste`, com rótulos-**rascunho** feitos pelo assistente
  (`revisado: false`).

  | Medida | Rascunho | Meta |
  |---|---|---|
  | Família, F1 macro | 95,1% | ≥ 90% |
  | Família, acurácia | 94,6% | — |
  | Subfamília (família certa) | 97,1% | — |
  | Idioma da vaga | 100% | ≥ 95% |
  | Nível do idioma exigido | 96,6% | — |
  | Inglês exigido, precisão e recall | 100% e 100% | — |

  Esses números são **otimistas**:
  - os rótulos são do assistente e ainda não foram revisados;
  - ao rotular, a família prevista estava visível;
  - as frases de idioma foram achadas por palavras-chave parecidas com as do classificador;
  - o lote é o de ajuste.

  A medição oficial é a de um lote `teste` sorteado agora e rotulado por pessoa, sem ver a saída.
- **Erros que ficam:**
  - "Senior Data Analyst (Data Quality & Reporting)" vira governança, porque a regra de governança vem
    antes da de análise;
  - "Tech Lead Data - Databricks" e "Software Engineer, Data Platform" ficam em `outra`;
  - títulos com dois cargos ("ETL/BI", "BI/Data Science") pegam a primeira regra que casa;
  - "Especialista de Recrutamento - Data Analytics" vira `analise_dados` pela regra de "* analytics".
- **Custo por execução:** a classificação custa ~1,3 ms por vaga coletada (~13 s numa execução com 10 mil
  registros), dentro do orçamento de +5 min do roadmap.
- **Limites:**
  - a Adzuna corta a descrição em ~500 caracteres, então menção a idioma no fim do texto não é vista;
  - "Good English" e similares ficam como nível não informado;
  - a subfamília só lê o título, e o idioma da vaga não separa variantes (pt-BR × pt-PT).
- **Sem mudança pública:** as colunas novas ficam na silver (privada). O contrato 1.2.0, com subfamília e
  idiomas, fica para o PR G, junto com salário e senioridade por anos de experiência.
