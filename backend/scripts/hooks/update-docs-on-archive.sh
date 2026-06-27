#!/bin/bash
# Hook: Update docs on OpenSpec archive
# Triggered when: /opsx:archive completes
# Purpose: Keep CLAUDE.md, RUNBOOK.md, and module CLAUDE.md files in sync with archived changes

set -euo pipefail

CHANGE_NAME="$1"
ARCHIVE_DATE="${2:-$(date +%Y-%m-%d)}"
ARCHIVE_PATH="openspec/changes/archive/${ARCHIVE_DATE}-${CHANGE_NAME}"

if [ ! -d "$ARCHIVE_PATH" ]; then
    echo "[doc-update] Archive not found: $ARCHIVE_PATH"
    exit 0
fi

echo "[doc-update] Scanning archived change: $CHANGE_NAME"

# Check if this change modified specs that affect core documentation
if [ -d "$ARCHIVE_PATH/specs" ]; then
    SPEC_DIRS=$(find "$ARCHIVE_PATH/specs" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null || true)

    for spec_dir in $SPEC_DIRS; do
        case "$spec_dir" in
            backtest)
                echo "[doc-update] Backtest spec changed — reviewing src/pdp/backtest/CLAUDE.md"
                # Verify module CLAUDE exists; backtest changes often affect it
                if [ ! -f "src/pdp/backtest/CLAUDE.md" ]; then
                    echo "[doc-update] WARNING: src/pdp/backtest/CLAUDE.md not found for backtest change"
                fi
                ;;
            supertrend-strategy)
                echo "[doc-update] Strategy spec changed — reviewing docs/supertrend_short_strategy.md"
                if [ ! -f "docs/supertrend_short_strategy.md" ]; then
                    echo "[doc-update] WARNING: docs/supertrend_short_strategy.md not found for strategy change"
                fi
                ;;
            *)
                echo "[doc-update] Spec dir: $spec_dir (no auto-update rules; manual review may be needed)"
                ;;
        esac
    done
fi

# Check if proposal mentions specific docs that need updating
if [ -f "$ARCHIVE_PATH/proposal.md" ]; then
    if grep -q "CLAUDE.md\|RUNBOOK.md\|docs/" "$ARCHIVE_PATH/proposal.md"; then
        echo "[doc-update] Proposal mentions docs — review may be needed:"
        grep "CLAUDE.md\|RUNBOOK.md\|docs/" "$ARCHIVE_PATH/proposal.md" | head -5
    fi
fi

echo "[doc-update] Archive $CHANGE_NAME reviewed. Manual doc updates (if needed) are flagged above."
exit 0
