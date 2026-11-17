# ADR 0012 — Descoberta assistida e fila de curadoria de empresas

- **Status:** aceito (PR D da evolução para inteligência de mercado)
- **Data:** 2026-11-17

## Contexto

O catálogo (ADR 0009) só crescia à mão: alguém achava o quadro de uma empresa, conferia a API e editava
`config/empresas.yaml`. Os adaptadores Ashby e SmartRecruiters (ADR 0011) ficaram sem empresa porque não
havia um caminho simples para achar e conferir quadros. A regra continua: não inventar identificador de
empresa, não fazer rastreamento de sites e não pôr nada na coleta sem conferência humana.

## Decisão

1. **Detecção** (`empresas/deteccao_ats.py`), a partir de um endereço que a pessoa informa:
   - endereço do próprio quadro (`boards.greenhouse.io/x`, `jobs.lever.co/x`, `jobs.ashbyhq.com/x`,
     `jobs.smartrecruiters.com/X`, as APIs públicas e o código de incorporação `?for=x` do Greenhouse):
     reconhecido sem nenhuma requisição;
   - página de carreiras da empresa: o JobRadar lê **uma** página, só se o robots.txt permitir, e procura
     esses endereços nos links, iframes e scripts. O destino de um redirecionamento também conta.
     - Não segue links, não faz login e não insiste em 401/403/429.
     - robots.txt que falha (5xx, rede) ou bloqueado (401/403) = página não consultada (RFC 9309).
   - Gupy e Workday são reconhecidos só para registro: não têm coletor por empresa. O ambiente europeu
     do Greenhouse e do Lever (`*.eu.*`) também fica fora, porque os coletores leem só o endereço global.
2. **Verificação** (`empresas/verificacao.py`): o quadro é lido pelo **próprio coletor** da plataforma,
   com o filtro de título da coleta. O resultado vai para `meta/empresas_verificacoes`: quadro completo,
   vagas no total, vagas de dados, vagas de dados no Brasil e no alvo (Brasil, Portugal e América
   Latina), países e o nome que a API informa (Greenhouse e SmartRecruiters).
3. **Fila de curadoria** = empresas `status: candidata` do catálogo (o status já existia). Os comandos
   editam o YAML como texto, uma entrada por vez, para não apagar comentários. Cada alteração é validada
   com o catálogo inteiro antes de gravar:
   - `jobradar empresas detectar URL --adicionar --nome --pais --segmento` inclui a candidata
     (`origem: descoberta`);
   - `jobradar empresas verificar [ID…]` confere de novo (padrão: as candidatas);
   - `jobradar empresas aprovar ID` → `ativa`, com `verificada_em` = data da verificação usada;
   - `jobradar empresas descartar ID --motivo …` → `descartada`, com o motivo em `observacoes`.
4. **Aprovação exige uma verificação de até 7 dias sem pendências:**
   - quadro respondeu e veio inteiro;
   - ao menos uma vaga de dados no alvo;
   - nome da API compatível com o do catálogo.
   `--forcar` aprova mesmo assim e registra isso em `observacoes`.
5. **Nome da empresa:** `nome_fixo: true` no catálogo faz a coleta usar o `nome` do catálogo no lugar do
   que a API informa (Greenhouse, Lever e SmartRecruiters; no Ashby o nome já vem do catálogo). O padrão
   é `false`: as empresas atuais continuam com o nome da fonte, e o histórico e as chaves de
   deduplicação não mudam.

## Consequências

- **Primeiras candidatas:** os dois quadros da Artefact no Greenhouse.
  - `artefact`: é o quadro oficial, citado na página de carreiras da empresa. Tem 72 vagas de dados,
    3 delas no Brasil.
  - `artefactlinkedin`: tem 64 vagas de dados, 27 no alvo. A API informa a empresa como "LinkedIn Job
    Wrapping", então a aprovação exige `nome_fixo: true` e a conferência de que o quadro é mesmo da
    Artefact.
  - Se os dois forem aprovados, as vagas repetidas entre eles se fundem pela chave alternativa, porque
    a empresa, o título e o local são os mesmos.
- **Páginas inacessíveis:** sites que recusam o robô no robots.txt ou respondem erro a ele ficam sem
  detecção automática (exemplo: em 2026-11-17, o robots.txt do Nubank respondeu HTTP 500 para o
  JobRadar). Nesse caso, a pessoa cola o link de uma vaga, que já identifica o quadro.
- **Países não identificados:** a contagem por país usa a geografia (ADR 0010). Países fora da tabela
  dela (Marrocos, Suíça, Bélgica…) e cidades sem UF que ela não conhece aparecem como "?". Nenhum
  desses casos é do Brasil, de Portugal ou da América Latina, então a contagem do alvo não é afetada.
- **Onde ficam as verificações:** `meta/empresas_verificacoes` fica no histórico local de quem roda o
  comando. A aprovação lê a última verificação desse mesmo histórico. O catálogo editado vai para a main
  por PR, como qualquer configuração.
