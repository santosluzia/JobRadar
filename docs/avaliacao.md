# Avaliação da extração (conjunto-ouro)

## Onde fica

`<lake>/avaliacao/conjunto_ouro.yaml`, no repositório **privado** `jobradar-data`. Guarda o texto das
vagas (conteúdo de terceiros, copiado para a avaliação não depender da retenção da silver) e as
anotações. Nada disso vai para o contrato público. O relatório de medição só tem métricas agregadas
e ids de competência.

## Fluxo

```bash
# 1. sortear vagas (estratifica descrição completa × trecho da Adzuna; não repete as que já estão)
jobradar avaliacao amostrar --completas 25 --trechos 15 --semente 42 --lote ajuste

# 2. anotar no YAML: `competencias` (ids), `desejaveis` (subconjunto) e `revisado: true`

# 3. medir (só itens revisados; --incluir-rascunhos para usar os demais)
jobradar avaliacao medir --lote teste --base caminho/da/taxonomia-anterior.yaml
jobradar avaliacao medir --lote teste --semantica      # inclui o híbrido (requer .[semantica])
```

- **Lote `ajuste`:** use para calibrar regras.
- **Lote `teste`:** sorteie **depois** de mexer nas regras e anote **sem olhar** a saída do
  extrator. A métrica oficial é a dele; a do ajuste é otimista por construção.

## Regras de anotação

1. Anote a competência se a **vaga** pede ou cita como parte do trabalho, seja nos requisitos, nas
   responsabilidades ou nos diferenciais.
2. Conta quando uma frase a implica sem ambiguidade. Exemplos: "pipelines de ingestão" → `etl`;
   "garantir a integridade dos dados" → `qualidade_dados`.
3. Ferramenta conta pela competência a que a taxonomia a associa. Exemplos: BigQuery → `gcp` e
   `data_warehouse`; Pandas → `python`; Unity Catalog → `databricks` e `governanca`.
4. **Não** anote o que aparece só no texto sobre a empresa, nos benefícios ou no processo seletivo.
5. **Não** anote formação ("Graduação em Estatística") nem "usar ferramentas de IA" (copilots,
   ChatGPT): `ia_ml` é construir ou aplicar modelos.
6. **Não** anote o que a vaga nega ("não é uma posição de big data/streaming").
7. "Analisar grandes volumes de dados" (analista) não é `processamento_distribuido`. Processar ou
   ingerir em escala, ou citar Spark, Hadoop ou Trino, é.
8. Comportamentais só quando pedidas como competência ("boa comunicação", "trabalho em equipe",
   "equipes multidisciplinares"). Responsabilidades genéricas ("apoiar a resolução de problemas")
   e cultura da empresa ("aqui você tem autonomia") não contam.
9. Competência que falta na taxonomia vai em `notas`. Ela alimenta a fila de curadoria.

## Estado atual

- **60 vagas** (40 ajuste + 20 teste), todas com anotação-**rascunho** feita pelo assistente,
  `revisado: false`. Resultados no ADR 0001.
- **Próximo passo:** revisão humana, isto é, corrigir o que discordar e marcar `revisado: true`.
  Depois, crescer o lote teste.
