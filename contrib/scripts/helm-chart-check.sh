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
helm template "$release_name" "$chart_dir" -n "$namespace" -f "$chart_dir/values.aws-dev.yaml" >"$aws_render"

grep -Fq "postgres-role-migration" "$aws_render"
grep -Fq "REASSIGN OWNED BY %I TO %I" "$aws_render"
