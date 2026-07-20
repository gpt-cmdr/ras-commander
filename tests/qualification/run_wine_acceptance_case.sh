#!/usr/bin/env bash
set -euo pipefail

# Retained only as a fail-closed compatibility tombstone. The former script
# launched hard-coded candidate/provision diagnostics; it is not an approved
# acceptance workflow.

echo "run_wine_acceptance_case.sh is retired" >&2
echo "use run_wine_acceptance_version.sh for an exact-version, user-visible TCU session" >&2
exit 64
