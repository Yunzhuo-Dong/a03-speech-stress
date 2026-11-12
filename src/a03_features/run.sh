#!/usr/bin/env bash
# A03 Step 1a: blind acoustic feature extraction.
#   bash run.sh test     -> 3 participants, foreground (speed + sanity check, ~1-2 min)
#   bash run.sh start    -> all participants in tmux session 'a03feat'
#   bash run.sh status   -> last lines of the running job
# Overrides: TRIALS_ROOT=...  WORKERS=16  FORCE=1
set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/config.sh"
export TMPDIR="$AUDIO_PROJECT/.cache/tmp"; mkdir -p "$TMPDIR" "$AUDIO_PROJECT/results"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1   # one core per worker

if [[ -z "${TRIALS_ROOT:-}" ]]; then
  for c in "$AUDIO_PROJECT/data/raw/A03_FP1_VSA/A03 FP1 VSA for Michael and Dong/trials" \
           "$AUDIO_PROJECT/data/A03_FP1_VSA/A03 FP1 VSA for Michael and Dong/trials"; do
    [[ -d "$c" ]] && { TRIALS_ROOT="$c"; break; }
  done
fi
[[ -d "${TRIALS_ROOT:-}" ]] || { echo "trials dir not found; set TRIALS_ROOT=..."; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$AUDIO_PROJECT/results/a03_features_v1"
WORKERS="${WORKERS:-16}"
CMD=${1:-help}

python - <<'EOF'
import importlib
for m in ("parselmouth", "opensmile", "soundfile", "scipy", "pandas"):
    try: importlib.import_module(m); print(f"  ok  {m}")
    except ImportError: print(f"  MISSING {m}  ->  pip install " + {"parselmouth": "praat-parselmouth"}.get(m, m))
EOF

case "$CMD" in
  test)
    python "$HERE/a03_features.py" --root "$TRIALS_ROOT" --out "$OUT/_test" --workers 3 --limit 3
    echo "test output: $OUT/_test  (check runtime and features_qc_PUBLIC.md, then: bash run.sh start)";;
  start)
    if [[ -e "$OUT/features_qc_PUBLIC.json" && "${FORCE:-0}" != "1" ]]; then
      echo "$OUT already has results; FORCE=1 to overwrite"; exit 1; fi
    mkdir -p "$OUT"
    tmux new-session -d -s a03feat \
      "source '$VENV/bin/activate'; export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TMPDIR='$TMPDIR'; \
       python '$HERE/a03_features.py' --root '$TRIALS_ROOT' --out '$OUT' --workers $WORKERS 2>&1 | tee '$OUT/run.log'; \
       echo FINISHED; sleep 86400"
    echo "started in tmux session 'a03feat' (bash run.sh status)";;
  status)
    tmux capture-pane -pt a03feat -S -20 2>/dev/null || tail -n 20 "$OUT/run.log";;
  *)
    echo "usage: bash run.sh test | start | status";;
esac
