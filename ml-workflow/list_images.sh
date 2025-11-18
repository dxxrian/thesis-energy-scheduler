#!/bin/bash
REGISTRY_URL="http://127.0.0.1:5000"

echo "--- Images in der Registry $REGISTRY_URL ---"
REPOS=$(curl -s $REGISTRY_URL/v2/_catalog | jq -r '.repositories[]')

if [ -z "$REPOS" ]; then
    echo "FEHLER: Konnte Registry nicht erreichen."
    exit 1
fi

for REPO in $REPOS; do
  # Holt die Tags für jedes Repo
  TAGS=$(curl -s $REGISTRY_URL/v2/$REPO/tags/list | jq -r '.tags | join(", ")' 2>/dev/null)
  echo "  - $REPO: [$TAGS]"
done
