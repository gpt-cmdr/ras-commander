#!/usr/bin/env bash
set -euo pipefail

# Run one exact stable HEC-RAS build's user-visible TCU session in a disposable
# Wine prefix. Windows Python calls RasAcceptanceState.run_user_driven_acceptance;
# this wrapper and the Python harness never click, type, or dismiss a dialog.

if [[ $# -ne 3 ]]; then
    echo "usage: $0 PREFIX VERSION RECEIPT" >&2
    echo "required environment: RAS_COMMANDER_TCU_SOURCE_EVIDENCE_SHA256," >&2
    echo "  RAS_COMMANDER_TCU_AUTHORIZATION_REFERENCE," >&2
    echo "  RAS_COMMANDER_TCU_PROFILE_INSTANCE_TOKEN," >&2
    echo "  RAS_COMMANDER_TCU_CONTROLLED_ROOT," >&2
    echo "  RAS_COMMANDER_TCU_SOURCE_ROOT," >&2
    echo "  RAS_COMMANDER_TCU_WINDOWS_SOURCE_ROOT," >&2
    echo "  RAS_COMMANDER_TCU_DISPLAY, RAS_COMMANDER_TCU_USER_VISIBLE=1" >&2
    exit 64
fi

prefix=$(readlink -f "$1")
version=$2
receipt=$(readlink -m "$3")
controlled_root_config=${RAS_COMMANDER_TCU_CONTROLLED_ROOT:-}
source_root_config=${RAS_COMMANDER_TCU_SOURCE_ROOT:-}
windows_source=${RAS_COMMANDER_TCU_WINDOWS_SOURCE_ROOT:-}

if [[ -z "$controlled_root_config" || -z "$source_root_config" ]]; then
    echo "RAS_COMMANDER_TCU_CONTROLLED_ROOT and RAS_COMMANDER_TCU_SOURCE_ROOT are required" >&2
    exit 64
fi
case "$windows_source" in
    [A-Za-z]:\\*) ;;
    *)
        echo "RAS_COMMANDER_TCU_WINDOWS_SOURCE_ROOT must be an absolute Windows path" >&2
        exit 64
        ;;
esac

controlled_root=$(readlink -f "$controlled_root_config")
source_root=$(readlink -f "$source_root_config")
session_root=$controlled_root/manual-user-acceptance

case "$version" in
    4.0|4.1.0|5.0.3|5.0.6|5.0.7|6.0|6.1|6.2|6.3|6.3.1|6.4.1|6.5|6.6|7.0|7.0.1) ;;
    *6.7*Beta*)
        echo "beta builds require a separate beta-authorized workflow" >&2
        exit 64
        ;;
    *)
        echo "version is not one of the 15 installed stable qualification builds" >&2
        exit 64
        ;;
esac

case "$prefix" in
    "$session_root"/*/prefix) ;;
    *)
        echo "prefix is outside the controlled user-acceptance session root" >&2
        exit 64
        ;;
esac
case "$receipt" in
    "$session_root"/receipts/*.json) ;;
    *)
        echo "receipt is outside the controlled user-acceptance receipt root" >&2
        exit 64
        ;;
esac

source_evidence_sha256=${RAS_COMMANDER_TCU_SOURCE_EVIDENCE_SHA256:-}
authorization_reference=${RAS_COMMANDER_TCU_AUTHORIZATION_REFERENCE:-}
profile_instance_token=${RAS_COMMANDER_TCU_PROFILE_INSTANCE_TOKEN:-}
display=${RAS_COMMANDER_TCU_DISPLAY:-}

if [[ ! "$source_evidence_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "RAS_COMMANDER_TCU_SOURCE_EVIDENCE_SHA256 must be lowercase SHA-256" >&2
    exit 64
fi
if [[ -z "$authorization_reference" ]]; then
    echo "RAS_COMMANDER_TCU_AUTHORIZATION_REFERENCE is required" >&2
    exit 64
fi
if [[ -z "$profile_instance_token" ]]; then
    echo "RAS_COMMANDER_TCU_PROFILE_INSTANCE_TOKEN is required" >&2
    exit 64
fi
if [[ -z "$display" || ${RAS_COMMANDER_TCU_USER_VISIBLE:-} != 1 ]]; then
    echo "a user-visible display and RAS_COMMANDER_TCU_USER_VISIBLE=1 are required" >&2
    exit 64
fi

test -d "$prefix/drive_c/Python311"
product_directory="$prefix/drive_c/Program Files (x86)/HEC/HEC-RAS/$version"
if [[ -f "$product_directory/Ras.exe" ]]; then
    windows_executable="C:\\Program Files (x86)\\HEC\\HEC-RAS\\$version\\Ras.exe"
elif [[ -f "$product_directory/ras.exe" ]]; then
    windows_executable="C:\\Program Files (x86)\\HEC\\HEC-RAS\\$version\\ras.exe"
else
    echo "exact-version Ras.exe is absent from the disposable prefix" >&2
    exit 66
fi
if [[ ! -f "$source_root/tests/qualification/run_user_acceptance_session.py" ]]; then
    echo "configured source root lacks the user-acceptance harness" >&2
    exit 66
fi

windows_harness="$windows_source\\tests\\qualification\\run_user_acceptance_session.py"
windows_output='C:\acceptance-output\user-driven-version.json'
host_output="$prefix/drive_c/acceptance-output/user-driven-version.json"

if [[ -e "$host_output" || -e "$receipt" ]]; then
    echo "refusing to overwrite a prior session receipt" >&2
    exit 73
fi

cleanup() {
    runuser -u rasq -- env \
        HOME=/home/rasq \
        WINEPREFIX="$prefix" \
        WINEDEBUG=-all \
        wineserver -k >/dev/null 2>&1 || true
}
trap cleanup EXIT

set +e
runuser -u rasq -- env \
    HOME=/home/rasq \
    USER=rasq \
    LOGNAME=rasq \
    WINEPREFIX="$prefix" \
    DISPLAY="$display" \
    WINEDEBUG=-all \
    PYTHONUTF8=1 \
    PYTHONPATH="$windows_source" \
    timeout --signal=TERM --kill-after=15s 1050s \
    wine 'C:\Python311\python.exe' "$windows_harness" \
        --ras-executable "$windows_executable" \
        --expected-version "$version" \
        --source-evidence-sha256 "$source_evidence_sha256" \
        --destination-is-disposable \
        --authorization-reference "$authorization_reference" \
        --profile-instance-token "$profile_instance_token" \
        --session-timeout-seconds 900 \
        --legal-observation-seconds 0.25 \
        --main-ready-seconds 2 \
        --restart-timeout-seconds 45 \
        --restart-ready-seconds 20 \
        --output "$windows_output"
status=$?
set -e

if [[ -f "$host_output" ]]; then
    install -D -o rasq -g rasq -m 0644 "$host_output" "$receipt"
    sha256sum "$receipt"
fi
exit "$status"
