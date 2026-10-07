#!/usr/bin/env bash
# Point the Coolify app at one image tag, deploy it, and wait for the outcome.
#
#   COOLIFY_URL=https://coolify.example.org COOLIFY_TOKEN=... COOLIFY_APP_UUID=... \
#     scripts/coolify-deploy.sh <image tag>
#
# What the `deploy` job in .github/workflows/ci-cd.yml runs; works the same from
# a laptop, e.g. to roll back to an earlier commit's tag. The tag is the commit
# SHA the `build` job pushed to GHCR. Exits non-zero unless Coolify reports the
# deployment `finished` — Coolify only swaps containers once the new one passes
# its health check, so `failed` leaves the old version serving.
set -euo pipefail

tag=${1:?usage: coolify-deploy.sh <image tag>}
: "${COOLIFY_URL:?set COOLIFY_URL}" "${COOLIFY_TOKEN:?set COOLIFY_TOKEN}"
: "${COOLIFY_APP_UUID:?set COOLIFY_APP_UUID}"

api="${COOLIFY_URL%/}/api/v1"

call() {
  local method=$1 path=$2
  shift 2
  curl -fsS --max-time 30 -X "$method" "$api$path" \
    -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Accept: application/json" "$@"
}

echo "setting image tag $tag"
call PATCH "/applications/$COOLIFY_APP_UUID" \
  -H "Content-Type: application/json" \
  --data "$(jq -cn --arg tag "$tag" '{docker_registry_image_tag: $tag}')" > /dev/null

deployment=$(call POST "/deploy?uuid=$COOLIFY_APP_UUID" | jq -r '.deployments[0].deployment_uuid')
if [ -z "$deployment" ] || [ "$deployment" = null ]; then
  echo "::error::Coolify queued no deployment" >&2
  exit 1
fi
echo "deployment $deployment queued"

# Pull + migrate + health check normally takes well under a minute; 10 minutes
# covers a slow first pull of the image on a fresh server.
for _ in $(seq 1 120); do
  status=$(call GET "/deployments/$deployment" | jq -r '.status')
  case "$status" in
    finished)
      echo "deployment finished"
      exit 0
      ;;
    failed | cancelled*)
      echo "::error::deployment $status — logs: $COOLIFY_URL (Deployments tab of the app)" >&2
      exit 1
      ;;
  esac
  sleep 5
done
echo "::error::deployment still '$status' after 10 minutes" >&2
exit 1
