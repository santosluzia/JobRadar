#!/usr/bin/env bash
# Publica os JSON validados na branch `public-data` DESTE repositório.
# O site lê de: https://raw.githubusercontent.com/<owner>/<repo>/refs/heads/public-data/v1/<arquivo>.json
# Só roda depois de `jobradar publish` validar o contrato; se algo falhar antes,
# a branch continua apontando para a versão anterior.
set -euo pipefail
SRC="$(cd "${1:?pasta gerada por jobradar publish}" && pwd)"
BRANCH="${2:-public-data}"
[ -f "$SRC/v1/manifest.json" ] || { echo "manifest ausente em $SRC/v1" >&2; exit 1; }

WT="$(mktemp -d)"
trap 'git worktree remove --force "$WT" >/dev/null 2>&1 || true' EXIT
if git fetch -q --depth=1 origin "$BRANCH" 2>/dev/null; then
  git worktree add -q -B "$BRANCH" "$WT" FETCH_HEAD
else
  git branch -D "$BRANCH" >/dev/null 2>&1 || true   # sobra local de uma execução anterior
  git worktree add -q --detach "$WT"
  git -C "$WT" checkout -q --orphan "$BRANCH"
  git -C "$WT" rm -rfq --cached . >/dev/null
  git -C "$WT" clean -fdxq
fi

cd "$WT"
rm -rf v1 && cp -R "$SRC/v1" v1
cat > README.md <<'MD'
# JobRadar — dados públicos

Branch gerada automaticamente pelo pipeline. Não edite à mão.
Contrato: `v1/*.schema.json` · índice: `v1/manifest.json` · documentação: branch `main`, `docs/contracts/`.
MD
git config user.name "jobradar-bot"
git config user.email "jobradar-bot@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then echo "dados públicos sem alteração"; exit 0; fi
git commit -q -m "dados públicos: ${RUN_ID:-manual}"
git push -q origin "$BRANCH"
echo "publicado em $BRANCH"
