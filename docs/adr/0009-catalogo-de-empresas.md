# ADR 0009 — Catálogo de empresas e coleta por quadro

- **Status:** aceito (PR A da evolução para inteligência de mercado)
- **Data:** 2026-11-17

## Contexto

As empresas consultadas no Greenhouse e no Lever eram duas listas soltas em `config/sources.yaml`
(12 tokens e 1 slug). Não havia país, segmento, situação da integração nem a data da última conferência.
Também não dava para responder "quando a coleta desta empresa funcionou pela última vez": as métricas
eram só por fonte, e a falha de um quadro virava um texto dentro de `meta/source_runs.erros`.

A próxima etapa amplia as fontes (Ashby, SmartRecruiters) e a lista de empresas, com descoberta
assistida e fila de curadoria. Isso pede um lugar único, validado e versionado para as empresas.

## Decisão

1. **Catálogo versionado em `config/empresas.yaml`**, validado por Pydantic (`jobradar.empresas.catalogo`).
   - É dado público e curado: nome, país (ISO 3166-1 alfa-2), segmento (lista fechada), site, página de
     carreiras, plataforma (`ats`), identificador do quadro (`board`), `status`, `verificada_em` e `origem`.
   - Status `candidata | ativa | pausada | descartada`. **Só `ativa` entra na coleta.** Uma empresa ativa
     precisa de plataforma com coletor, de `board` e de `verificada_em`.
   - A URL da API e a página do quadro no ATS são **derivadas** de `ats + board`. Elas não são repetidas
     no arquivo, para não divergirem do coletor (um teste garante que são as mesmas URLs).
   - `site` e `pagina_carreiras` ficam vazios até alguém conferir. O catálogo não inventa endereço.
2. **Medido fica separado do curado.** Cada quadro consultado gera uma linha em `meta/board_runs`
   (ok, completo, vagas listadas e mantidas no filtro de título, requisições, retentativas, duração e
   erro mascarado). A "última coleta bem-sucedida" sai dessa tabela, não do YAML, que só muda por revisão.
3. **Falha de um quadro não derruba os outros**, como já acontecia. Agora ela fica registrada no próprio
   quadro. Resposta fora do formato esperado (sem `jobs` no Greenhouse, sem lista no Lever) é falha do
   quadro, com a mensagem "formato mudou?".
4. **Coleta mais educada com as APIs.** O backoff exponencial ganhou jitter de até 25%. `Retry-After` é
   aceito em segundos ou em data HTTP. Se o servidor pedir mais de 60 s, o quadro é dado como falho
   nesta execução, em vez de travar o job, e a próxima execução tenta de novo.
5. **Compatibilidade.** `fontes.<ats>.empresas` em `sources.yaml` continua aceito e é somado ao catálogo
   sem repetir quadro. Os coletores e o formato da bronze não mudaram (a bronze só ganhou `por_quadro`).

## Consequências

- A lista coletada é exatamente a de antes da migração (há teste com as 13 empresas na mesma ordem).
- `jobradar empresas listar` mostra catálogo e situação lado a lado, sem dado pessoal.
- O catálogo é validado em toda execução e o resultado vai para `meta/validacoes`
  (`catalogo_empresas`). Catálogo inválido impede a coleta.
- Estar no catálogo **não** significa ter vaga aberta: significa que o quadro existe e é lido.

## Fora do escopo (próximos PRs)

- Adaptadores Ashby e SmartRecruiters (o enum `ats` já os aceita como `candidata`).
- Descoberta assistida a partir da página de carreiras e fila de curadoria (`origem: descoberta`).
- Workday: não há API pública documentada. A rota `/wday/cxs/` é interna do site e não será usada.
