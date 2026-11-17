# ADR 0011 — Adaptadores Ashby e SmartRecruiters

- **Status:** aceito (PR C da evolução para inteligência de mercado)
- **Data:** 2026-11-17

## Contexto

A coleta direta nas empresas usava só Greenhouse e Lever. Para ampliar a cobertura, o roadmap prevê mais
plataformas de recrutamento (ATS) com acesso público e documentado. A regra é não inventar endpoint,
parâmetro ou identificador de empresa.

## Verificação (2026-11-17)

| Plataforma | Documentação | Sondagem real |
|---|---|---|
| Ashby | developers.ashbyhq.com/docs/public-job-posting-api | `api.ashbyhq.com/posting-api/job-board/ashby` → 200, 77 vagas |
| SmartRecruiters | developers.smartrecruiters.com/reference/v1listpostings e v1getposting | `api.smartrecruiters.com/v1/companies/SmartRecruiters/postings` → 200, `totalFound` 1; detalhe com `jobAd.sections` |
| Lever (`country`, `lists`) | — | `api.lever.co/v0/postings/ciandt` → 110 vagas, `country` em todas (BR 89, CO 14, GB 4, US 2, SG 1) |

Os quadros usados na sondagem servem só para confirmar o formato e **não** entram no catálogo.

## Decisão

1. **Ashby** (`collectors/ats/ashby.py`): `GET /posting-api/job-board/{quadro}?includeCompensation=true`.
   - O quadro vem inteiro e sem total informado. Como no Lever, quadro vazio é suspeito e não serve de
     evidência de encerramento.
   - A tabela de campos da documentação não lista `id`, mas a resposta traz o UUID. Sem ele, o id sai
     do último trecho de `jobUrl`.
   - `isListed: false` (vaga só acessível por link direto) não é coletada, mas conta como presente no
     quadro. Assim, não encerra a vaga.
   - A API não informa o nome da empresa. Ele vem do catálogo (`nome`), que os coletores agora
     recebem em `cfg["nomes"]`.
2. **SmartRecruiters** (`collectors/ats/smartrecruiters.py`): listagem paginada
   (`limit=100&offset=N&destination=PUBLIC`, sem autenticação para vagas públicas) e detalhe por vaga.
   - O quadro só está completo quando todas as páginas foram lidas e `totalFound` bate com a lista.
   - A descrição só existe no detalhe. Ele é buscado **apenas para as vagas que passam no filtro de
     título**, o que dá uma requisição por vaga relevante.
   - A descrição junta as seções do anúncio, cada uma com o título que a empresa deu ("Requisitos",
     "Qualifications"…). O texto sobre a empresa vira contexto pela regra de extração que já existe.
   - Detalhe que falha: a vaga fica fora da coleta, porque sem link de candidatura não há registro
     válido. Ela conta em `detalhes_com_erro`, continua no quadro e, por isso, não é encerrada.
3. **Lever, descrição completa e país:**
   - a descrição passou a ser `descriptionPlain` + `lists` (com o título de cada lista) + `additionalPlain`.
     Antes, as listas de requisitos e o texto adicional ficavam de fora;
   - `country` (ISO alfa-2) alimenta a geografia (ADR 0010).
4. **Preferência entre fontes** para eleger a vaga canônica: Gupy > Greenhouse > Lever > Ashby >
   SmartRecruiters > Adzuna (ATS direto antes do agregador).
5. **Salário:** a remuneração das APIs (`compensation` no Ashby e no SmartRecruiters) fica na bronze e
   será normalizada no passo de salário e moeda (PR G). Com a bronze de 90 dias, o histórico recente
   poderá ser reprocessado.
6. **Workday continua fora:** não há API pública documentada.

## Consequências

- Os adaptadores só rodam quando houver empresa `ativa` com `ats: ashby` ou `ats: smartrecruiters` no
  catálogo. Hoje não há nenhuma: as empresas entram por curadoria, com o quadro conferido. A
  descoberta assistida vem no PR D.
- **Primeira execução depois do merge (Lever):** a descrição maior pode trazer competências novas nas
  vagas da CI&T já conhecidas. Essas vagas aparecem uma vez como "requisitos alterados", efeito da
  coleta mais completa e não de mudança na vaga.
- A geografia passou para a versão 1.0.1: blocos regionais ("European Union", "EMEA"…) não viram cidade.
  O histórico é recalculado uma vez, e as chaves do Brasil não mudam.
- **Custo do SmartRecruiters:** uma requisição por página de 100 vagas mais uma por vaga relevante, com a
  pausa da fonte entre elas. Uma empresa com centenas de vagas de dados aumenta o tempo do job. A
  duração por quadro fica em `meta/board_runs`.
