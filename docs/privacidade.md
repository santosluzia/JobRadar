# Privacidade e segurança

Este documento diz onde fica cada dado, quem pode lê-lo, por quanto tempo fica e como apagá-lo.
A decisão está no [ADR 0008](adr/0008-governanca-seguranca.md).

## 1. Três lugares, três níveis de exposição

| Lugar | Quem lê | O que guarda |
|---|---|---|
| **Repositório público** `JobRadar` e branch `public-data` | qualquer pessoa, inclusive os **logs e resumos do Actions** | código, configuração sem dado pessoal, contrato público (vagas sem descrição, agregados de mercado) |
| **Repositório privado** `jobradar-data` | só você (e o workflow, pela deploy key) | lake (bronze, silver, gold, meta) e `private/`: perfil, progresso, candidaturas, registros de e-mail, resumo do currículo (opcional, só níveis) |
| **Pasta privada local** `$JOBRADAR_HOME` (padrão `~/.jobradar`) | só a sua máquina | currículo (versões, texto extraído, original se você pedir), diagnósticos e planos salvos. Recusa ficar dentro de um repositório git |

**Regra:** nada do `private/` nem da pasta local entra no contrato público. Isso é testado:

- um canário (texto único) é colocado no perfil, no progresso, no `radar.yaml` e no resumo do currículo, e
  não pode aparecer em nenhum arquivo publicado (`tests/integration/test_governanca.py`);
- uma checagem estática garante que o código de publicação não referencia `private/`, `job_scores` nem o perfil.

## 2. A parte pessoal fora do workflow público

Os logs e o resumo de cada execução do Actions no repositório público são públicos. Por isso a parte que usa
dado pessoal (score por vaga e objetivo, e-mails) pode rodar num **workflow do repositório privado**.

Como ligar (uma vez):

1. Faça commit e push do arquivo `jobradar-data/.github/workflows/privado.yml`.
2. Em `jobradar-data` → **Settings → Secrets and variables → Actions**, crie os secrets do e-mail:
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`.
3. Crie a **variável** `JOBRADAR_NOTIFICACAO_PRIVADA` = `true` **nos dois repositórios**.
4. Rode o workflow público uma vez e confira: ele termina sem os passos de score e e-mail, e o workflow
   "Parte pessoal" do `jobradar-data` começa sozinho logo depois do push do lake.
5. Funcionando por alguns dias, apague os secrets de e-mail do repositório **público**.

Enquanto a variável não for `true`, tudo continua como antes (o workflow público pontua e envia).

| | Workflow público | Workflow privado |
|---|---|---|
| Coleta, transformação, taxonomia | ✅ | — |
| Contrato público e `public-data` | ✅ | — |
| Perfil na memória | ❌ (`--sem-pontuacao` descarta) | ✅ |
| Score (`gold/job_scores`) | ❌ | ✅ `jobradar pontuar` (só o que mudou) |
| E-mail (Radar, semanal, mensal, turno) | ❌ | ✅ |
| Secrets | Adzuna, deploy key | SMTP |

## 3. Segredos

- Os secrets ficam só nos secrets do GitHub (ou no `.env` local, ignorado pelo git).
- **Máscara em duas barreiras** (`jobradar.seguranca`): os erros das fontes e o resumo do Actions passam
  por `mascarar`, e todo log passa por um filtro. Somem os valores dos secrets conhecidos, pares
  `app_key=…`, `token=…`, `password=…` e cabeçalhos `Bearer …`.
- Actions de terceiros são fixadas por **SHA do commit** (a tag pode ser movida; o SHA não), com a versão
  em comentário.

## 4. Painel

`.streamlit/config.toml` liga o painel só em `localhost` (não fica acessível pela rede) e desliga a
telemetria do Streamlit.

## 5. Retenção

| Dado | Onde | Retenção |
|---|---|---|
| Versões do currículo (com o original e os diagnósticos de cada uma) | pasta local | as **12** mais recentes |
| Diagnósticos do currículo e planos salvos | pasta local | **24 meses** |
| Resumo do currículo (só níveis) e histórico | `private/` | até você remover |
| Perfil, progresso, candidaturas, registros de e-mail | `private/` | indefinida (é o seu histórico) |
| Validações | `meta/validacoes`, `private/validacoes` | indefinida (é a rastreabilidade) |

Os limites ficam em `config/scoring.yaml → privacidade`. A regra roda a cada importação de currículo e com:

```bash
jobradar privacidade limpar
```

## 6. Apagar tudo

```bash
jobradar privacidade apagar-tudo --confirmar
```

Apaga a pasta privada local inteira e o resumo do currículo (com o histórico) no lake. Não tem volta.
Depois, faça commit e push no `jobradar-data`.

**Ficam** (são configuração e histórico que você controla no repositório privado): `private/profile.yaml`,
progresso, candidaturas e registros de e-mail. Apague os arquivos à mão se quiser.

**Histórico do git.** Um arquivo apagado continua nos commits antigos do `jobradar-data`. Para tirá-lo também
de lá, reescreva o histórico (operação destrutiva, faça backup antes):

```bash
pip install git-filter-repo
cd ../jobradar-data
git filter-repo --path private/curriculo_resumo.json --path private/curriculo_resumos_historico.json --invert-paths
git push --force origin main
```

Como o repositório é privado, o histórico só é visível para você; reescrevê-lo é opcional.

## 7. O que nunca acontece

- Currículo, perfil ou score enviados a serviço externo: nenhuma API paga, nenhuma IA remota. A camada
  semântica é local e vem desligada.
- Dado pessoal em log ou resumo público: o workflow público só imprime agregados de mercado e da operação.
- Texto do currículo no CI: só os níveis, e só se você optar (`jobradar curriculo compartilhar-resumo`).
