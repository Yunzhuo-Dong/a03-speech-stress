#!/usr/bin/env bash
# A03 Step 0 audit (v2): protocols + wav files + SPSS. Read-only on data.
# Usage:  bash run.sh            (normal)
#         TRIALS_ROOT=... SPSS=... bash run.sh   (override paths)
#         FORCE=1 bash run.sh    (overwrite an existing output folder)
set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/config.sh"
export TMPDIR="$AUDIO_PROJECT/.cache/tmp"; mkdir -p "$TMPDIR"
mkdir -p "$AUDIO_PROJECT/results"


# trials root: first existing candidate unless TRIALS_ROOT is set
if [[ -z "${TRIALS_ROOT:-}" ]]; then
  for c in \
    "$AUDIO_PROJECT/data/raw/A03_FP1_VSA/A03 FP1 VSA for Michael and Dong/trials" \
    "$AUDIO_PROJECT/data/A03_FP1_VSA/A03 FP1 VSA for Michael and Dong/trials"; do
    [[ -d "$c" ]] && { TRIALS_ROOT="$c"; break; }
  done
fi
[[ -d "${TRIALS_ROOT:-}" ]] || { echo "trials dir not found; set TRIALS_ROOT=..."; exit 1; }

SPSS="${SPSS:-$AUDIO_PROJECT/data/private_a03_metadata/Gesamt_A03_aktuell_1 - Kopie (1).zip}"
if [[ ! -f "$SPSS" ]]; then
  # fall back to any .sav / .zip in the metadata folder
  SPSS="$(find "$AUDIO_PROJECT/data" -maxdepth 3 -type f \( -iname 'Gesamt_A03*.zip' -o -iname 'Gesamt_A03*.sav' \) 2>/dev/null | sort | head -n1 || true)"
fi
AUDIO_SUBDIR="${AUDIO_SUBDIR:-original}"
OUT="$AUDIO_PROJECT/results/a03_protocol_audit_v2"
if [[ -e "$OUT/protocol_audit_summary_PUBLIC.json" && "${FORCE:-0}" != "1" ]]; then
  echo "$OUT already has results; rerun with FORCE=1 to overwrite"; exit 1
fi

python - <<'EOF'
import importlib
for m in ("pandas", "numpy", "openpyxl", "soundfile", "pyreadstat"):
    try: importlib.import_module(m); print(f"  ok  {m}")
    except ImportError: print(f"  MISSING {m}" + ("  (SPSS checks will be skipped; pip install pyreadstat)" if m == "pyreadstat" else ""))
EOF

echo "trials: $TRIALS_ROOT"
echo "spss:   ${SPSS:-<not found>}"
echo "audio:  only wavs below a folder named '$AUDIO_SUBDIR' (AUDIO_SUBDIR= for all)"
echo "out:    $OUT"

SPSS_ARG=()
if [[ -n "$SPSS" && -f "$SPSS" ]]; then SPSS_ARG=(--spss "$SPSS"); else echo "[warn] SPSS file not found, skipping SPSS checks (set SPSS=...)"; fi

python "$(dirname "$0")/a03_protocol_audit.py" \
  --root "$TRIALS_ROOT" "${SPSS_ARG[@]}" --out "$OUT" --audio-stats --audio-subdir "$AUDIO_SUBDIR" \
  2>&1 | tee "$OUT.log"

echo
echo "Send back ONLY these two files:"
echo "  $OUT/protocol_audit_summary_PUBLIC.md"
echo "  $OUT/protocol_audit_summary_PUBLIC.json"
