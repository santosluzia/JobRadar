# ADR 0010 — Geografia da vaga e deduplicação fora do Brasil

- **Status:** aceito (PR B da evolução para inteligência de mercado)
- **Data:** 2026-11-17

## Contexto

O local da vaga era só a **UF brasileira**, e a UF entra nas três chaves de deduplicação (alternativa,
remota e republicação). Fora do Brasil a UF é nula. Duas vagas da mesma empresa e do mesmo título em
Lisboa e no Porto caíam, então, na mesma chave e uma delas virava "duplicata". Isso já acontecia nos
quadros do Greenhouse que listam vagas em outros países, e iria piorar com a coleta em Portugal e na
América Latina.

Havia um segundo problema: siglas de país eram lidas como UF ("Madrid, ES" virava Espírito Santo) e
entravam na distribuição por estado.

Pré-requisito para ampliar as fontes: sem ele, cada empresa estrangeira nova esconderia vagas reais.

## Decisão

1. **`transformations/geografia.py`** infere, para cada vaga:
   - `pais_iso` (ISO 3166-1 alfa-2), nesta ordem: campo da fonte (nome ou código) → nome de país no
     local, em português, inglês ou espanhol → cidade que identifica o país sozinha (Lisboa, Bogotá,
     Buenos Aires…) → UF brasileira → não informado. Mais de um país no local ("Brazil or Mexico") fica
     como não informado. A origem vai em `origem_campos.pais`;
   - `uf` só quando o país é o Brasil ou não foi identificado;
   - `regiao` (UF no Brasil, estado ou província normalizado nos demais países) e `cidade_norm`
     (normalizada, com grafias unificadas: "Lisbon" = "Lisboa").
2. **Parte de local das chaves** (`chave_local`, `chave_remota`):
   - Brasil ou país não identificado: a UF (ou vazio), **exatamente como antes**;
   - outros países: `país:cidade` (ou `país:região`);
   - vaga remota: `remoto` no Brasil (ou sem país) e `remoto:<país>` fora. O mesmo anúncio remoto
     repetido por estado continua sendo uma vaga só, mas remoto no Brasil e remoto em Portugal são
     vagas diferentes.
3. **Migração incremental, sem a bronze.** A coluna `geografia_versao` diz com que regras a linha foi
   calculada. Na execução, as vagas com outra versão (ou nula, isto é, gravadas antes) são recalculadas
   a partir das colunas que a silver já guarda (`pais`, `uf`, `cidade`, `local_raw`). O número de chaves
   alteradas vai para `chaves_geografia_alteradas` no relatório da execução. As vagas que trocam de
   canônica recalculam o mês delas na gold, pela regra que já existia.

## Consequências

- **Chaves do Brasil inalteradas.** Há teste comparando com a fórmula antiga. O histórico brasileiro
  não muda de agrupamento.
- Vagas estrangeiras que estavam marcadas como duplicata por engano voltam a ser canônicas na primeira
  execução. As contagens da gold sobem nos meses delas, e isso é correção, não aumento da demanda.
- `uf` deixa de ter siglas de outros países: `market-summary.by_state` pode perder alguns itens errados.
- **Filtro de relevância** (e-mail e `jobs.json`): uma vaga híbrida ou presencial **em outro país**
  deixa de passar como "local não informado" no filtro de locais. Vaga remota continua passando sempre;
  a elegibilidade para remoto internacional fica para o PR G.
- O contrato público **não muda** neste passo. País e cidade entram como campos opcionais no 1.2.0
  (PR G).
- **Limitações:**
  - a lista de países e de cidades é fechada e conservadora: o que não reconhece fica como "não
    informado" e mantém o comportamento antigo;
  - a mesma cidade com grafias que não estão no mapa não se junta. Nesse caso sobram duas vagas, e
    nenhuma vaga real é escondida;
  - "Madrid, ES" sem o nome do país continua sendo lido como Espírito Santo.

## Fora do escopo

Restrição de residência, elegibilidade para remoto internacional e idioma (PR G). O campo `country`
do Lever será lido junto com o novo pacote de coletores (PR C).
