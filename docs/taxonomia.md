# Taxonomia de competências

Arquivo: `config/skills.yaml`, validado por Pydantic (`transformations/skills.py`). Um campo
desconhecido, uma regex inválida ou um id repetido fazem o carregamento falhar, em vez de
seguir com a taxonomia errada.

## Campos de uma competência

| Campo | Uso |
|---|---|
| `id` | Identificador estável (minúsculas e `_`). É o que aparece em dados públicos e privados |
| `nome`, `categoria` | Exibição |
| `tipo` | `tecnica` (padrão), `comportamental` ou `idioma`. **Só `tecnica`** vai para gold, score, recomendações, e-mail e dados públicos |
| `padroes` | Regex de **termo** (nome ou sinônimo direto) sobre texto normalizado (minúsculas, sem acento). Método `termo`, confiança `alta` |
| `conceitos` | Regex de **frase que implica** a competência sem citá-la. Método `conceito`, confiança `media` |
| `descricoes` | Frases-âncora da camada de embeddings (desligada por padrão) |
| `ignorar_em_formacao` | Não conta em frase de formação acadêmica ("Graduação em Estatística") |
| `esforco`, `projeto` | Opinião configurável, usada nas recomendações de estudo |

## Como a vaga é lida

1. **Segmentação.** Cabeçalhos e listas colados (comuns na Gupy: "…GCP.- Desenvolver",
   "atribuiçõesArquitetura", "Diferenciais:- Docker") voltam a ser linhas. As linhas viram frases
   (inclusive em ";" e "." sem espaço).
2. **Seções.** Linha curta ou terminada em ":" que começa por um marcador é cabeçalho:
   - `marcadores_desejavel` → desejável;
   - `marcadores_requisito` (requisitos e responsabilidades) → requisito;
   - `marcadores_contexto` (empresa, benefícios, etapas) → contexto, que **não gera competência**.

   O texto antes do primeiro cabeçalho é contexto até uma frase que descreva a vaga (`frases_vaga`).
   Trecho sem cabeçalho (Adzuna) é todo requisito.
3. **Frases.** Frase institucional (`frases_contexto`: "somos…", "acreditamos…") também é contexto.
   "Inglês é um diferencial" na própria frase torna só ela desejável.
4. **Achado.** Por competência fica o melhor: requisito vence desejável; no mesmo nível, termo vence
   conceito. A **evidência** é a frase original (com acentos), recortada em até 240 caracteres em
   volta do trecho que casou.

## Política de versão

`versao` segue `MAIOR.MENOR.CORREÇÃO`:

- **MAIOR**: competência removida ou renomeada, ou mudança de `tipo` (quebra comparações).
- **MENOR**: competência nova, padrão ou conceito novo, mudança de seção ou segmentação.
- **CORREÇÃO**: ajuste que só corrige falso positivo ou falso negativo pontual.

Qualquer mudança que altere o resultado da extração **sobe a versão**. O passo "Alinhar histórico à
versão da taxonomia" do workflow (`jobradar reextrair`) reaplica a régua nova às vagas que ainda
têm descrição; sem isso, a tendência mensal misturaria réguas. Troca de versão nunca é registrada
como "requisitos alterados" da vaga.

### Como mudar

1. Edite `config/skills.yaml` e suba `versao`.
2. `jobradar avaliacao medir --base <yaml da versão anterior>` no conjunto-ouro: a precisão não pode cair sem justificativa.
3. `pytest`.
4. Registre a mudança no histórico abaixo.

## Fila de curadoria

```bash
jobradar competencias candidatas --dias 90 -n 40
```

A fila lista termos frequentes nas vagas de dados que a taxonomia não cobre. A ordem vem de:
- o **lift** entre vagas de dados e as demais (termo genérico aparece igual nos dois grupos);
- a cara de **nome de ferramenta** (inicial maiúscula no meio da frase).

Partes de termos já cobertos são descartadas.

- **Aprovar:** acrescentar padrão ou conceito e subir a versão.
- **Recusar:** acrescentar uma regex em `candidatas.ignorar`.

A fila só sugere; o lift descreve associação na amostra, não causa.

## Histórico

| Versão | Data | Mudança |
|---|---|---|
| 1.0.0 | 2026-10 | 36 competências técnicas por termo; sem versão gravada (linhas antigas = 1.0.0) |
| 2.0.0 | 2026-11-12 | Sinônimos e **conceitos**; 5 técnicas novas (`ia_ml`, `processamento_distribuido`, `estatistica`, `excel`, `kubernetes`); 7 comportamentais e `ingles` (privados); segmentação da Gupy; seções e frases de contexto; frases de formação; evidência, método, confiança e posições de todas as menções (coocorrência) por achado. F1 no lote teste: 85,4% → 97,2% (ADR 0001) |
| 2.1.0 | 2026-11-17 | 5 técnicas de banco de dados: `plsql`, `sql_server`, `mysql`, `tuning_bd` e `administracao_bd`. Junto: família `administracao_dados` e títulos com marcador de gênero ("Engenheiro(a) de Dados"), reclassificados pelo `reextrair` |
| 2.1.1 | 2026-11-17 | Correção: título de ERP/middleware Oracle (BPM, SOA, OIC, EBS, APEX, Fusion…) não vira `desenvolvimento_dados` nem conta pelas competências; o `reextrair` reaplica a família ao histórico |
| 2.1.2 | 2026-11-18 | Família por título de BI e visualização: "Analista de Power BI", "Especialista em BI", "Consultor Qlik Sense" e "Data Visualization" → `analise_dados`; "Desenvolvedor Power BI" e "Desenvolvedor Qlik Sense" → `desenvolvimento_dados`. O cargo precisa vir antes da ferramenta, para "Assistente Administrativo (Excel e Power BI)" continuar `outra`. No histórico, 54 títulos saem de `outra` e nenhum troca de família de dados; o `reextrair` reaplica a família |
| 2.2.0 | 2026-11-18 | Títulos em espanhol ("Ingeniero de Datos", "Desarrollador ETL", "Administrador de Bases de Datos", "Gobierno de Datos", "Analista de Datos") e lacunas em português ("Analista de Inteligência de Dados", "Analista Sr. de Dados", "Análise de Dados", "Assistente de BI", "* Analytics" de produto, negócio e pessoas, "Arquitetura de Dados", "Engenheiro Big Data", "Gestão de Dados"). Senioridade em espanhol: "Semi Senior"/"SSr" → `pleno`, "Practicante"/"Pasante" → `estagio`, "Jefe" → `lideranca`. Idioma `espanhol` (privado). No histórico, ~170 vagas canônicas saem de `outra`; 2 trocam entre famílias de dados; nenhuma competência técnica muda (ADR 0014) |
