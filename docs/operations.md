# Operação: setup, segredos, custos e limites

## 1. Repositórios

| Repositório | Visibilidade | Conteúdo inicial |
|---|---|---|
| `santosluzia/jobradar` | Público | Este código. Adicione o tópico `destaque` para ele aparecer na seção Projetos do portfólio |
| `santosluzia/jobradar-data` | **Privado** | Vazio, com um commit inicial (ex.: README). O pipeline cria a estrutura. Coloque o seu `private/profile.yaml` |

## 2. Deploy key (acesso mínimo ao histórico privado)

```bash
ssh-keygen -t ed25519 -C "jobradar-actions" -f jobradar-data-key -N ""
```

1. `jobradar-data` → **Settings → Deploy keys → Add deploy key**: cole `jobradar-data-key.pub` e marque **Allow write access**.
2. `jobradar` → **Settings → Secrets and variables → Actions → New repository secret**: crie `JOBRADAR_DATA_DEPLOY_KEY` com o conteúdo de `jobradar-data-key` (a chave privada).
3. Apague os dois arquivos locais da chave.

A chave só acessa o `jobradar-data`. Não use token pessoal (PAT) com escopo amplo.

Se o repositório de dados tiver outro nome, crie a variável `JOBRADAR_DATA_REPO` (Actions → **Variables**) com `dono/nome`.

## 3. Secrets do workflow

| Secret | Obrigatório | Uso |
|---|---|---|
| `JOBRADAR_DATA_DEPLOY_KEY` | sim | Ler e gravar o histórico privado |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` | para e-mail | Gmail: `smtp.gmail.com`, `587`, uma [senha de app](https://myaccount.google.com/apppasswords) (exige verificação em duas etapas) |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | opcional | API Adzuna. Sem eles, a fonte é ignorada |

O `GITHUB_TOKEN` é automático. O workflow pede só `contents: write`, que vale **apenas** para este repositório (branch `public-data`).

## 4. Primeira execução

1. Em **Actions → Pipeline diário → Run workflow**, rode com "Enviar e-mail" desmarcado.
2. No resumo da execução, confira a tabela por fonte. Se a Adzuna mostrar `❌` ou 0 registros, a cobertura BR ou a chave precisa de ajuste.
3. Verifique se a branch `public-data` foi criada e se `v1/manifest.json` abre no navegador.
4. Rode de novo com e-mail. Depois configure o disparo externo (seção 5.1); a partir daí o agendamento assume.

## 4.1 Incluir uma empresa (catálogo)

O caminho normal é a fila de curadoria (ADR 0012):

1. **Detectar:** `jobradar empresas detectar <URL>`, com a página de carreiras da empresa ou o link de uma vaga.
   O comando mostra o ATS, o quadro e a verificação: vagas no total, de dados, no Brasil e no alvo
   (Brasil, Portugal e América Latina), países e o nome que a API informa.
   - Se a página não puder ser lida (robots.txt, login, erro), cole o link de uma vaga aberta no navegador.
2. **Pôr na fila:** repita com `--adicionar --nome "Nome" --pais BR --segmento tecnologia [--id id]`. A
   empresa entra em `config/empresas.yaml` como `status: candidata`, que não é coletada.
3. **Revisar:** abra o quadro no navegador e confira se ele é mesmo da empresa.
   - Se a API informar outro nome (quadro publicado por um parceiro), acrescente `nome_fixo: true` na entrada.
   - `jobradar empresas listar --status candidata` mostra a fila, e `jobradar empresas verificar [ID]`
     confere de novo.
4. **Aprovar:** `jobradar empresas aprovar <ID>`. Exige uma verificação de até 7 dias sem pendências e
   grava `status: ativa` com `verificada_em`. `--forcar` aprova com pendências e registra isso em
   `observacoes`.
   - Para tirar da fila: `jobradar empresas descartar <ID> --motivo "…"`.
5. **Levar para a main:** `pytest -q tests/unit/test_empresas.py` valida o catálogo. Leve a alteração por PR;
   depois do próximo turno, confira com `jobradar empresas listar`.

Também dá para editar o YAML à mão, como antes: entrada com `status: ativa` e `verificada_em` = data da
conferência do quadro público (`boards.greenhouse.io/<token>`, `jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<quadro>`
ou `api.smartrecruiters.com/v1/companies/<id>/postings`). Empresa que deixou de usar o ATS: `status: pausada`
(mantém o histórico) em vez de apagar a entrada.

## 5. Agendamento e fuso

- Quatro execuções por dia, uma a cada 6 horas. Com a tarefa no fuso de São Paulo (UTC−3; o Brasil não tem horário de verão desde 2019): **00:00, 06:00, 12:00 e 18:00**.
- Quem dispara no horário é o **cron-job.org** (seção 5.1), chamando a API do GitHub (`workflow_dispatch` com `origem=agendador`). O disparo pela API começa em segundos.
- O cron do próprio GitHub fica **só de reserva**: `13 3,9,15,21` UTC (00:13, 06:13, 12:13 e 18:13 em SP). Ele não garante horário: em 17 e 18/10/2026 a execução das 06:47 só começou depois das 10h, e às vezes ela nem acontece.
- O job `checar` consulta a API do Actions (`actions: read`) e calcula o turno de 6 horas pela hora de criação da execução em São Paulo, com os limites 30 min antes da hora cheia: madrugada 23:30–05:29, manhã 05:30–11:29, tarde 11:30–17:29, noite 17:30–23:29. Disparos na hora cheia caem sempre um em cada turno, esteja a tarefa do cron-job.org em São Paulo ou em UTC. Se já houve uma execução **agendada** (cron-job.org ou reserva) com sucesso no mesmo turno, a execução termina em segundos, sem coletar e sem e-mail. Se a do cron-job.org falhou ou não chegou, a reserva do GitHub roda quando sair da fila.
- **E-mail:** cada turno manda e-mail só com as vagas ainda não enviadas. O turno da manhã (06:00) manda mesmo sem vaga nova (serve de alarme se a coleta parar); os outros só mandam se houver vaga nova (`jobradar notify --pular-se-vazio`).
- Execuções manuais (**Run workflow**, com origem `manual`) sempre rodam, mandam e-mail se "Enviar e-mail" estiver marcado e não contam para o turno.
- Workflows agendados pelo cron do GitHub são **desativados após 60 dias sem atividade** no repositório. Os commits vão para a branch `public-data`; se o GitHub desativar mesmo assim, reative em Actions. O disparo pelo cron-job.org não depende disso.

### 5.1 Disparo externo (cron-job.org)

**Token do GitHub** (só dispara execuções deste workflow):

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Repository access:** *Only select repositories* → `santosluzia/JobRadar`.
3. **Permissions → Repository permissions → Actions:** *Read and write*. Nada mais.
4. Anote a data de expiração: quando vencer, o cron-job.org passa a receber `401` e só as reservas do GitHub rodam.

**Tarefa no [cron-job.org](https://cron-job.org)** (conta gratuita), em **Create cronjob**:

| Campo | Valor |
|---|---|
| URL | `https://api.github.com/repos/santosluzia/JobRadar/actions/workflows/daily-pipeline.yml/dispatches` |
| Execution schedule | *Every 6 hours* (ou *Custom*: horas `0`, `6`, `12`, `18`, minuto `0`) |
| Time zone (em *Advanced*) | `America/Sao_Paulo` |
| Request method | `POST` |
| Headers | `Accept: application/vnd.github+json` · `Authorization: Bearer <token>` · `X-GitHub-Api-Version: 2022-11-28` · `Content-Type: application/json` |
| Request body | `{"ref":"main","inputs":{"origem":"agendador"}}` |
| Notifications | ligue o aviso de falha |

Use **Test run**: a resposta esperada é `204 No Content`, e em Actions aparece uma execução **"Agendado (cron-job.org)"**. Se o teste cair num turno que já rodou, essa execução termina em segundos (é o esperado).

## 6. Custos e limites (camadas gratuitas)

| Recurso | Limite relevante | Uso estimado |
|---|---|---|
| GitHub Actions | Gratuito para repositórios públicos em runners padrão | ~6–12 min/dia (4 execuções + reservas que terminam em segundos) |
| Repositório privado | Arquivos individuais acima de 50 MB geram alerta; acima de 100 MB são bloqueados | Tabelas Parquet de poucos MB |
| cron-job.org | Gratuito | 4 chamadas/dia |
| raw.githubusercontent.com | Uso razoável; cache de alguns minutos | 4 arquivos pequenos por visita |
| Gmail SMTP | Limite diário de envios da conta | até 4 e-mails/dia |
| Adzuna | Limite de chamadas do plano da conta (consulte o painel) | 1 chamada por termo por execução (20 termos × 4 = 80/dia, ~2.400/mês; confira se cabe no plano antes de acrescentar termos) |

Não há custo previsto. A dependência externa crítica é o formato do endpoint da Gupy.

A extração de competências não usa API paga nem envia texto a terceiros (ADR 0001). A camada
semântica opcional roda local. Se for ligada, o modelo (~530 MB) é baixado uma vez do Hugging Face por
revisão fixa. Nesse caso, ponha `JOBRADAR_MODEL_CACHE` num `actions/cache`. Enquanto desligada, o CI
não instala `.[semantica]`.

## 6.2 Currículo (privado, só local)

```bash
pip install -e ".[curriculo]"                       # pypdf + python-docx, versões fixas
jobradar curriculo importar ~/Documentos/cv.pdf --nota "versão de novembro"
jobradar curriculo mostrar                          # o que foi entendido (⚠️ = revisar empresa/cargo)
jobradar curriculo exportar > cv.json               # editar à mão e…
jobradar curriculo importar cv.json                 # …salvar como nova versão
jobradar curriculo comparar                         # duas últimas versões
jobradar curriculo diagnostico --objetivo engenharia_dados --salvar
jobradar curriculo historico
jobradar curriculo apagar --versao <id>             # ou --tudo
```

- **Onde ficam os dados:** em `$JOBRADAR_HOME` (padrão `~/.jobradar`), **fora do git**. A pasta se recusa
  a ficar dentro de um repositório. Faça backup por conta própria, se quiser (por exemplo, cópia
  criptografada); por decisão, ela não vai para o `jobradar-data`.
- **No painel:** a página **Meu currículo** faz o mesmo (importar, revisar e corrigir, versões e diagnóstico).
- **Objetivos profissionais:** ficam no `profile.yaml`, em `objetivos:` (veja
  `config/profile.example.yaml`). Ao mudar o perfil, a próxima execução recalcula os scores de todos
  os objetivos.

## 6.3 Minha Evolução Profissional (privado)

```bash
jobradar evolucao plano --objetivo engenharia_dados          # prioridades, classes e recomendações
jobradar evolucao plano --salvar                             # guarda no histórico local
jobradar evolucao progresso aws em_estudo
jobradar evolucao progresso aws demonstrada_em_projeto --evidencia "github.com/voce/projeto-aws"
jobradar evolucao historico
```

- **Progresso:** fica no `jobradar-data` (`private/study_progress`). Faça commit e push para a próxima
  execução recalcular os scores.
- **Sem evidência:** "demonstrada em projeto" e "comprovada em experiência" contam como em desenvolvimento
  até você registrar a evidência.
- **Conteúdo de estudo:** "o que estudar", "projeto" e "como mostrar no currículo" vêm de
  `config/evolucao.yaml`. É sugestão editável.
- **Pesos e corte de prioritárias:** `config/scoring.yaml → evolucao`.

## 6.4 Radar Profissional (e-mail diário)

```bash
jobradar radar --dry-run --html-out radar.html   # prévia: não envia nem registra
jobradar radar --forcar                          # envia agora, ignorando horário e duplicidade
jobradar curriculo compartilhar-resumo           # opcional: só competência → nível, para o Radar no CI
jobradar curriculo remover-resumo
```

- **Configuração:** copie `config/radar.example.yaml` para `jobradar-data/private/radar.yaml` e faça commit e
  push. Campos: ativo, horário (turno), dias da semana, frequência, objetivo e limites. Sem o arquivo, o
  Radar sai todo dia às 06:00 no lugar do e-mail da manhã; para manter o e-mail antigo, use `ativo: false`.
- **No workflow:** o passo "Enviar e-mail" passa `--turno`; o `notify` decide entre o Radar e o alerta de vagas.
- **Falha de envio:** fica registrada em `private/radar_envios` como `falha`, e o próximo turno do mesmo dia tenta de novo.

## 6.5 Relatório Semanal

```bash
jobradar semanal --dry-run --html-out semanal.html   # prévia: não envia nem registra
jobradar semanal --forcar                            # envia agora
```

- **Configuração:** seção `semanal:` do `private/radar.yaml` (ativo, dia, horário, objetivo, limite). O padrão
  é segunda 12:00, num e-mail separado do Radar.
- **Comparação de versões do currículo no CI:** compartilhe o resumo a cada versão nova
  (`jobradar curriculo compartilhar-resumo`).
- **Consulta:** página "Relatório semanal" do painel, que gera o relatório sob demanda e mostra o histórico.

## 6.6 Diagnóstico mensal

```bash
jobradar mensal --dry-run --html-out mensal.html   # prévia: não grava nem envia
jobradar mensal --forcar                           # grava o retrato do mês e envia agora
```

- **Configuração:** seção `mensal:` do `private/radar.yaml` (ativo, dia, horário). O retrato do mês é gravado
  sempre, mesmo com o e-mail desativado, porque é o histórico.
- **Consulta:** painel → Career Intelligence → Diagnóstico mensal. "Minha compatibilidade" compara objetivos e
  versões do currículo.

## 6.1 Extração de competências: comandos

| Comando | Para quê |
|---|---|
| `jobradar reextrair` | Reaplica a taxonomia atual às vagas com descrição numa versão antiga (roda em toda execução do workflow; `--todas` força tudo) |
| `jobradar competencias candidatas` | Fila de curadoria: termos que a taxonomia não cobre |
| `jobradar avaliacao amostrar` / `medir` | Conjunto-ouro privado e precisão/recall (docs/avaliacao.md) |
| `jobradar coocorrencia [--skill X] [--familia F] [--senioridade S] [--dias 90]` | Competências que aparecem juntas (ADR 0002) |
| `jobradar enriquecer` | Camada semântica local nas vagas pendentes (requer `pip install -e ".[semantica]"` e `extracao.semantica.ativa: true`, ou `--forcar`) |

**Ao publicar uma versão nova da taxonomia:**
1. A próxima execução do workflow reextrai o histórico (~30 s para ~8 mil vagas).
2. Os percentuais públicos de skill-trends mudam de patamar. Na 2.0.0, por exemplo, qualidade de
   dados passou de 7,4% para 18,3% das vagas de dados. É melhora da medição, não mudança do
   mercado: explique no portfólio, se os números forem exibidos.

## 6.7 Privacidade, segurança e saúde (Etapa 8)

- **Parte pessoal no repositório privado:** passo a passo em [docs/privacidade.md](privacidade.md), seção 2
  (variável `JOBRADAR_NOTIFICACAO_PRIVADA` nos dois repositórios, secrets SMTP no `jobradar-data`).
- **Retenção e apagamento:**

  ```bash
  jobradar privacidade limpar                     # 12 versões de currículo, 24 meses de diagnósticos/planos
  jobradar privacidade apagar-tudo --confirmar    # pasta local inteira + resumo do currículo no lake
  ```

- **Saúde da operação:** `jobradar saude` (também no resumo do Actions, na Visão geral e no rodapé do
  Radar quando há alerta). Limites em `config/sources.yaml → saude`; detalhes em
  [docs/rastreabilidade.md](rastreabilidade.md).
- **Qualidade por fonte e formato das respostas** (ADR 0013):

  ```bash
  jobradar qualidade                      # nota e indicadores por fonte (30 dias; --dias N, --json)
  jobradar qualidade formato              # assinatura atual e mudanças registradas (--fonte gupy)
  jobradar qualidade reconstruir-formato  # refaz o histórico de assinaturas com a bronze (90 dias)
  ```

  Alerta "formato da fonte X mudou (essenciais em queda: …)": a fonte trocou ou tirou um campo que o
  coletor usa. Abra a bronze mais recente da fonte (`bronze/source=X/`), veja o campo novo e ajuste o
  `to_raw_job` e o `CAMPOS_ESSENCIAIS` do coletor. O alerta some sozinho depois de 24 horas, porque o
  formato novo vira a referência.
- **Atualizar uma action fixada por SHA:**

  ```bash
  gh api repos/actions/checkout/git/ref/tags/v4.4.0 --jq .object.sha
  ```

  Troque o SHA e o comentário de versão nos dois workflows. Se `.object.type` for `tag`, resolva mais
  uma vez em `git/tags/<sha>`.

## 7. Painel privado

```bash
cd ../jobradar-data && git pull          # traz o histórico gerado pelo Actions
cd ../jobradar && streamlit run app/main.py
```

O painel só escuta em `localhost` e não envia telemetria (`.streamlit/config.toml`).

Candidaturas e progresso de estudos registrados no painel são gravados em `jobradar-data/private/`. Faça `git commit` e `git push` no `jobradar-data` depois de usar o painel, para que a próxima execução do Actions não sobrescreva seus registros. O workflow tenta `pull --rebase` antes de desistir do push.

## 8. Diagnóstico

| Sintoma | Onde olhar |
|---|---|
| Fonte com ❌ | Resumo da execução e `meta/source_runs.erros` |
| Muitos inválidos | `silver/quality_issues` e `jobradar qualidade formato` (o formato da fonte pode ter mudado) |
| Fonte trazendo pouca vaga útil | `jobradar qualidade`: relevância, descrição completa e campos por fonte |
| Site sem atualizar | Passo "Gerar e validar contrato" (erro de schema) e data em `manifest.json` |
| E-mail não chegou | Passo "Enviar e-mail". Nada é registrado em caso de falha, e as vagas voltam na próxima execução |
| Vagas repetidas no e-mail | Não deve ocorrer; verifique se o passo "Persistir registros da execução" (ou "Persistir" do workflow privado) falhou |
| E-mail parou depois de ligar a variável | Workflow "Parte pessoal" no `jobradar-data`: a variável precisa existir lá também, e os secrets SMTP também |
| Alerta de saúde | `jobradar saude`; cada alerta aponta a fonte, a taxa ou a validação |
| Validação falhou | `meta/validacoes` (contrato, taxonomia) e `private/validacoes` (perfil, radar.yaml) |
| Competência estranha numa vaga | `silver/job_skills.evidencia` mostra a frase que gerou o achado, e `metodo` mostra se foi termo ou conceito. Ajuste a regra, suba a versão e meça (docs/taxonomia.md) |
| Taxonomia não carrega | Erro de validação Pydantic aponta o campo. Cuidado com `no`/`on` sem aspas e com `\b` entre aspas duplas (escreva `\\b`) |
