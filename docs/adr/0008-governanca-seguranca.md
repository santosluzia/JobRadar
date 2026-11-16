# ADR 0008 — Governança, segurança e qualidade

- **Status:** aceito (Etapa 8)
- **Data:** 2026-11-15

## Contexto

As etapas 1 a 7 trouxeram dados pessoais (perfil com objetivos, progresso, currículo, score por objetivo,
e-mails com recomendações) para um projeto cujo código, logs e resumos do Actions são **públicos**.

O diagnóstico da Etapa 8 encontrou estas lacunas:

1. O painel Streamlit escutava em todas as interfaces e enviava telemetria.
2. O workflow público carregava o perfil, calculava score e enviava e-mails, com os secrets SMTP no
   repositório público.
3. O resultado das validações (contrato, taxonomia, perfil) não ficava registrado.
4. Não havia regra de retenção nem forma de apagar tudo dos dados pessoais locais.
5. O monitoramento era parcial (tabela por fonte no resumo).
6. As actions eram referenciadas por tag, que é móvel.
7. Uma mensagem de erro de biblioteca poderia levar a URL da Adzuna com `app_key`.

Restrição da usuária: "plano totalmente seguro e sem custos". Isso exclui API paga, envio de dado pessoal
a terceiros e novos serviços.

## Decisão

1. **Painel só local.** `.streamlit/config.toml` com `address = "localhost"` e `gatherUsageStats = false`.
2. **Segredos mascarados em duas barreiras** (`jobradar.seguranca`).
   - A primeira é nos erros das fontes e no resumo do Actions.
   - A segunda é um filtro em todo log.
   - Mascara valores dos secrets do ambiente, pares `chave=valor` sensíveis e `Bearer`.
3. **Parte pessoal no repositório privado, com transição segura.**
   - `jobradar run/reextrair --sem-pontuacao`: o perfil sai da memória e nada é pontuado.
   - `jobradar pontuar`: score incremental, rodado pelo workflow `jobradar-data/.github/workflows/privado.yml`.
   - O workflow privado é disparado pelo push do lake (`silver/jobs.parquet`). O push dele usa o
     `GITHUB_TOKEN`, que não redispara workflows.
   - Tudo fica atrás da variável `JOBRADAR_NOTIFICACAO_PRIVADA`. Sem ela, nada muda.
4. **Validações registradas** em `meta/validacoes` (contrato público, taxonomia) e `private/validacoes`
   (perfil, radar.yaml).
   - São tabelas separadas, para que os dois workflows nunca gravem o mesmo arquivo.
   - Para o perfil, o registro guarda só a contagem e o campo, nunca o valor.
5. **Retenção e apagamento.**
   - Retenção: 12 versões de currículo e 24 meses de diagnósticos e planos locais
     (`jobradar privacidade limpar`, também a cada importação).
   - Apagamento: `jobradar privacidade apagar-tudo --confirmar` remove a pasta local e o resumo no lake.
   - A reescrita do histórico do git fica documentada, opcional e manual.
6. **Monitoramento** (`analytics/saude.py`, `jobradar saude`).
   - Indicadores: tempo, volume, falhas, custo de IA (0), extração por fonte, duplicação, qualidade e
     validações.
   - Alertas configuráveis, só com agregados: vão para o resumo do Actions, para a Visão geral e para o
     rodapé do Radar.
7. **Actions fixadas por SHA** do commit da release, com a versão em comentário. Há um teste para isso.
8. **Troca atômica com nova tentativa** no lake: no Windows, antivírus e indexador às vezes seguram o
   arquivo por milissegundos.

## Alternativas descartadas

- **Tornar o repositório de código privado.** Tiraria o projeto do portfólio.
- **Criptografar o `private/` no lake.** Exigiria guardar uma chave em algum lugar e trocar de chave. O
  repositório já é privado; o risco real era o log público.
- **Monitoramento externo** (Grafana Cloud, Sentry, etc.). Envia dados a terceiros e cria conta e
  custo. As métricas cabem no próprio lake.
- **Dependabot para atualizar os SHAs.** Abre PRs automaticamente. Fica como opção futura; a atualização
  manual está documentada.

## Consequências

- O workflow público fica sem dado pessoal na memória, mas só depois que a usuária ligar a variável nos dois
  repositórios e configurar os secrets SMTP no privado (docs/privacidade.md, seção 2).
- Na transição há duas execuções por turno (pública e privada), ambas dentro da cota gratuita: o
  repositório privado usa minutos da conta (2.000 por mês grátis), e a parte pessoal leva cerca de 1 a 2
  minutos por execução.
- Os perfis inválidos aparecem em `private/validacoes`. O erro completo do Pydantic (que inclui o valor)
  só aparece no log do workflow privado.
- **Atualizar uma action:** resolva o SHA da nova tag
  (`gh api repos/actions/checkout/git/ref/tags/vX.Y.Z`) e troque o SHA e o comentário.
