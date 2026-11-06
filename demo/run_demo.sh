#!/usr/bin/env bash
# End-to-end demo of the legacy -> refgenie 1.0 upgrade path.
#
#   1. install legacy refgenie (0.x) and pull a few small assets from the
#      legacy server (refgenomes.databio.org)
#   2. install refgenie 1.0 + refgenie-upgrade and migrate that folder
#   3. use the migrated instance against the new server (api.refgenie.org)
#
# Usage: bash demo/run_demo.sh [WORKDIR]
# See demo/README.md for the knobs (LEGACY_SPEC, REFGENIE_SPEC, ...).

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:-$(mktemp -d -t refgenie-upgrade-demo.XXXXXX)}"
WORK="$(mkdir -p "$WORK" && cd "$WORK" && pwd)"

LEGACY_SPEC="${LEGACY_SPEC:-refgenie<1}"
REFGENIE_SPEC="${REFGENIE_SPEC:-refgenie>=1.0.0a1}"
UPGRADE_SPEC="${UPGRADE_SPEC:-$(cd "$HERE/.." && pwd)}"
SERVER="${SERVER:-https://api.refgenie.org}"
PYTHON="${PYTHON:-3.11}"
UPGRADE_MODE="${UPGRADE_MODE:---symlink}"

# Small genomes, so the whole demo downloads well under 20 MB.
GENOMES=(rCRSd mouse_chrM2x)
LEGACY_ASSETS=(rCRSd/fasta rCRSd/bowtie2_index mouse_chrM2x/fasta)
# Assets pulled from the new server onto the migrated genomes. Each needs the
# migrated fasta as its parent, so this only works if the migrated fasta is
# recognized as the same asset the server has.
NEW_ASSETS=(rCRSd/fasta_index mouse_chrM2x/bowtie2_index)

LOGS="$WORK/logs"
mkdir -p "$LOGS"
PASSED=0
FAILED=0

# Keep the user's own refgenie setup out of this.
unset REFGENIE REFGENIE_HOME_PATH REFGENIE_DB_CONFIG_PATH REFGENIE_GENOME_FOLDER \
      REFGENIE_GENOME_STAGE_FOLDER

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# run LOGNAME CMD...: run a setup step, stop the demo if it fails.
run() {
    local log="$LOGS/$1.log"; shift
    if ! "$@" >"$log" 2>&1; then
        echo "FAILED: $*"; tail -20 "$log"; echo "(full log: $log)"
        exit 1
    fi
}

# check DESCRIPTION CMD...: run one test, record pass or fail, keep going.
check() {
    local desc="$1"; shift
    local log="$LOGS/check_$((PASSED + FAILED + 1)).log"
    if "$@" >"$log" 2>&1; then
        printf '  \033[32mPASS\033[0m  %s\n' "$desc"; PASSED=$((PASSED + 1))
    else
        printf '  \033[31mFAIL\033[0m  %s\n' "$desc"; FAILED=$((FAILED + 1))
        grep -E "ERROR|Error|error|FAIL|mismatch" "$log" | tail -3 | sed 's/^/          /'
        echo "          (log: $log)"
    fi
}

for tool in uv curl; do
    command -v "$tool" >/dev/null || { echo "Needs '$tool' on PATH"; exit 1; }
done

echo "Work folder: $WORK"
echo "Legacy refgenie:  $LEGACY_SPEC"
echo "refgenie 1.0:     $REFGENIE_SPEC"
echo "refgenie-upgrade: $UPGRADE_SPEC"
echo "New server:       $SERVER"

# ---------------------------------------------------------------------------
say "1. Legacy refgenie: install and pull ${LEGACY_ASSETS[*]}"
CFG="$WORK/legacy/genome_config.yaml"
OLD="$WORK/legacy-env/bin/refgenie"
mkdir -p "$WORK/legacy"
run legacy_install uv venv -q -p "$PYTHON" "$WORK/legacy-env"
run legacy_install_pkgs uv pip install -q -p "$WORK/legacy-env/bin/python" "$LEGACY_SPEC"
echo "  $("$OLD" --version)"
run legacy_init "$OLD" init -c "$CFG"
run legacy_pull "$OLD" pull -c "$CFG" "${LEGACY_ASSETS[@]}"
"$OLD" list -c "$CFG" 2>/dev/null | sed 's/^/  /'

# ---------------------------------------------------------------------------
say "2. Install refgenie 1.0 + refgenie-upgrade, migrate the legacy folder"
NEW="$WORK/new-env/bin/refgenie"
PY="$WORK/new-env/bin/python"
run new_install uv venv -q -p "$PYTHON" "$WORK/new-env"
run new_install_pkgs uv pip install -q -p "$PY" "$REFGENIE_SPEC" "$UPGRADE_SPEC"
echo "  refgenie $("$PY" -c 'import refgenie; print(refgenie.__version__)')"
run upgrade "$WORK/new-env/bin/refgenie-upgrade" "$CFG" \
    --target-dir "$WORK/new" "$UPGRADE_MODE"
grep -E "Summary|skipped|Errors" "$LOGS/upgrade.log" | sed 's/^/  /'

export REFGENIE_HOME_PATH="$WORK/new"
run subscribe "$NEW" subscribe --reset -s "$SERVER"

# ---------------------------------------------------------------------------
say "3. Use the migrated instance against $SERVER"

# Digest of the server's default asset in a group, e.g. rCRSd's fasta.
server_asset_digest() {
    curl -sf "$SERVER/v4/assets?genome_digest=$1&asset_group_name=$2" | "$PY" -c '
import json, sys
rows = json.load(sys.stdin)["results"]
print(next((r["digest"] for r in rows if r.get("is_default")), ""))'
}

# seek returns a file for fasta, but an index prefix (".../rCRSd") for aligner
# indexes, so accept either the path itself or files that start with it.
seek_exists() {
    local p; p="$("$NEW" seek "$1")" && echo "$p" || return 1
    test -e "$p" || compgen -G "$p.*" >/dev/null
}

genome_known_by_server() {
    local d; d="$("$NEW" id "$1")" || return 1
    echo "local digest: $d"
    curl -sf -o /dev/null "$SERVER/v4/genomes/$d"
}

# A migrated fasta holds the same bytes the server's fasta does, so the two
# should be one content-addressed asset with one digest. (Indexes are not
# compared: the server's were rebuilt with newer aligner versions.)
fasta_matches_server() {
    local g="$1" d local_d server_d
    d="$("$NEW" id "$g")" || return 1
    local_d="$("$NEW" id "$g/fasta")" || return 1
    server_d="$(server_asset_digest "$d" fasta)"
    echo "local:  $local_d"
    echo "server: $server_d"
    [ -n "$server_d" ] && [ "$local_d" = "$server_d" ] || { echo "digest mismatch"; return 1; }
}

pull_and_seek() { "$NEW" pull "$1" && seek_exists "$1"; }

for a in "${LEGACY_ASSETS[@]}"; do
    check "seek $a (migrated, local)" seek_exists "$a"
done
check "listr against $SERVER" "$NEW" listr
for g in "${GENOMES[@]}"; do
    check "$g: server knows the migrated genome digest" genome_known_by_server "$g"
done
for g in "${GENOMES[@]}"; do
    check "$g: migrated fasta has the server's digest" fasta_matches_server "$g"
done
for a in "${NEW_ASSETS[@]}"; do
    check "pull $a from $SERVER onto the migrated genome" pull_and_seek "$a"
done

# ---------------------------------------------------------------------------
say "Result: $PASSED passed, $FAILED failed"
echo "Work folder (delete when done): $WORK"
[ "$FAILED" -eq 0 ]
