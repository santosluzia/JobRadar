# ADR 0003 — Perfil com vários objetivos e análise privada do currículo

- **Status:** aceito (Etapa 3)
- **Data:** 2026-11-12

## Contexto

O perfil (`private/profile.yaml`, no repositório privado) tinha **um** objetivo, com 4 famílias de
cargo misturadas numa única pontuação. A Etapa 3 pede três coisas: vários objetivos com análise
independente; comparar o **currículo** com o que as vagas pedem; e manter tudo privado, sem IA paga
e sem inventar experiência, resultado, ferramenta ou nível.

Dois riscos guiaram o desenho:
- O workflow grava o lake com `git add -A`. Qualquer arquivo de currículo dentro do `jobradar-data`
  iria para o histórico do git, de onde não dá para apagar de verdade.
- O perfil é lido no CI para o score do e-mail. Isso continua, e fica para a Etapa 8.

## Decisão

1. **Perfil v2** (`objetivos: [...]`, validado por Pydantic; o formato antigo vira o objetivo `principal`).
   - As competências são da pessoa. O que muda por objetivo são as vagas-alvo.
   - `gold/job_scores` passa a ter **uma linha por vaga e objetivo** (`objetivo_id`). Listas e e-mail
     usam o melhor objetivo de cada vaga; a análise por objetivo usa só as linhas dele.
2. **Currículo só local**, em `$JOBRADAR_HOME` (padrão `~/.jobradar`):
   - fica **fora de qualquer repositório**, e a pasta se recusa a ficar dentro de um repositório git;
   - o arquivo original não é guardado (só o hash), salvo se você pedir;
   - apagar uma versão apaga de verdade;
   - o CI, o pipeline, a publicação e o e-mail não importam o pacote `jobradar.curriculo` (há teste).
3. **Leitura local sem IA:**
   - `pypdf` (BSD) e `python-docx` (MIT), com limite de 5 MB e conferência do tipo real do arquivo;
   - PDF escaneado é recusado com aviso.
4. **Estruturação por regras** (`curriculo/estrutura.py`):
   - seções, períodos, empresa e cargo;
   - "resultado" só quando a frase do seu texto já tem número ou valor;
   - competências pela mesma taxonomia da Etapa 1, com a frase como evidência.

   Empresa e cargo podem sair errados em layouts incomuns. Por isso há `revisar` e edição manual
   (painel ou JSON), e o campo editado não é sobrescrito numa nova importação.
5. **Níveis de evidência no currículo** (pesos em `scoring.yaml` → `curriculo`):

   | Nível | Peso |
   |---|---|
   | comprovada | 1,0 |
   | em projeto | 0,75 |
   | declarada | 0,5 |
   | parcial (conceito, curso ou certificação) | 0,4 |

   Curso concluído **não** é experiência profissional.
6. **Diagnóstico por objetivo, com duas lentes** (`curriculo/diagnostico.py`):
   - **Aderência do perfil × do currículo:** média das evidências ponderada pela demanda das
     vagas-alvo. Vem geral, por família e por senioridade, sempre com `n` e aviso de amostra pequena.
   - **Listas:** compatíveis, sem evidência no currículo, requisitos recorrentes ausentes,
     "declaradas mas não demonstradas" (o que você marca no perfil e o currículo não mostra),
     a desenvolver (com a coocorrência da Etapa 2), palavras-chave e experiências por relevância.
7. **Sugestões por regra** (`curriculo/sugestoes.py`):
   - cada uma traz o dado que a sustenta;
   - nenhuma escreve fato por você: toda sugestão de incluir algo é condicional ("se você usou…", "se houver…").
8. **Versões e histórico:** comparação entre versões (experiências e competências novas) e
   diagnósticos guardados localmente, com gráfico de evolução por objetivo no painel.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| LLM para estruturar o currículo e redigir sugestões | Custo e envio de dado pessoal a terceiro (API); risco de inventar fatos |
| LLM local (Ollama) | Fora do escopo sem custo e sem manutenção; as regras com revisão manual resolvem a estrutura |
| Guardar o currículo no `jobradar-data` | `git add -A` no workflow e histórico do git: não dá para apagar de verdade |
| Uma pontuação média entre objetivos | A especificação proíbe misturar requisitos de cargos diferentes |

## Consequências e limites

- A interpretação é heurística. A precisão de empresa, cargo e período depende do layout, e a
  revisão manual faz parte do fluxo.
- Os números de aderência dependem do objetivo e da janela (90 dias). Com poucas vagas-alvo, o
  diagnóstico avisa que é indício.
- Backup da pasta privada é responsabilidade da pessoa: ela não está no git, por decisão.
- No Windows, a proteção da pasta é a do perfil do usuário (o `chmod 700` só vale em POSIX).
