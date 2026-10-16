#!/usr/bin/env bash
# Grava o histórico no repositório privado jobradar-data (clonado em $JOBRADAR_LAKE).
# Commits pequenos e frequentes: o próprio git é o log de versões do lake.
set -euo pipefail
MSG="${1:-atualização do lake}"
cd "${JOBRADAR_LAKE:?defina JOBRADAR_LAKE}"
git config user.name "jobradar-bot"
git config user.email "jobradar-bot@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "lake sem alterações"
  exit 0
fi
git commit -q -m "$MSG"
for tentativa in 1 2 3; do
  if git push -q origin HEAD; then echo "lake persistido"; exit 0; fi
  echo "push falhou (tentativa $tentativa), sincronizando…"; sleep $((tentativa * 5))
  git pull -q --rebase origin "$(git rev-parse --abbrev-ref HEAD)"
done
echo "não foi possível persistir o lake" >&2
exit 1
