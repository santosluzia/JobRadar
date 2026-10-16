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
4. Rode de novo com e-mail. A partir daí, o agendamento diário assume.

## 5. Agendamento e fuso

- O cron `47 9 * * *` é em UTC: **06:47 em São Paulo** (UTC−3; o Brasil não tem horário de verão desde 2019).
- O GitHub pode atrasar execuções agendadas em horários de pico, às vezes em dezenas de minutos. Por isso o minuto não é cheio.
- Workflows agendados são **desativados após 60 dias sem atividade** no repositório. Os commits diários vão para a branch `public-data`; se o GitHub desativar mesmo assim, reative em Actions.

## 6. Custos e limites (camadas gratuitas)

| Recurso | Limite relevante | Uso estimado |
|---|---|---|
| GitHub Actions | Gratuito para repositórios públicos em runners padrão | ~3–6 min/dia |
| Repositório privado | Arquivos individuais acima de 50 MB geram alerta; acima de 100 MB são bloqueados | Tabelas Parquet de poucos MB |
| raw.githubusercontent.com | Uso razoável; cache de alguns minutos | 4 arquivos pequenos por visita |
| Gmail SMTP | Limite diário de envios da conta | 1 e-mail/dia |
| Adzuna | Limite de chamadas do plano da conta (consulte o painel) | 1 chamada por termo/dia |

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
