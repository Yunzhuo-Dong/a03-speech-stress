#!/usr/bin/env bash
# Shared settings for all run.sh scripts.
# Machine-specific values go in src/config.local.sh (git-ignored; see config.local.sh.example). Override any value with an environment variable, e.g.
#   AUDIO_PROJECT=/path/to/project VENV=/path/to/venv bash src/a03_features/run.sh test
HERE_CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$HERE_CFG/config.local.sh" ]] && source "$HERE_CFG/config.local.sh"
: "${AUDIO_PROJECT:=$HOME/research_storage/from_gold/Audio_Analysis_Mannheim}"   # data + results root
: "${VENV:=$HOME/.venvs/audio_ml}"                                              # Python virtual environment
: "${RESEARCH_MOUNT:=}"            # optional: mount point that must be present (e.g. the research disk)
export AUDIO_PROJECT VENV RESEARCH_MOUNT

[[ -f "$VENV/bin/activate" ]] && source "$VENV/bin/activate" || echo "[warn] venv not found: $VENV (using current python)"
if [[ -n "$RESEARCH_MOUNT" ]] && ! mountpoint -q "$RESEARCH_MOUNT"; then
  echo "Research disk is not mounted: $RESEARCH_MOUNT"; exit 1
fi
[[ -d "$AUDIO_PROJECT" ]] || { echo "AUDIO_PROJECT not found: $AUDIO_PROJECT"; exit 1; }
export TMPDIR="${TMPDIR_OVERRIDE:-$AUDIO_PROJECT/.cache/tmp}"; mkdir -p "$TMPDIR" "$AUDIO_PROJECT/results"
