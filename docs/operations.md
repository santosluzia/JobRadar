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
| Adzuna | Limite de chamadas do plano da conta (consulte o painel) | 1 chamada por termo por execução (9 termos × 4 = 36/dia) |

Não há custo previsto. A dependência externa crítica é o formato do endpoint da Gupy.

## 7. Painel privado

```bash
cd ../jobradar-data && git pull          # traz o histórico gerado pelo Actions
cd ../jobradar && streamlit run app/main.py
```

Candidaturas e progresso de estudos registrados no painel são gravados em `jobradar-data/private/`. Faça `git commit` e `git push` no `jobradar-data` depois de usar o painel, para que a próxima execução do Actions não sobrescreva seus registros. O workflow tenta `pull --rebase` antes de desistir do push.

## 8. Diagnóstico

| Sintoma | Onde olhar |
|---|---|
| Fonte com ❌ | Resumo da execução e `meta/source_runs.erros` |
| Muitos inválidos | `silver/quality_issues` (o formato da fonte pode ter mudado) |
| Site sem atualizar | Passo "Gerar e validar contrato" (erro de schema) e data em `manifest.json` |
| E-mail não chegou | Passo "Enviar e-mail". Nada é registrado em caso de falha, e as vagas voltam na próxima execução |
| Vagas repetidas no e-mail | Não deve ocorrer; verifique se o passo "Persistir registro de notificações" falhou |
