# ADR 0001 — Extração de competências híbrida, local e sem custo

- **Status:** aceito (Etapa 1)
- **Data:** 2026-11-12
- **Decisores:** dona do projeto (requisito "totalmente seguro e sem custos")

## Contexto

A extração v1 era um conjunto de regex sobre 36 competências técnicas, sem versão, sem evidência
e sem medição de qualidade. Ela só reconhecia o nome da ferramenta ("Airflow"). Frases como
"pipelines escaláveis", "garantir a integridade dos dados" ou "processamento distribuído" passavam
batidas. Na Gupy, que entrega a descrição numa linha só, um "Diferenciais:" colado no texto
marcava a linha inteira como desejável, inclusive SQL e Python obrigatórios. E o texto institucional
("aplicamos inteligência artificial em nossos processos") contava como requisito.

A primeira proposta usava um LLM pago (Claude) para a camada semântica. Ela foi descartada pelo
requisito do projeto: **nenhum custo, nenhum dado enviado a terceiros, nenhum segredo novo**.

## Decisão

1. **Regras ampliadas e versionadas (`config/skills.yaml` 2.0.0)**, ativas por padrão:
   - **termos e sinônimos** (método `termo`, confiança alta);
   - **conceitos**, isto é, frases que implicam a competência (método `conceito`, confiança média);
   - **segmentação** que separa cabeçalhos e listas colados (Gupy);
   - **seções de contexto** (empresa, benefícios, processo seletivo) e frases institucionais não geram competência;
   - **frases de formação** ("Graduação em Estatística") não contam para competência que também é nome de curso;
   - competências **comportamentais e de idioma**, guardadas só na silver, para uso privado;
   - cada achado guarda **evidência** (a frase original, recortada em volta do trecho), método,
     confiança e versão da taxonomia.
2. **Camada semântica local (embeddings)**, implementada, testada e **desligada por padrão**:
   - **modelo:** `minishlab/potion-multilingual-128M` (model2vec, licença MIT), com revisão
     fixa e SHA-256 conferido a cada carga;
   - roda na CPU, sem chamada externa além do download do arquivo público do modelo;
   - só complementa: atua em competências que as regras não acharam, fora do título, do contexto e dos cabeçalhos;
   - grava em tabela separada (`silver/job_skills_semantica`) e só entra em gold, score e dados
     públicos com `extracao.gold_hibrida: true`.
3. **Conjunto-ouro privado e medição reprodutível** (`jobradar avaliacao medir`). Toda mudança de
   regra passa por ele.
4. **Fila de curadoria** (`jobradar competencias candidatas`): termos frequentes nas vagas de
   dados que a taxonomia não cobre, ranqueados por lift e por cara de nome de ferramenta. Ela só sugere.
5. **Histórico alinhado à versão**: `jobradar reextrair` roda em toda execução do workflow. Não
   faz nada se o histórico já está na versão atual. Mudança de taxonomia não é registrada como
   "mudança de requisito" da vaga.

## Medição (conjunto-ouro, competências técnicas)

60 vagas das famílias de dados, estratificadas entre descrição completa (ATS) e trecho de ~500
caracteres (Adzuna):
- **Lote "ajuste" (40 vagas):** usado para calibrar as regras.
- **Lote "teste" (20 vagas):** sorteado **depois** do ajuste e anotado **sem ver** a saída do extrator. É o número que vale.

> ⚠️ As anotações são um **rascunho** feito pelo assistente (`anotador: rascunho-claude`,
> `revisado: false`), seguindo docs/avaliacao.md. Os números valem como indicação até a revisão humana.
> Quem escreveu as regras também anotou, então há viés possível; o lote teste existe para reduzi-lo.

| Extrator | Lote | Precisão | Recall | F1 |
|---|---|---|---|---|
| Regras v1 (1.0.0) | teste | 100,0% | 74,5% | 85,4% |
| **Regras v2 (2.0.0)** | **teste** | **98,7%** | **95,7%** | **97,2%** |
| Híbrido v2 + model2vec (limiar 0,65) | teste | 98,1% | 96,3% | 97,2% |
| Regras v1 (1.0.0) | ajuste | 96,8% | 68,5% | 80,2% |
| Regras v2 (2.0.0) | ajuste | 97,8% | 98,7% | 98,3% |
| Híbrido v2 + model2vec (limiar 0,65) | ajuste | 97,8% | 99,0% | 98,4% |

- **Conceitos:** 13 acertos e 0 falsos positivos no lote teste.
- **Importância (requisito × desejável):** acerta 94,2% no teste (90,8% na v1).
- **Comportamentais e inglês:** F1 87,8% no teste.

### Embeddings: dois candidatos locais

Varredura de limiar de 0,40 a 0,85 nos dois lotes:

| Backend | Melhor limiar | Δ F1 teste | Δ F1 ajuste | Velocidade | Download |
|---|---|---|---|---|---|
| **model2vec** potion-multilingual-128M (MIT) | 0,65 | +0,3 p.p. (+1 acerto, 0 erro) | +0,2 p.p. | ~10 ms/vaga | ~530 MB |
| fastembed paraphrase-multilingual-MiniLM-L12-v2 quantizado (Apache-2.0) | 0,75 | +0,9 p.p. (+4 acertos, +1 erro) | −0,5 p.p. | ~510 ms/vaga | ~220 MB |

O **model2vec** foi escolhido porque não acrescenta falso positivo e é 50× mais rápido.

O enriquecimento de 7.093 vagas do histórico real leva 32 s e acrescenta achados em 2,6% das
vagas. O ganho mais claro está em texto em **espanhol** e em paráfrases ("Modelamiento y
transformación de datos").

**Por que desligada:** o ganho medido (+1 acerto em cada lote) está dentro do ruído de 60 vagas
em rascunho. Não justifica baixar ~530 MB e conferir o hash (~15 s) a cada execução no CI.

**Quando reavaliar:** com o conjunto-ouro revisado e maior (≥150 vagas), ou quando a fila de
candidatas e os erros mostrarem lacunas de paráfrase que as regras não cobrem bem.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| LLM via API (Claude Haiku/Sonnet) | Custo recorrente; envio de texto para terceiro; segredo novo. Fere o requisito do projeto |
| LLM local (Ollama) no CI | Modelos de GBs, minutos por vaga na CPU do Actions; ganho não demonstrado sobre as regras |
| fastembed (MiniLM multilíngue) | Mais lento (50×) e com mais falsos positivos que o model2vec no mesmo conjunto-ouro |
| Raspar a página da Adzuna para ter a descrição completa | Termos de uso e fragilidade. O trecho de 500 caracteres já rende F1 ~100% no lote teste (8 vagas) |

## Consequências

- **Dados públicos mudam de patamar**, não de formato. O contrato v1 é o mesmo; entram 5
  competências técnicas novas: IA/ML, Big Data/Processamento distribuído, Estatística, Excel e
  Kubernetes. Na janela de 90 dias do histórico real, por exemplo:
  - Qualidade de dados: de 7,4% para 18,3%;
  - Governança: de 10,3% para 19,3%;
  - ETL: de 22,7% para 27,2%.

  Ferramentas citadas por nome quase não mudam. Isso é melhora de medição, não mudança de mercado,
  e deve ser explicado onde os números forem exibidos.
- O workflow ganha o passo "Alinhar histórico à versão da taxonomia" (segundos quando não há nada a fazer).
- Toda mudança de regra exige subir `versao`, medir no conjunto-ouro e registrar em docs/taxonomia.md.
- A camada semântica é dependência opcional (`pip install -e ".[semantica]"`), fora do CI enquanto desligada.
