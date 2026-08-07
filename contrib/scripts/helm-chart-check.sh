#!/usr/bin/env bash
set -euo pipefail

chart_dir="${CHART_DIR:-contrib/chart}"
release_name="${HELM_RELEASE_NAME:-centaur}"
namespace="${HELM_NAMESPACE:-centaur}"
aws_render="$(mktemp)"
trap 'rm -f "$aws_render"' EXIT

helm lint "$chart_dir"
helm lint "$chart_dir" -f "$chart_dir/values.dev.yaml"
helm lint "$chart_dir" -f "$chart_dir/values.aws-dev.yaml"

helm template "$release_name" "$chart_dir" -n "$namespace" >/dev/null
helm template "$release_name" "$chart_dir" -n "$namespace" -f "$chart_dir/values.dev.yaml" >/dev/null
# The role migration is a one-shot recovery hook and is disabled in the steady
# state AWS values. Enable it only in this render so its template remains
# covered without scheduling it on every deployment.
helm template "$release_name" "$chart_dir" -n "$namespace" \
  -f "$chart_dir/values.aws-dev.yaml" \
  --set postgres.roleMigration.enabled=true \
  --set postgres.roleMigration.previousUsername=world \
  >"$aws_render"

grep -Fq "postgres-role-migration" "$aws_render"
grep -Fq "REASSIGN OWNED BY %I TO %I" "$aws_render"

# The AWS dev host shares one ingress between Console and Slackbot. Keep the
# Console route ahead of Slackbot's catch-all and retain the SSO wiring.
console_path_line="$(grep -nE '^[[:space:]]+- path: /console$' "$aws_render" | head -1 | cut -d: -f1)"
catch_all_line="$(grep -nE '^[[:space:]]+- path: /$' "$aws_render" | head -1 | cut -d: -f1)"
test -n "$console_path_line"
test -n "$catch_all_line"
test "$console_path_line" -lt "$catch_all_line"
grep -Fq "CENTAUR_CONSOLE_BOOTSTRAP_ADMINS" "$aws_render"
grep -Fq "IRON_CONTROL_GOOGLE_CLIENT_ID" "$aws_render"
