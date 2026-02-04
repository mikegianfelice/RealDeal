#!/bin/bash
# One-off: create GitHub repo (if needed) and push using GITHUB_SSH_KEY from .env
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] && export $(grep -v '^#' .env | grep -v '^$' | xargs)
[ -z "$GITHUB_SSH_KEY" ] && { echo "GITHUB_SSH_KEY not set in .env"; exit 1; }

USER=$(curl -s -H "Authorization: token $GITHUB_SSH_KEY" https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin).get('login',''))")
[ -z "$USER" ] && { echo "Could not get GitHub user (check token)"; exit 1; }
echo "GitHub user: $USER"

curl -s -X POST -H "Authorization: token $GITHUB_SSH_KEY" -H "Content-Type: application/json" \
  -d '{"name":"RealDeal","description":"Ontario cash-flow property scanner","private":false}' \
  https://api.github.com/user/repos 2>/dev/null || true

git remote add origin "https://github.com/${USER}/RealDeal.git" 2>/dev/null || git remote set-url origin "https://github.com/${USER}/RealDeal.git"
git push -u "https://${GITHUB_SSH_KEY}@github.com/${USER}/RealDeal.git" main
git remote set-url origin "https://github.com/${USER}/RealDeal.git"
echo "Pushed to https://github.com/${USER}/RealDeal"
