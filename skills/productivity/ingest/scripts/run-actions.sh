#!/usr/bin/env bash
# Compatibility shim: the launcher lives in the chief-of-staff skill. Forward everything there.
exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../chief-of-staff/scripts" && pwd)/run-actions.sh" "$@"
