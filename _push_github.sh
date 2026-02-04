#!/bin/bash
set -e
cd "$(dirname "$0")"
# Load .env without printing
export $(grep -v '^#' .env | xargs) 2>/dev/null || true
[ -z "$GITHUB_SSH_KEY" ] && { echo "GITHUB_SSH_KEY not set in .env"; exit 1; }

# Get GitHub username
USER=$(curl -s -H "Authorization: token $GITHUB_SSH_KEY" https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin).get('login',''))")
[ -z "$USER" ] && { echo "Could not get GitHub user"; exit 1; }
echo "GitHub user: $USER"

# Create repo if needed (ignore error if exists)
curl -s -X POST -H "Authorization: token $GITHUB_SSH_KEY" -H "Content-Type: application/json" \
  -d '{"name":"RealDeal","description":"Ontario cash-flow property scanner","private":false}' \
  https://api.github.com/user/repos || true

# Remote URL with token for this push only (we will set url back to public after)
REPO_URL="https://${GITHUB_SSH_KEY}@github.com/${USER}/RealDeal.git"
git remote add origin "https://github.com/${USER}/RealDeal.git" 2>/dev/null || git remote set-url origin "https://github.com/${USER}/RealDeal.git"
git push -u "https://${GITHUB_SSH_KEY}@github.com/${USER}/RealDeal.git" main 2>/dev/null || git push -u "https://${GITHUB_SSH_KEY}@github.com/${USER}/RealDeal.git" master 2>/dev/null || true
# If push failed, try with origin
git push -u origin main 2>/dev/null || git push -u origin master 2>/dev/null || { git push -u "$REPO_URL" main 2>/dev/null || git push -u "$REPO_URL" master; }
# Remove token from stored remote
git remote set-url origin "https://github.com/${USER}/RealDeal.git"
echo "Done. Remote origin: https://github.com/${USER}/RealDeal.git"
