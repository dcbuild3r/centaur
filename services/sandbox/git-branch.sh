#!/bin/bash
# git-branch — create a writable working copy from a read-only mounted repo.
#
# Usage:  git-branch <org/repo> <branch slug>
# Example: git-branch owner/centaur fix-flaky-slack-delivery
#
# Creates ~/branches/<org>/<repo> from the read-only repo cache when available,
# otherwise clones from GitHub. The resulting directory is fully writable and
# supports commit, push, and PR workflows.

set -euo pipefail

usage() {
    echo "Usage: git-branch <org/repo> <branch slug>" >&2
    echo "Example: git-branch owner/centaur fix-flaky-slack-delivery" >&2
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

if [ $# -ne 2 ]; then
    usage
    echo "Error: branch slug is required; choose a short descriptive kebab-case name." >&2
    exit 1
fi

REPO="$1"
SLUG="$2"
SRC="$HOME/github/$REPO"
DEST="$HOME/branches/$REPO"

if [[ ! "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    usage
    echo "Error: repository must be in owner/name form." >&2
    exit 1
fi

# Fine-grained PATs are organization-bound. Keep worldcoin and
# worldcoin-foundation on the default placeholder, and select the dedicated
# worldfnd placeholder for that organization. Rebinding GITHUB_TOKEN also makes
# gh's credential helper present the selected placeholder to iron-proxy for
# Git-over-HTTPS operations.
GITHUB_TOKEN_ENV="GITHUB_TOKEN"
if [ "${REPO%%/*}" = "worldfnd" ]; then
    GITHUB_TOKEN_ENV="GITHUB_TOKEN_WORLDFND"
fi

selected_github_token() {
    printf '%s' "${!GITHUB_TOKEN_ENV:-}"
}

# Override inherited/global helpers for this checkout. The helper stores only
# the selected environment-variable name; iron-proxy still receives and
# substitutes the placeholder at request time, and no real token is persisted.
configure_git_credentials() {
    local helper
    helper="!f() { if [ \"\$1\" = get ]; then printf '%s\\n' 'username=x-access-token' \"password=\${$GITHUB_TOKEN_ENV:-}\"; fi; }; f"
    git -C "$DEST" config --local --replace-all credential.helper ""
    git -C "$DEST" config --local --add credential.helper "$helper"
    git -C "$DEST" config --local credential.useHttpPath false
}

# Match commit authorship to the account that will publish the PR so GitHub does
# not preserve a separate sandbox identity as a squash-merge co-author.
configure_git_identity() {
    local name="${CENTAUR_GIT_USER_NAME:-}"
    local email="${CENTAUR_GIT_USER_EMAIL:-}"
    local github_identity_query='[.name // .login,
        .email // ((.id | tostring) + "+" + .login + "@users.noreply.github.com")
    ] | @tsv'

    if [ -n "$name" ] || [ -n "$email" ]; then
        if [ -z "$name" ] || [ -z "$email" ]; then
            echo "Error: CENTAUR_GIT_USER_NAME and CENTAUR_GIT_USER_EMAIL" \
                "must be set together" >&2
            return 1
        fi
    elif command -v gh >/dev/null 2>&1 && [ -n "$(selected_github_token)" ]; then
        local identity
        identity="$({
            GH_PROMPT_DISABLED=1 GH_TOKEN="$(selected_github_token)" \
                gh api user --jq "$github_identity_query"
        } 2>/dev/null || true)"
        IFS=$'\t' read -r name email <<< "$identity"
    fi

    if [ -n "$name" ] && [ -n "$email" ]; then
        git -C "$DEST" config user.name "$name"
        git -C "$DEST" config user.email "$email"
    elif ! git -C "$DEST" var GIT_AUTHOR_IDENT >/dev/null 2>&1; then
        echo "Warning: no Git author identity is configured; set" \
            "CENTAUR_GIT_USER_NAME and CENTAUR_GIT_USER_EMAIL before committing" >&2
    fi
}

if [[ ! "$SLUG" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$ ]]; then
    usage
    echo "Error: branch slug must be lowercase kebab-case using only a-z, 0-9, and hyphens." >&2
    exit 1
fi

if [ -d "$DEST/.git" ]; then
    echo "$DEST already exists — reusing" >&2
    configure_git_credentials
    configure_git_identity
    echo "Use gh-repo for GitHub CLI operations in this checkout." >&2
    echo "$DEST"
    exit 0
fi

mkdir -p "$(dirname "$DEST")"

if [ -d "$SRC/.git" ] || git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
    if ! git clone --quiet --shared "$SRC" "$DEST"; then
        echo "shared clone failed; retrying with regular clone" >&2
        rm -rf -- "$DEST"
        git clone --quiet "$SRC" "$DEST"
    fi

    # --shared clones set origin to the local path; fix it to the upstream URL
    # so that git push and gh pr create target the real GitHub remote.
    UPSTREAM_URL=$(git -C "$SRC" config --get remote.origin.url 2>/dev/null || echo "")
    if [ -n "$UPSTREAM_URL" ]; then
        git -C "$DEST" remote set-url origin "$UPSTREAM_URL"
    fi
else
    if [ -z "$(selected_github_token)" ]; then
        echo "Error: $SRC is not cached and $GITHUB_TOKEN_ENV is not configured" >&2
        exit 1
    fi
    UPSTREAM_URL="https://github.com/$REPO.git"
    # The destination does not exist yet, so its repository-local helper cannot
    # participate in this first clone. Override both gh token variables for the
    # inherited global helper, then install the durable local helper below.
    if ! GH_TOKEN="$(selected_github_token)" \
        GITHUB_TOKEN="$(selected_github_token)" \
        GIT_TERMINAL_PROMPT=0 git clone --quiet "$UPSTREAM_URL" "$DEST"; then
        rm -rf -- "$DEST"
        echo "Error: unable to clone $REPO with $GITHUB_TOKEN_ENV" >&2
        exit 1
    fi
fi

configure_git_credentials

BRANCH="centaur/$SLUG-$(date +%s)"
git -C "$DEST" checkout -q -b "$BRANCH"

configure_git_identity

echo "Use gh-repo for GitHub CLI operations in this checkout." >&2
echo "$DEST"
