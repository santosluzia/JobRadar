# Contrato de dados público — v1

Interface estável entre o JobRadar (produtor) e o portfólio [santosluzia.com](https://santosluzia.com/vagas-engenharia-de-dados) (consumidor).

**URL base:** `https://raw.githubusercontent.com/santosluzia/jobradar/refs/heads/public-data/v1/`

| Arquivo | Conteúdo | Schema |
|---|---|---|
| `manifest.json` | Índice: versão, data de geração, run_id e, por arquivo, sha256, registros e bytes | [manifest.schema.json](v1/manifest.schema.json) |
| `market-summary.json` | Totais, distribuições, qualidade e última execução bem-sucedida | [market-summary.schema.json](v1/market-summary.schema.json) |
| `skill-trends.json` | Taxonomia, frequência atual, série mensal e recorte por senioridade | [skill-trends.schema.json](v1/skill-trends.schema.json) |
| `jobs.json` | Até 300 vagas relevantes dos últimos 30 dias, com links | [jobs.schema.json](v1/jobs.schema.json) |

Os schemas também são publicados ao lado dos dados (`v1/*.schema.json`).

## Envelope comum

Todos os arquivos de dados têm a mesma estrutura externa:

```json
{
  "schema_version": "1.0.0",
  "dataset": "jobs",
  "generated_at": "2026-10-16T09:52:11Z",
  "run_id": "11456789012-1",
  "data_window": { "start": "2026-09-16", "end": "2026-10-16" },
  "coverage": {
    "sources": [{ "source": "gupy", "status_last_run": "ok", "last_success_at": "2026-10-16T09:51:40Z",
                  "records_last_run": 412, "jobs_in_history": 1830 }],
    "observations": 212,
    "note": "Amostra das fontes e termos configurados no JobRadar; não representa o mercado inteiro. ..."
  },
  "data": { }
}
```

## Regras

- **Campos ausentes** são `null`, nunca string vazia nem omitidos. Todos os campos são obrigatórios no schema (`required`), e os anuláveis declaram `["tipo", "null"]`.
- **Datas** seguem ISO-8601 em UTC (`date-time`), ou `AAAA-MM-DD` em `data_window`.
- **Enums são fechados:**
  - modality: `remoto` `hibrido` `presencial` `nao_informada`;
  - seniority: `estagio` `junior` `pleno` `senior` `lideranca` `nao_informada`;
  - family: `engenharia_dados` `analytics_engineering` `desenvolvimento_dados` `analise_dados` `governanca_qualidade` `outra`;
  - status: `ativa` `desconhecida` `encerrada`.
- **`additionalProperties: false`** em todos os objetos, o que impede que um campo não previsto, como uma descrição ou um score pessoal, vaze por engano.
- **Amostra:** `low_sample: true` quando o denominador está abaixo de `min_sample` (30). O frontend deve exibir esses pontos com aviso.
- **URLs** de vaga são sempre `https://`, a URL original da fonte, para candidatura manual.

## O que nunca é publicado

Descrições de vagas, respostas brutas, perfil profissional, score de aderência, lacunas, recomendações pessoais, candidaturas, observações pessoais, registro de notificações e credenciais.

## Versionamento

| Mudança | Versão | Onde |
|---|---|---|
| Novo campo **opcional** ou novo valor informativo | minor (`1.1.0`) | mesmo `v1/` |
| Remover, renomear, mudar tipo ou ampliar um enum | major (`2.0.0`) | novo `v2/`, publicado **em paralelo** com `v1/` até o site migrar |

O consumidor deve ler `schema_version`, aceitar qualquer `1.x` e ignorar campos que não conhece.

## Garantias de publicação

1. `jobradar publish` gera os quatro arquivos e valida cada um com JSON Schema (Draft 2020-12, incluindo formato de datas). Também verifica ids duplicados.
2. Qualquer erro interrompe o processo **antes** de escrever. O diretório `v1/` anterior fica intacto.
3. Só depois disso o workflow faz commit na branch `public-data`. Se a validação falhar, o site continua servindo a última versão válida, e `generated_at` mostra a idade dos dados.
4. O cache do `raw.githubusercontent.com` pode levar alguns minutos para refletir um novo commit.

## Exemplo de consumo (TypeScript + zod)

O portfólio valida a resposta com zod antes de renderizar (`src/services/vagas.ts` e `src/types/vagas.ts`, na rota `/vagas-engenharia-de-dados`). Se a validação falhar, a página mostra um estado de erro em vez de dados quebrados.
