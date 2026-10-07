#!/usr/bin/env bash
# Run bundled actions.py commands, initializing once per invocation/batch.
set -euo pipefail

if [[ $# -eq 0 ]]; then
  printf '%s\n' 'Supply SERVICE COMMAND [arguments], or --batch with action commands on standard input.' >&2
  exit 2
fi
COS_ACTION_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Hermes home: HERMES_HOME, else the home this script is installed in (works for cron and CLI
# runs that do not export HERMES_HOME), else the root install.
COS_ACTION_HOME=""
for candidate in "${HERMES_HOME:-}" "$COS_ACTION_DIR/../../../.." "${LOCALAPPDATA:-}/hermes" "$HOME/.hermes"; do
  [[ -n "$candidate" && -d "$candidate/hermes-agent" ]] || continue
  COS_ACTION_HOME="$(cd -- "$candidate" && pwd)"; break
done
: "${COS_ACTION_HOME:=${HERMES_HOME:-$HOME/.hermes}}"
# actions.py resolves credentials from HERMES_HOME; keep it on the same home as the launcher,
# as a Windows path under Git Bash so Python does not see /c/Users/... .
case "$(uname -s)" in
  MINGW*|MSYS*) COS_ACTION_HOME="$(cygpath -m "$COS_ACTION_HOME")" ;;
esac
export HERMES_HOME="$COS_ACTION_HOME"
if [[ -f "$COS_ACTION_HOME/hermes-agent/venv/Scripts/python.exe" ]]; then
  COS_ACTION_PYTHON="$COS_ACTION_HOME/hermes-agent/venv/Scripts/python.exe"
elif [[ -x "$COS_ACTION_HOME/hermes-agent/venv/bin/python" ]]; then
  COS_ACTION_PYTHON="$COS_ACTION_HOME/hermes-agent/venv/bin/python"
else
  COS_ACTION_PYTHON="$(command -v python3 || command -v python)"
fi
COS_ACTION_SCRIPT="$COS_ACTION_DIR/../../ingest/scripts/actions.py"
if [[ ! -f "$COS_ACTION_SCRIPT" ]]; then
  printf '%s\n' "Bundled actions.py is missing: $COS_ACTION_SCRIPT" >&2
  exit 2
fi
case "$(uname -s)" in
  MINGW*|MSYS*) COS_ACTION_SCRIPT="$(cygpath -m "$COS_ACTION_SCRIPT")" ;;
esac
# Preserve literal Google queries, ranges, and URLs under Git Bash on Windows.
export MSYS2_ARG_CONV_EXCL='*' MSYS_NO_PATHCONV=1
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1

action() {
  if [[ $# -eq 0 ]]; then
    printf '%s\n' 'action needs SERVICE COMMAND [arguments].' >&2
    exit 2
  fi
  "$COS_ACTION_PYTHON" -X utf8 -B "$COS_ACTION_SCRIPT" "$@" || exit "$?"
}
if [[ "$1" == '--batch' ]]; then
  if [[ $# -ne 1 ]]; then
    printf '%s\n' '--batch takes its command block from standard input, not extra arguments.' >&2
    exit 2
  fi
  # Read the complete caller-authored shell block first so helpers cannot
  # accidentally consume subsequent commands as their input.
  COS_ACTION_BATCH="$(cat)"
  if [[ -z "${COS_ACTION_BATCH//[[:space:]]/}" ]]; then
    printf '%s\n' 'The batch needs action commands.' >&2
    exit 2
  fi
  export COS_ACTION_PYTHON COS_ACTION_SCRIPT
  export -f action
  "$BASH" -euo pipefail -c "$COS_ACTION_BATCH"
else
  exec "$COS_ACTION_PYTHON" -X utf8 -B "$COS_ACTION_SCRIPT" "$@"
fi
