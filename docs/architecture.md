# Arquitetura e decisões técnicas

## Visão geral

O JobRadar é um pipeline em lote, executado a cada 6 horas no GitHub Actions (00:00, 06:00, 12:00 e 18:00 em São Paulo). Ele é dividido em módulos de domínio que não sabem como os dados serão entregues:

```
src/jobradar/
├── collectors/        coleta por fonte (collect → bronze, to_raw_job → silver); ats/ = um módulo por ATS
├── empresas/          catálogo de empresas (config/empresas.yaml) e situação da coleta por empresa
├── models/            schema canônico (Pydantic) e enums
├── transformations/   normalização, competências, chaves de dedup
├── storage/           lake em Parquet (sem conhecimento de git)
├── pipeline.py        orquestração incremental bronze → silver → gold
├── analytics/         indicadores de mercado e filtro de relevância
├── scoring/           perfil e score de aderência explicável
├── recommendations/   prioridades de estudo com regras de confiança
├── applications/      candidaturas e progresso de estudos (privado)
├── notifications/     e-mail HTML idempotente
├── publishing/        contrato v1 (JSON Schema) e exportador validado
└── cli.py             interface de linha de comando
```

`publishing/` e `notifications/` são **mecanismos de entrega**. Coletores, transformações e análises não dependem deles. Uma API REST futura entraria como outro mecanismo, reutilizando `analytics/` e `storage/`.

## Fluxo de uma execução

1. **Coleta.** Cada coletor ativo busca os termos configurados (Gupy, Adzuna) ou lê o quadro de cada empresa ativa do catálogo (Greenhouse, Lever), com timeout, retry exponencial com jitter para 429/5xx/timeouts e respeito a `Retry-After` (segundos ou data HTTP; acima de 60 s o quadro é dado como falho na execução). Respostas 4xx não são repetidas. Duplicatas entre termos são removidas e contadas.
2. **Bronze.** A resposta bruta vai para `bronze/source=<fonte>/dt=<data>/run=<run_id>.json.gz`, com `run_id`, horário de ingestão, parâmetros, contagem de requisições, retentativas e erros. Isso acontece mesmo quando a fonte falha, para ficar registrado.
3. **Silver.** Cada registro vira `RawJob`, validado pelo Pydantic; registros inválidos vão para `silver/quality_issues`. Depois é normalizado: senioridade, modalidade, UF e família do cargo, cada um com a **origem** registrada em `origem_campos` (`fonte`, `titulo`, `descricao` ou `nao_informada`). Em seguida:
   - **merge incremental** com `silver/jobs`: vaga conhecida atualiza `ultima_observacao` e preserva `primeira_observacao`;
   - **observação** por vaga e execução em `silver/observations`, registrando competências adicionadas ou removidas quando os requisitos mudam;
   - **deduplicação**: duas vagas são a mesma quando batem na **chave alternativa** (empresa + título sem ruído + UF, entre fontes) ou na **chave de republicação** (mesma fonte + mesma empresa, ou ambas sem empresa + mesmo título + mesma UF + mesma descrição). A segunda pega o agregador que republica o anúncio com outro id e outra data, inclusive sem empresa, caso em que não há chave alternativa. Os grupos são transitivos. Uma vaga é eleita canônica (ATS direto > agregador; depois a mais antiga) e as demais ficam marcadas `is_canonica = false`. Nada é apagado. "Novas" no relatório da execução são só as canônicas de id novo;
   - **status** recalculado (regra abaixo) e **retenção** de descrições aplicada.
   - **competências** extraídas pela taxonomia versionada. Cada achado traz método, evidência,
     confiança e versão; detalhes na seção abaixo.
4. **Gold.**
   - `gold/skill_monthly` é recalculado **só para os meses afetados**: meses de vagas novas ou com requisitos alterados.
   - `gold/job_scores` é recalculado para vagas observadas na execução ou quando o perfil muda (o hash do perfil detecta isso).
5. **Meta.** `meta/runs` e `meta/source_runs` guardam métricas por execução e fonte: coletados, válidos, inválidos, duplicatas, novas, requisições, retentativas, erros e duração. `meta/board_runs` guarda as mesmas medidas por quadro de ATS (empresa), base da "última coleta bem-sucedida" do catálogo.

Se **todas** as fontes falharem, a silver e a gold não são alteradas. Só a execução é registrada, com status `falha`, e o CLI sai com código 2.

## Regra de status das vagas

| Status | Regra |
|---|---|
| `ativa` | Observada nos últimos `status_desconhecido_apos_dias` (padrão 14) |
| `desconhecida` | Sem observação há mais tempo e sem evidência de encerramento |
| `encerrada` | Evidência explícita: a vaga **saiu do quadro da empresa** no Greenhouse/Lever (`saiu_do_quadro_da_empresa`) ou a fonte informou prazo de inscrição (`applicationDeadline`) e ele já passou (`prazo_de_inscricao_vencido`) |

Na Gupy e na Adzuna, que são **buscas**, uma vaga pode deixar de aparecer porque saiu do top N, porque o termo mudou ou porque a fonte ficou fora do ar. Por isso, nelas, a ausência nunca é tratada como encerramento.

O Greenhouse e o Lever são diferentes: cada chamada devolve o **quadro inteiro** da empresa. Então, se o quadro foi lido por completo e a vaga não está nele, ela saiu do ar. A regra:

- o coletor registra, por quadro, os ids de **todas** as vagas listadas, antes do filtro de título (uma vaga que só deixou de passar no filtro continua no quadro e não é encerrada);
- não servem de evidência: quadro com erro, quadro vazio (suspeito) e, no Greenhouse, quadro cujo `meta.total` não bate com a lista devolvida (`quadros_incompletos` na bronze);
- a vaga ausente recebe `encerrada_em` na primeira execução em que faltou, e a data não muda nas execuções seguintes;
- só vale para vagas cujo `quadro` foi lido nesta execução: empresa retirada da configuração não encerra nada, e vagas gravadas antes desta regra (sem `quadro`) seguem a regra de 14 dias;
- se a vaga voltar ao quadro, a nova observação zera `encerrada_em` e ela volta a ser `ativa`.

Com `encerrada_em` dá para medir quanto tempo cada vaga ficou aberta (`encerrada_em − primeira_observacao`), por empresa.

## Persistência

**Decisão:** o histórico vive num repositório **privado** (`jobradar-data`), clonado no workflow com uma **deploy key** que tem escrita apenas nele.

| Alternativa | Por que não (agora) |
|---|---|
| Artefatos ou cache do Actions | Expiram e podem ser removidos. Não são armazenamento durável |
| Commit no repositório público | Exporia descrições de terceiros, perfil e candidaturas |
| Cloudflare R2 / S3 | Bom destino futuro, mas exige mais um fornecedor e credenciais. O volume atual não justifica |
| Banco remoto (Postgres etc.) | Não há escrita concorrente nem consulta online que justifique |

O módulo `storage/` só lê e grava arquivos. Migrar para R2 significa trocar os passos de sincronização do workflow (ou implementar `Lake` sobre `s3://` com DuckDB httpfs), sem tocar em coletores ou transformações.

**Volume esperado:** algumas centenas de vagas por dia, com descrições cortadas em 20 mil caracteres e bronze com retenção de 90 dias. Isso fica na casa de dezenas de MB por ano, bem abaixo dos limites recomendados pelo GitHub para repositórios.

## Publicação para o portfólio

- Depois que `jobradar publish` **valida** os três documentos e o manifesto contra os JSON Schema, `scripts/publish_public_data.sh` grava `v1/` na branch órfã `public-data` deste repositório, usando o `GITHUB_TOKEN` (`contents: write` só neste repositório).
- O site lê `https://raw.githubusercontent.com/santosluzia/jobradar/refs/heads/public-data/v1/*.json`. Esse domínio já está liberado na CSP do portfólio (`connect-src`), não há token no frontend e a resposta tem `Access-Control-Allow-Origin: *`.
- **Versão anterior preservada:** a geração acontece num diretório temporário e só troca o `v1/` no fim. Se a validação ou qualquer passo falhar, a branch continua no último commit válido, e o histórico da branch guarda todas as versões.
- O GitHub Actions de um repositório **não** escreve no repositório do portfólio. O site é que consome uma URL pública. Não há tokens pessoais amplos.

### Por que JSON estático e não uma API

O dashboard público só lê poucos agregados, que mudam poucas vezes por dia. JSON estático tem custo zero, cache por CDN e nenhuma superfície de ataque. Uma API REST passa a se justificar quando houver ao menos um destes requisitos concretos:

1. uma área pessoal **na web**, com login, para candidaturas ou notas;
2. consultas filtradas sobre um histórico grande demais para um arquivo;
3. consumidores externos que precisem de paginação ou filtros no servidor.

## Extração de competências

Detalhes em docs/taxonomia.md; decisão e medição em docs/adr/0001-extracao-de-competencias-sem-custo.md.

- **Regras determinísticas, ativas por padrão.**
  - **Achados:** termos e sinônimos, mais **conceitos** (frases que implicam a competência).
  - **Leitura do texto:** segmentação dos textos colados da Gupy; seções e frases de contexto (sobre
    a empresa, benefícios), que não geram competência.
  - **Rastreabilidade:** por achado ficam a evidência (frase original), o método, a confiança e a versão da taxonomia.
- **Técnicas × não técnicas.** Comportamentais e idioma ficam só na silver (uso privado). Gold, score,
  recomendações, e-mail e contrato público usam só as técnicas, por um único ponto de decisão:
  `transformations.skills.efetivas` (via `analytics.market.competencias`).
- **Camada semântica local, desligada.** Usa embeddings model2vec (modelo MIT, revisão fixa e
  SHA-256 conferido), só como complemento e em tabela separada. Entra nos números públicos apenas com
  `gold_hibrida: true`. Nenhum texto sai da máquina.
- **Versão da taxonomia.**
  - Mudança de versão não é "mudança de requisito" da vaga.
  - A gold recalcula os meses das vagas cujas competências mudaram por qualquer motivo.
  - O passo `jobradar reextrair` do workflow alinha o histórico à versão atual; não faz nada se já está alinhado.
- **Qualidade medida.** Conjunto-ouro privado com lotes `ajuste` e `teste` (`jobradar avaliacao medir`).
  A fila de curadoria (`jobradar competencias candidatas`) sugere termos não cobertos.

## Coocorrência de competências

Detalhes em docs/adr/0002-coocorrencia-de-competencias.md.

- **Base:** vagas com ao menos uma competência técnica. Mesma menção ("PySpark", "Azure Data Factory") não é par.
- **Métricas** (`analytics/coocorrencia.py`): suporte, confiança A→B e B→A com intervalo de Wilson,
  lift e Jaccard, com mínimos de amostra.
- **Armazenamento e uso:**
  - `gold/skill_pairs` é incremental pelos meses afetados;
  - o recorte de 90 dias vai para o contrato público (`co_occurrence`, 1.1.0);
  - o uso privado fica no comando `jobradar coocorrencia` e na página Mercado do painel.
- **Leitura:** é associação, não causa.

## Perfil, objetivos e currículo (privado)

Detalhes em docs/adr/0003-curriculo-privado.md.

- **Objetivos:** o perfil tem vários (`objetivos:` em `profile.yaml`). Cada um tem vagas-alvo, score
  (`gold/job_scores.objetivo_id`) e diagnóstico próprios.
- **Currículo:** é lido e interpretado localmente, sem IA (`jobradar.curriculo`), e guardado em
  `$JOBRADAR_HOME`, fora do git. Pipeline, publicação e e-mail não importam esse pacote.
- **Diagnóstico:** compara a aderência do **perfil** (o que você declara) com a do **currículo** (o que
  o texto demonstra), ponderadas pela demanda das vagas-alvo. As sugestões vêm de regras e citam os
  dados que as justificam.

## Minha Evolução Profissional (privado)

Detalhes em docs/adr/0004-evolucao-profissional.md.

- **Plano por objetivo:** prioridade explicável (7 fatores com decomposição) e as 7 classes da
  especificação. Só as N lacunas mais prioritárias viram "prioritárias"; as demais aparecem com o motivo.
- **Recomendações:** ligadas às vagas (quantas, em quais cargos, com quais tecnologias) e ao conteúdo
  editável de `config/evolucao.yaml`.
- **Progresso** (`private/study_progress` e `study_events`): forma o **perfil efetivo**, que só sobe o
  nível declarado. Curso concluído não vira experiência profissional. Mudar o progresso recalcula o score
  na próxima execução e o plano na próxima consulta.

## JobRadar — Seu Radar Profissional (e-mail diário)

Detalhes em docs/adr/0005-radar-profissional.md.

- **Quando sai:** no turno configurado (`private/radar.yaml`), o Radar substitui o e-mail de vagas e já
  leva as vagas novas.
- **Conteúdo:** 4 blocos (mercado, perfil, oportunidade, ação do dia) montados com o plano da Etapa 4.
- **Qualidade:** tendência só com amostra mínima; a ação do dia não se repete e respeita o progresso;
  item já apontado nos últimos dias não volta.
- **Privacidade e controle:**
  - o currículo só entra pelo resumo de níveis, compartilhado por adesão;
  - o Radar não lê `~/.jobradar`, e o log recebe só contagens;
  - o histórico e o controle de duplicidade ficam em `private/radar_envios`.

## Relatório Semanal de Evolução Profissional

Detalhes em docs/adr/0006-relatorio-semanal.md.

- **Envio:** e-mail semanal à parte do Radar (padrão: segunda 12:00).
- **Conteúdo:** 10 seções e, no fim, as 3 principais oportunidades.
- **Comparações:** semana × semana, 30 × 30 dias, objetivo × mercado e versões do resumo do currículo,
  todas só com amostra mínima.
- **Acompanhamento:** cruza as recomendações anteriores (Radar e relatório) com o progresso registrado depois.
- **Histórico:** `private/relatorios_semanais`; consulta na página "Relatório semanal" do painel.

## Career Intelligence e diagnóstico mensal

Detalhes em docs/adr/0007-career-intelligence.md.

- **Retrato mensal automático por objetivo** em `private/diagnosticos_mensais`, com e-mail mensal.
- **As 7 perguntas da especificação**, e "a aderência melhorou?" decomposta em efeito do mercado e
  efeito do perfil.
- **Painel em duas seções:**
  - Mercado: Visão geral, Radar de mercado e Vagas;
  - Career Intelligence: Minha compatibilidade, Minha Evolução Profissional, Meu currículo, Relatório
    semanal e Diagnóstico mensal.

## Score de aderência

Calculado **por objetivo** do perfil (uma linha por vaga e objetivo). O texto abaixo vale para cada objetivo.


A soma ponderada vai de 0 a 100. Os pesos estão em `config/scoring.yaml`:

| Componente | Peso | Como pontua |
|---|---|---|
| Família / responsabilidades | 20 | Fração por família de cargo; família-alvo do perfil vale 100%. Título genérico (analista, desenvolvedor, consultor…) sem família de dados que pede ao menos 3 competências de dados (`familia_por_competencias` em `config/scoring.yaml`) vale 50%, sem a penalidade abaixo |
| Competências | 45 | Cobertura dos requisitos pela evidência (profissional 1,0 · projeto 0,75 · em desenvolvimento 0,4 · não dominada e sem evidência 0). Desejáveis valem 40% de um requisito |
| Senioridade | 20 | 100% se estiver no objetivo; sênior e liderança pontuam pouco |
| Modalidade e local | 15 | Remoto, ou híbrido/presencial na região preferida; neutro quando não informado |
| Penalidades | — | −30 para palavra excludente no título; −20 para cargo fora das famílias de dados (exceto o caso de competências acima) |

Cada score é gravado com a lista de critérios, pontos e motivo. As lacunas são separadas em **não dominadas**, quando o perfil diz que a pessoa não domina, e **sem evidência**, quando não há registro no perfil.

## Recomendações de estudo

- **Grupo-alvo:** vagas canônicas das famílias e senioridades do perfil (mais `nao_informada`).
- **Janelas:** recente (90 dias) contra a anterior equivalente (90 dias), pela data da primeira observação.
- **Tendência:** só é declarada com pelo menos 30 vagas em **cada** janela e variação de pelo menos 5 p.p. Caso contrário, é "inconclusiva".
- **Classes:**
  - `consolidada`: evidência profissional ou em projeto;
  - `em_desenvolvimento`: marcada como em desenvolvimento no perfil;
  - `lacuna_prioritaria`: competência não dominada ou sem evidência, com amostra suficiente e presente em pelo menos 15% das vagas recentes;
  - `monitoramento`: os demais casos.
- **Prioridade:** combina demanda, peso de requisito, tendência positiva, possibilidade de projeto prático e esforço estimado. A justificativa em texto traz os números que sustentam cada recomendação.

## Fontes

| Fonte | Acesso | Situação |
|---|---|---|
| Gupy | JSON consumido por `portal.gupy.io`, sem autenticação | Não é API documentada. Rota atual: `portal.gupy.io/api/job-search/jobs` (desde 2026-10; as antigas `portal.api.gupy.io/api/v1/jobs` e `employability-portal.gupy.io/api/v1/jobs` respondem 404). `urls` aceita alternativas. Uso com pausa entre requisições |
| Adzuna | API oficial com `app_id`/`app_key` | A cobertura BR (`/jobs/br/`) precisa ser confirmada na primeira execução com chave real |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs` | API pública de job board. Ativa com 12 empresas brasileiras (catálogo `config/empresas.yaml`). Traz todas as vagas da empresa; `titulo_contem` descarta as que não são de dados antes da bronze |
| Lever | `api.lever.co/v0/postings/{empresa}` | API pública de postings. Ativa com a CI&T (catálogo), com o mesmo filtro por título |
| Workday | — | Não usado: não há API pública documentada (ADR 0009) |
| LinkedIn / Indeed | — | Não usados: os termos proíbem automação |

## Catálogo de empresas

Detalhes em docs/adr/0009-catalogo-de-empresas.md.

- **Curado × medido:** `config/empresas.yaml` guarda o que foi conferido (país, segmento, ATS, quadro,
  status, data da verificação); `meta/board_runs` guarda o que cada execução mediu por quadro.
- **Só `status: ativa` é coletada.** Candidatas (descoberta assistida, próximo passo) esperam curadoria.
- **Consulta:** `jobradar empresas listar [--status ativa] [--ats greenhouse]`.

## Governança e segurança

Detalhes em docs/adr/0008-governanca-seguranca.md, docs/privacidade.md e docs/rastreabilidade.md.

- **Fronteira:** o público (código, logs do Actions, `public-data`) nunca recebe dado pessoal. Há um teste
  com canário em todo dado privado e uma checagem estática do código de publicação.
- **Parte pessoal no privado:** com `JOBRADAR_NOTIFICACAO_PRIVADA=true`, o workflow público roda
  `--sem-pontuacao`, e o workflow do `jobradar-data` roda `jobradar pontuar` e os e-mails, disparado pelo
  push do lake.
- **Validações registradas** em `meta/validacoes` e `private/validacoes`. Segredos mascarados em erros,
  logs e resumo. Actions fixadas por SHA. Painel só em `localhost`.
- **Saúde:** `analytics/saude.py`, com indicadores e alertas só agregados.

## Retenção

| Dado | Retenção |
|---|---|
| Bronze (respostas brutas) | 90 dias |
| Descrição completa na silver | Até 180 dias após a última observação; depois só o hash e as competências |
| Metadados, competências, observações e agregados | Indefinida |
| Dados públicos | Só agregados, título, empresa, local, link e competências, **sem descrição** |
| Currículo local (pasta privada) | 12 versões mais recentes; diagnósticos e planos por 24 meses (`jobradar privacidade limpar`) |
