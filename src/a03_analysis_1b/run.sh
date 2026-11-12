#!/usr/bin/env bash
# A03 Step 1b: group analysis of vocal change (H1, H2a, H2b, H3, sensitivity, exploratory).
# Runs in about a minute; no tmux needed.  Overrides: SPSS=...  FORCE=1
set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/config.sh"
export TMPDIR="$AUDIO_PROJECT/.cache/tmp"; mkdir -p "$TMPDIR"
export MPLBACKEND=Agg

HERE="$(cd "$(dirname "$0")" && pwd)"
FEATURES="$AUDIO_PROJECT/results/a03_features_v1/PRIVATE_features_long.csv"
AUDIT="$AUDIO_PROJECT/results/a03_protocol_audit_v2"
OUT="$AUDIO_PROJECT/results/a03_analysis_1b_v1"

SPSS="${SPSS:-$AUDIO_PROJECT/data/private_a03_metadata/Gesamt_A03_aktuell_1 - Kopie (1).zip}"
if [[ ! -f "$SPSS" ]]; then
  SPSS="$(find "$AUDIO_PROJECT/data" -maxdepth 3 -type f \( -iname 'Gesamt_A03*.zip' -o -iname 'Gesamt_A03*.sav' \) 2>/dev/null | sort | head -n1 || true)"
fi
[[ -f "$FEATURES" ]] || { echo "missing $FEATURES (run Step 1a first)"; exit 1; }
[[ -n "$SPSS" && -f "$SPSS" ]] || { echo "SPSS file not found; set SPSS=..."; exit 1; }
[[ -d "$AUDIT" ]] || { echo "[warn] $AUDIT not found: flag/timing sensitivity analyses will be skipped"; AUDIT=""; }
if [[ -e "$OUT/analysis_1b_summary_PUBLIC.json" && "${FORCE:-0}" != "1" ]]; then
  echo "$OUT already has results; FORCE=1 to overwrite"; exit 1
fi

# statsmodels is the only new dependency; pip installs it without upgrading existing packages
python -c "import statsmodels, pyreadstat, matplotlib" 2>/dev/null || {
  echo "installing missing packages (statsmodels / pyreadstat / matplotlib) into audio_ml ..."
  pip install --upgrade-strategy only-if-needed statsmodels pyreadstat matplotlib
}

echo "features: $FEATURES"; echo "spss:     $SPSS"; echo "audit:    ${AUDIT:-<none>}"; echo "out:      $OUT"
mkdir -p "$OUT"
AUDIT_ARG=(); [[ -n "$AUDIT" ]] && AUDIT_ARG=(--audit-dir "$AUDIT")
python "$HERE/a03_analysis_1b.py" --features "$FEATURES" --spss "$SPSS" \
  "${AUDIT_ARG[@]}" --out "$OUT" 2>&1 | tee "$OUT/run.log"

echo
echo "Send back:"
echo "  $OUT/analysis_1b_report_PUBLIC.md"
echo "  $OUT/analysis_1b_summary_PUBLIC.json"
echo "  $OUT/exploratory_all_features_PUBLIC.csv"
echo "  $OUT/trajectories_PUBLIC.png"
