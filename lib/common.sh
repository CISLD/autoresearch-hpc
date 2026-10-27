#!/usr/bin/env bash
# AutoResearch HPC — shared shell library. Sourced by bin/arh-* commands.
set -euo pipefail

ARH_HOME="${ARH_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export ARH_HOME

arh_die()  { printf 'arh: %s\n' "$*" >&2; exit 1; }
arh_warn() { printf 'arh: %s\n' "$*" >&2; }
arh_info() { printf '  %s\n' "$*"; }
arh_ok()   { printf '  OK   %s\n' "$*"; }
arh_fail() { printf '  FAIL %s\n' "$*"; }

# Config files are Markdown. Machine-readable settings live only in
# fenced `arh-config` blocks as `key = value`.
arh_config_get() {
  local file="$1" key="$2" default="${3-}" val
  [ -f "$file" ] || { printf '%s' "$default"; return 0; }
  val=$(awk -v key="$key" '
    /^[ \t]*```[ \t]*arh-config[ \t]*$/ { inb=1; next }
    /^[ \t]*```/    { inb=0; next }
    !inb   { next }
    /^[ \t]*#/       { next }
    {
      n = index($0, "=")
      if (n == 0) next
      k = substr($0, 1, n-1); v = substr($0, n+1)
      gsub(/^[ \t]+|[ \t]+$/, "", k)
      gsub(/^[ \t]+|[ \t]+$/, "", v)
      if (k == key) { print v; exit }
    }' "$file")
  [ -n "$val" ] && printf '%s' "$val" || printf '%s' "$default"
}

arh_config_keys() {
  awk '
    /^[ \t]*```[ \t]*arh-config[ \t]*$/ { inb=1; next }
    /^[ \t]*```/    { inb=0; next }
    !inb || /^[ \t]*#/        { next }
    { n=index($0,"="); if(n){ k=substr($0,1,n-1); gsub(/^[ \t]+|[ \t]+$/,"",k); print k } }' "$1"
}

arh_find_project() {
  local d="${ARH_PROJECT:-$PWD}"
  d=$(cd "$d" 2>/dev/null && pwd) || arh_die "cannot resolve $d"
  while [ "$d" != "/" ]; do
    [ -d "$d/.arh" ] && { printf '%s' "$d"; return 0; }
    d=$(dirname "$d")
  done
  arh_die "not inside an AutoResearch HPC project (no .arh/ found from ${ARH_PROJECT:-$PWD}).
       Run: arh init <dir>, or export ARH_PROJECT=<study> to work from any directory"
}

arh_load_project() {
  ARH_ROOT=$(arh_find_project)
  ARH_STATE="$ARH_ROOT/.arh"
  ARH_CONF="$ARH_STATE/config"
  ARH_SITE="$ARH_CONF/site.md"
  ARH_PROJ="$ARH_CONF/project.md"
  ARH_HARN="$ARH_CONF/harnesses.md"
  ARH_GENS="$ARH_CONF/generators.md"
  ARH_ITERS="$ARH_ROOT/$(arh_config_get "$ARH_PROJ" iterations_dir iterations)"
  ARH_VERIFY="$ARH_ROOT/$(arh_config_get "$ARH_PROJ" verification_dir verification)"
  ARH_LEDGER="$ARH_ROOT/$(arh_config_get "$ARH_PROJ" ledger PROGRESS.md)"
  ARH_REGISTRY="$ARH_STATE/registry.tsv"
  # The operator's directives file; a study that kept them in VALIDATION_PROTOCOL.md names it (#47).
  ARH_DIRECTIVES="$ARH_ROOT/$(arh_config_get "$ARH_PROJ" directives DIRECTIVES.md)"
  # Which environment variables carry the harness's own session id (harnesses.md session_env).
  ARH_SESSION_ENV=$(arh_config_get "$ARH_HARN" session_env "")
  # auto: gitleaks's maintained rules on top of the built-in patterns when gitleaks is installed.
  ARH_SECRET_SCANNER=$(arh_config_get "$ARH_HARN" secret_scanner auto)
  export ARH_ROOT ARH_STATE ARH_CONF ARH_SITE ARH_PROJ ARH_HARN ARH_GENS ARH_ITERS ARH_VERIFY ARH_LEDGER ARH_REGISTRY ARH_DIRECTIVES \
    ARH_SESSION_ENV ARH_SECRET_SCANNER
}

# mktemp makes files 0600 and directories 0700. Anything arh keeps in the project gets the mode the
# umask gives other files (a directory keeps its setgid bit), or a project shared between accounts
# through a group hides its records from the other account (field feedback #88).
arh_share_mode() {
  local p m
  m=$(umask)
  for p in "$@"; do
    if [ -d "$p" ]; then chmod "$(printf '%o' $(( 0777 & ~m )))" "$p"
    elif [ -e "$p" ]; then chmod "$(printf '%o' $(( 0666 & ~m )))" "$p"; fi
  done
}

arh_now()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
arh_today() { date -u +%Y-%m-%d; }

arh_abspath() {
  if readlink -m / >/dev/null 2>&1; then
    readlink -m -- "$1"
  else
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
  fi
}

arh_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else arh_die "no sha256sum or shasum available"; fi
}

arh_agent() {
  printf '%s' "${ARH_AGENT:-${CLAUDECODE:+claude}}" 2>/dev/null || true
  :
}

arh_agent_name() {
  if [ -n "${ARH_AGENT:-}" ]; then printf '%s' "$ARH_AGENT"
  elif [ -n "${CLAUDECODE:-}" ]; then printf 'claude'
  elif [ -n "${CODEX_SANDBOX:-}${CODEX_HOME:-}" ]; then printf 'codex'
  elif [ -n "${OPENCODE:-}" ]; then printf 'opencode'
  else printf '%s' "${USER:-unknown}"; fi
}

# What decided arh_agent_name. Harness markers are inherited by child processes, so a
# Codex session started from inside Claude Code still carries CLAUDECODE; claims record
# the source so a wrong inference is visible in the record.
arh_agent_source() {
  if [ -n "${ARH_AGENT:-}" ]; then printf 'ARH_AGENT'
  elif [ -n "${CLAUDECODE:-}" ]; then printf 'CLAUDECODE'
  elif [ -n "${CODEX_SANDBOX:-}${CODEX_HOME:-}" ]; then printf 'CODEX_SANDBOX/CODEX_HOME'
  elif [ -n "${OPENCODE:-}" ]; then printf 'OPENCODE'
  else printf 'USER'; fi
}

# Warn when the session's idea of the agent differs from the configured producer.
# ARH_AGENT is deliberately NOT exempt: the agent contract tells a session to set it to
# its own harness name ("claude", "codex", ...), which silently discards the model and
# account a lane pinned into the producer name. That override is exactly what needs
# reporting, so only a plain USER fallback (a human at a shell) is exempt.
arh_warn_agent_mismatch() {
  local name source producer
  name=$(arh_agent_name); source=$(arh_agent_source)
  producer=$(arh_config_get "$ARH_HARN" producer "")
  case "$source" in USER) return 0 ;; esac
  [ -n "$producer" ] && [ "$name" != "$producer" ] || return 0
  arh_warn "agent '$name' came from $source, but the configured producer is '$producer'."
  arh_warn "the configured producer is authoritative; pass 'arh claim -a NAME' to record a different agent"
}

arh_guard_path() {
  local p abs immutable ip
  immutable="$(arh_config_get "$ARH_PROJ" immutable_inputs "") $(! arh_has_sealed || python3 "$ARH_HOME/lib/freeze.py" sealed "$ARH_ROOT" | tr '\n' ' ')"
  for p in "$@"; do
    abs=$(arh_abspath "$p")
    case "$abs" in "$ARH_ROOT"/*) ;; *) arh_die "refusing write outside project root: $abs" ;; esac
    for ip in $immutable; do
      [ -n "$ip" ] || continue
      case "$ip" in /*) ;; *) ip="$ARH_ROOT/$ip" ;; esac
      ip=$(arh_abspath "$ip")
      case "$abs" in "$ip"/*|"$ip") arh_die "immutable input path: $abs" ;; esac
    done
  done
}

arh_crosschecks() {
  python3 "$ARH_HOME/lib/harness.py" valid "$1" | sed '/^$/d'
}

# The frozen pre-declaration fixes the science; the review terms (verifier, fallbacks, family rule,
# bounds) live in harnesses.md, which a producing agent could once edit without a trace (2026-09-16).
# arh claim now binds them to the iteration. Prints changed, unchanged, or unrecorded for claims
# older than the hash.
arh_harness_config_state() {
  local claimed
  claimed=$(sed -n 's/.*"harness_config_sha256"[ ]*:[ ]*"\([0-9a-f]\{64\}\)".*/\1/p' "$1/CLAIM.json" 2>/dev/null | head -1)
  if [ -z "$claimed" ]; then echo unrecorded
  elif [ "$claimed" = "$(arh_sha256 "$ARH_HARN" 2>/dev/null)" ]; then echo unchanged
  else echo changed; fi
}

# The value of a review-policy key (require_crosscheck, review_response, unsound_review) that iteration
# DIR is judged by: the one recorded when it was claimed, else project.md's (claims older than the
# record). A later edit of project.md is named on stderr and does not apply.
arh_review_policy() {
  local dir="$1" key="$2" default="$3" current claimed
  current=$(arh_config_get "$ARH_PROJ" "$key" "$default")
  claimed=$(python3 -c 'import json, sys
try:
    print(json.load(open(sys.argv[1])).get("review_policy", {}).get(sys.argv[2], ""))
except (OSError, ValueError, AttributeError):
    print("")' "$dir/CLAIM.json" "$key")
  if [ -n "$claimed" ]; then
    [ "$claimed" = "$current" ] || printf '  NOTE %s = %s in project.md, but %s when iteration %s was claimed: the claimed value applies\n' \
      "$key" "$current" "$claimed" "${dir##*iteration}" >&2
    printf '%s\n' "$claimed"
  else
    printf '%s\n' "$current"
  fi
}

# Build an environment prefix once: arh_build_once PREFIX COMMAND... A prefix is complete when it
# holds .arh-complete. Concurrent builders wait on PREFIX.building; a build left behind by a dead
# process on this host is removed and redone. COMMAND runs where `set -e` does not apply, so it must
# return non-zero itself when a step fails.
arh_build_once() {
  local prefix="$1" lock="$1.building" waited=0 host pid; shift
  mkdir -p "$(dirname "$prefix")"
  until mkdir "$lock" 2>/dev/null; do
    [ -f "$prefix/.arh-complete" ] && return 0
    host=""; pid=""
    read -r host pid 2>/dev/null < "$lock/owner" || true
    if [ "$host" = "$(uname -n)" ] && [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      mv "$lock" "$lock.stale.$$" 2>/dev/null && rm -rf "$lock.stale.$$"
      continue
    fi
    [ $((waited % 300)) -ne 0 ] || arh_warn "waiting for another setup to finish building $prefix"
    sleep 5; waited=$((waited + 5))
  done
  printf '%s %s\n' "$(uname -n)" "$$" > "$lock/owner"
  if [ ! -f "$prefix/.arh-complete" ]; then
    rm -rf "$prefix"
    if ! "$@"; then rm -rf "$prefix" "$lock"; return 1; fi
    touch "$prefix/.arh-complete"
  fi
  rm -rf "$lock"
}

# SOURCE:TARGET binds that cover every existing sealed input with an empty mount. `arh run` has no
# iteration and so no freeze: it never reads a sealed input, even one inside a broader immutable input.
arh_sealed_masks() {
  arh_has_sealed || return 0
  python3 "$ARH_HOME/lib/freeze.py" masks "$ARH_ROOT"
}

# Any sealed group declared: sealed_inputs, sealed_inputs_<group>, or either with _file.
arh_has_sealed() {
  [ -f "$ARH_PROJ" ] && arh_config_keys "$ARH_PROJ" | while read -r k; do
    case "$k" in sealed_inputs|sealed_inputs_*) [ -n "$(arh_config_get "$ARH_PROJ" "$k" "")" ] && echo y ;; esac
  done | grep -q y
}

# arh_secret_scan NOTE FILE...: succeed unless the files, or the note text, carry something shaped like
# a credential; the findings go to stderr, redacted. Run on what arh ask, arh delegate and arh evoke
# are about to send to an outside model service. `secret_scan = off` in harnesses.md disables it.
arh_secret_scan() {
  local note="$1" tmp="" rc=0 hits; shift
  [ "$(arh_config_get "$ARH_HARN" secret_scan on)" != off ] || return 0
  if [ -n "$note" ]; then tmp=$(mktemp); printf '%s\n' "$note" > "$tmp"; set -- "$@" "$tmp"; fi
  hits=$(python3 "$ARH_HOME/lib/secret_scan.py" scan "$@") || rc=$?
  [ "$rc" != 2 ] || { [ -z "$tmp" ] || rm -f "$tmp"; arh_die "the secret scanner could not run (above); nothing was sent"; }
  [ "$rc" = 0 ] || printf '%s\n' "${hits//"$tmp"/--note}" >&2
  [ -z "$tmp" ] || rm -f "$tmp"
  return "$rc"
}

# arh_owner_dir N|OBJECT: the iteration directory for a number, or the verification directory for a
# verification object's name. note, lease and wait worked on iterations only, so a verification could
# record no out-of-band work, no takeover and no wait (field feedback #56, #59, #67).
arh_owner_dir() {
  case "$1" in
    "") return 1 ;;
    *[!0-9]*) [ -f "$ARH_VERIFY/$1/PREDECLARATION.md" ] && case "$1" in */*|..*) return 1 ;; *) printf '%s' "$ARH_VERIFY/$1" ;; esac ;;
    *) printf '%s' "$ARH_ITERS/iteration$1" ;;
  esac
}

# arh_lease_touch DIR COMMAND: record that COMMAND acted on the iteration in DIR, warning when another
# session holds it. Never fails the command that calls it.
arh_lease_touch() {
  [ -f "$1/CLAIM.json" ] || [ -f "$1/PREDECLARATION.md" ] || return 0
  local rc=0
  python3 "$ARH_HOME/lib/lease.py" touch "$1" "$2" "$(arh_agent_name)" "${USER:-unknown}" "$(uname -n)" \
    "${ARH_SESSION:-}" || rc=$?
  # 3: a dispatched controller holds the iteration (lease.py said so); any other failure only warns.
  [ "$rc" -ne 3 ] || exit 3
}
