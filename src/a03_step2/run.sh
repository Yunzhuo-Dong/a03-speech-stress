#!/usr/bin/env bash
# A03 Step 2: (a) audEERING wav2vec2 emotion model, zero-shot; (b) positive controls + final contrasts.
#   bash run.sh            -> (a) if not done yet, then (b)
#   bash run.sh controls   -> only (b)
#   bash run.sh w2v2       -> only (a)
# If (a) fails (e.g. no internet for the model download), (b) still runs with handcrafted features only.
# Overrides: TRIALS_ROOT=...  SPSS=...  FORCE=1
set -uo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/config.sh"
export HF_HOME="$AUDIO_PROJECT/.cache/huggingface"
export TMPDIR="$AUDIO_PROJECT/.cache/tmp"
export MPLBACKEND=Agg
mkdir -p "$HF_HOME" "$TMPDIR"

HERE="$(cd "$(dirname "$0")" && pwd)"
FEATURES="$AUDIO_PROJECT/results/a03_features_v1/PRIVATE_features_long.csv"
W2V2_OUT="$AUDIO_PROJECT/results/a03_w2v2_emotion_v1"
OUT="$AUDIO_PROJECT/results/a03_positive_controls_v1"
MODE="${1:-all}"

if [[ -z "${TRIALS_ROOT:-}" ]]; then
  for c in "$AUDIO_PROJECT/data/raw/A03_FP1_VSA/A03 FP1 VSA for Michael and Dong/trials" \
           "$AUDIO_PROJECT/data/A03_FP1_VSA/A03 FP1 VSA for Michael and Dong/trials"; do
    [[ -d "$c" ]] && { TRIALS_ROOT="$c"; break; }
  done
fi
SPSS="${SPSS:-$AUDIO_PROJECT/data/private_a03_metadata/Gesamt_A03_aktuell_1 - Kopie (1).zip}"
if [[ ! -f "$SPSS" ]]; then
  SPSS="$(find "$AUDIO_PROJECT/data" -maxdepth 3 -type f \( -iname 'Gesamt_A03*.zip' -o -iname 'Gesamt_A03*.sav' \) 2>/dev/null | sort | head -n1 || true)"
fi
[[ -f "$FEATURES" ]] || { echo "missing $FEATURES (run Step 1a first)"; exit 1; }
[[ -n "$SPSS" && -f "$SPSS" ]] || { echo "SPSS file not found; set SPSS=..."; exit 1; }

python -c "import statsmodels, sklearn, joblib, pyreadstat, matplotlib" 2>/dev/null || {
  echo "installing missing analysis packages into audio_ml ..."
  pip install --upgrade-strategy only-if-needed statsmodels scikit-learn joblib pyreadstat matplotlib
}

# ---------- (a) wav2vec2 emotion model
if [[ "$MODE" == "all" || "$MODE" == "w2v2" ]]; then
  if [[ -f "$W2V2_OUT/PRIVATE_w2v2_long.csv" && "${FORCE:-0}" != "1" ]]; then
    echo "[w2v2] already done: $W2V2_OUT"
  elif [[ ! -d "${TRIALS_ROOT:-}" ]]; then
    echo "[w2v2] trials dir not found (set TRIALS_ROOT=...) -> skipped"
  else
    echo "[w2v2] running the audEERING model (first run downloads ~660 MB to $HF_HOME)"
    mkdir -p "$W2V2_OUT"
    python "$HERE/a03_w2v2_emotion.py" --root "$TRIALS_ROOT" --out "$W2V2_OUT" 2>&1 | tee "$W2V2_OUT/run.log" || true
    [[ -f "$W2V2_OUT/PRIVATE_w2v2_long.csv" ]] || echo "[w2v2] FAILED (see $W2V2_OUT/run.log) -> continuing with handcrafted features only"
  fi
fi

# ---------- (b) positive controls
if [[ "$MODE" == "all" || "$MODE" == "controls" ]]; then
  if [[ -e "$OUT/positive_controls_summary_PUBLIC.json" && "${FORCE:-0}" != "1" ]]; then
    echo "$OUT already has results; FORCE=1 to overwrite"; exit 1
  fi
  mkdir -p "$OUT"
  W2V2_ARG=(); [[ -f "$W2V2_OUT/PRIVATE_w2v2_long.csv" ]] && W2V2_ARG=(--w2v2-dir "$W2V2_OUT")
  python "$HERE/a03_positive_controls.py" --features "$FEATURES" --spss "$SPSS" "${W2V2_ARG[@]}" --out "$OUT" 2>&1 | tee "$OUT/run.log"
  echo
  echo "Send back (group-level only):"
  for f in positive_controls_report_PUBLIC.md positive_controls_summary_PUBLIC.json univariate_all_PUBLIC.csv \
           discrimination_auc_PUBLIC.png exercise_vs_stress_effects_PUBLIC.png; do echo "  $OUT/$f"; done
  [[ ${#W2V2_ARG[@]} -eq 0 ]] && echo "NOTE: wav2vec2 results are missing; also send the last lines of $W2V2_OUT/run.log"
fi
