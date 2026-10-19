# Arquitetura e decisões técnicas

## Visão geral

O JobRadar é um pipeline em lote, executado a cada 6 horas no GitHub Actions (00:00, 06:00, 12:00 e 18:00 em São Paulo). Ele é dividido em módulos de domínio que não sabem como os dados serão entregues:

```
src/jobradar/
├── collectors/        coleta por fonte (collect → bronze, to_raw_job → silver)
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

1. **Coleta.** Cada coletor ativo busca os termos configurados, com timeout, retry exponencial para 429/5xx/timeouts e respeito a `Retry-After`. Respostas 4xx não são repetidas. Duplicatas entre termos são removidas e contadas.
2. **Bronze.** A resposta bruta vai para `bronze/source=<fonte>/dt=<data>/run=<run_id>.json.gz`, com `run_id`, horário de ingestão, parâmetros, contagem de requisições, retentativas e erros. Isso acontece mesmo quando a fonte falha, para ficar registrado.
3. **Silver.** Cada registro vira `RawJob`, validado pelo Pydantic; registros inválidos vão para `silver/quality_issues`. Depois é normalizado: senioridade, modalidade, UF e família do cargo, cada um com a **origem** registrada em `origem_campos` (`fonte`, `titulo`, `descricao` ou `nao_informada`). Em seguida:
   - **merge incremental** com `silver/jobs`: vaga conhecida atualiza `ultima_observacao` e preserva `primeira_observacao`;
   - **observação** por vaga e execução em `silver/observations`, registrando competências adicionadas ou removidas quando os requisitos mudam;
   - **deduplicação entre fontes** pela chave alternativa (empresa + título sem ruído + UF): uma vaga é eleita canônica (ATS direto > agregador) e as demais ficam marcadas `is_canonica = false`. Nada é apagado;
   - **status** recalculado (regra abaixo) e **retenção** de descrições aplicada.
4. **Gold.**
   - `gold/skill_monthly` é recalculado **só para os meses afetados**: meses de vagas novas ou com requisitos alterados.
   - `gold/job_scores` é recalculado para vagas observadas na execução ou quando o perfil muda (o hash do perfil detecta isso).
5. **Meta.** `meta/runs` e `meta/source_runs` guardam métricas por execução e fonte: coletados, válidos, inválidos, duplicatas, novas, requisições, retentativas, erros e duração.

Se **todas** as fontes falharem, a silver e a gold não são alteradas. Só a execução é registrada, com status `falha`, e o CLI sai com código 2.

## Regra de status das vagas

| Status | Regra |
|---|---|
| `ativa` | Observada nos últimos `status_desconhecido_apos_dias` (padrão 14) |
| `desconhecida` | Sem observação há mais tempo e sem evidência de encerramento |
| `encerrada` | A fonte informou prazo de inscrição (`applicationDeadline`) e ele já passou |

Uma vaga pode deixar de aparecer porque saiu do top N da busca, porque o termo mudou ou porque a fonte ficou fora do ar. Por isso a ausência nunca é tratada como encerramento.

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

## Score de aderência

A soma ponderada vai de 0 a 100. Os pesos estão em `config/scoring.yaml`:

| Componente | Peso | Como pontua |
|---|---|---|
| Família / responsabilidades | 20 | Fração por família de cargo; família-alvo do perfil vale 100% |
| Competências | 45 | Cobertura dos requisitos pela evidência (profissional 1,0 · projeto 0,75 · em desenvolvimento 0,4 · não dominada e sem evidência 0). Desejáveis valem 40% de um requisito |
| Senioridade | 20 | 100% se estiver no objetivo; sênior e liderança pontuam pouco |
| Modalidade e local | 15 | Remoto, ou híbrido/presencial na região preferida; neutro quando não informado |
| Penalidades | — | −30 para palavra excludente no título; −20 para cargo fora das famílias de dados |

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
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs` | API pública de job board. Ativa com 12 empresas brasileiras (lista em `config/sources.yaml`). Traz todas as vagas da empresa; `titulo_contem` descarta as que não são de dados antes da bronze |
| Lever | `api.lever.co/v0/postings/{empresa}` | API pública de postings. Ativa com a CI&T, com o mesmo filtro por título |
| LinkedIn / Indeed | — | Não usados: os termos proíbem automação |

## Retenção

| Dado | Retenção |
|---|---|
| Bronze (respostas brutas) | 90 dias |
| Descrição completa na silver | Até 180 dias após a última observação; depois só o hash e as competências |
| Metadados, competências, observações e agregados | Indefinida |
| Dados públicos | Só agregados, título, empresa, local, link e competências, **sem descrição** |
