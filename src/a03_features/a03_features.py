#!/usr/bin/env python3
"""
A03 Step 1a: acoustic feature extraction from the original VSA/STE recordings.

BLIND by design: the PUBLIC summary reports feature quality and channel agreement only,
never group or time effects, so the confirmatory analysis can be pre-registered afterwards.

File selection per participant folder (<DATE>_<ID>_<GROUP>):
  1. wavs below a folder named 'original'           (preferred)
  2. else wavs directly inside a folder named 'vsa'  (case-insensitive)
  never: processed / processed_norm / trimmed copies

Per file and per stereo channel (L, R), after resampling to 16 kHz:
  Praat (Parselmouth): F0 statistics in semitones, jitter, shimmer, HNR, CPPS, intensity,
  pauses, phonation time, approximate syllable rate (de Jong & Wempe style)
  openSMILE: eGeMAPSv02 functionals (88)
F0 floor/ceiling: two-pass per speaker over all of that speaker's files
  (floor = 0.75 * q25, ceiling = 1.5 * q75 of a 60-700 Hz first pass; De Looze & Hirst).

Outputs (in --out):
  PRIVATE_features_long.csv   one row per participant x file x channel
  PRIVATE_channel_choice.csv  per participant: channel with the higher median SNR
  features_qc_PUBLIC.json/.md aggregates only (no IDs, no group/time effects)
"""
import argparse, json, math, os, re, sys, time, warnings
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
NAME_RE = re.compile(r"(?P<date>\d{8})_(?P<pid>[0-9A-Za-z]+)_(?P<group>TSST|TEEB|REST)", re.I)
SKIP_DIRS = {"processed", "processed_norm", "trimmed"}
TARGET_SR = 16000


def norm_pid(x):
    d = re.sub(r"\D", "", str(x))
    return (d.lstrip("0") or "0") if d else None


# ---------------------------------------------------------------- file selection
def select_files(root):
    by_part = defaultdict(list)
    for p in root.rglob("*.wav"):
        pos = next((j for j in range(len(p.parts) - 2, -1, -1) if NAME_RE.search(p.parts[j])), None)
        if pos is None:
            continue
        m = NAME_RE.search(p.parts[pos])
        sub = [x.lower() for x in p.parts[pos + 1:-1]]
        if SKIP_DIRS & set(sub):
            continue
        tier = 1 if "original" in sub else (2 if sub == ["vsa"] else None)
        if tier is None:
            continue
        idx = re.findall(r"\d{1,3}", p.stem)
        by_part[(norm_pid(m["pid"]), m["group"].upper(), m["date"])].append(
            (tier, int(idx[-1]) if idx else None, p))
    out = {}
    for key, files in by_part.items():
        best = min(t for t, _, _ in files)
        fs = sorted([(i, p) for t, i, p in files if t == best and i is not None])
        seen, uniq = set(), []
        for i, p in fs:
            if i not in seen:
                seen.add(i); uniq.append((i, p))
        out[key] = dict(tier=best, files=uniq)
    return out


# ---------------------------------------------------------------- audio helpers
def load_channels(path):
    import soundfile as sf
    from scipy.signal import resample_poly
    x, sr = sf.read(str(path), dtype="float64", always_2d=True)
    g = math.gcd(TARGET_SR, sr)
    chans = []
    for c in range(min(x.shape[1], 2)):
        y = x[:, c] if sr == TARGET_SR else resample_poly(x[:, c], TARGET_SR // g, sr // g)
        chans.append(y)
    return chans, sr, x.shape[1]


def snr_proxy(y, sr=TARGET_SR):
    hop = int(0.05 * sr)
    fr = y[: len(y) // hop * hop].reshape(-1, hop)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-12)
    return float(np.percentile(db, 90) - np.percentile(db, 10))


def first_pass_f0(y):
    import parselmouth
    snd = parselmouth.Sound(y, sampling_frequency=TARGET_SR)
    f0 = snd.to_pitch_ac(time_step=0.01, pitch_floor=60, pitch_ceiling=700).selected_array["frequency"]
    return f0[f0 > 0]


def st(f):
    return 12 * np.log2(f / 100.0)


def praat_features(y, floor, ceil):
    import parselmouth
    from parselmouth.praat import call
    from scipy.signal import find_peaks
    snd = parselmouth.Sound(y, sampling_frequency=TARGET_SR)
    d = dict(duration_total_s=snd.duration)

    pitch = snd.to_pitch_ac(time_step=0.01, pitch_floor=floor, pitch_ceiling=ceil)
    f0 = pitch.selected_array["frequency"]
    v = f0[f0 > 0]
    if len(v) >= 20:
        s = st(v)
        d.update(f0_mean_st=s.mean(), f0_median_st=np.median(s), f0_sd_st=s.std(),
                 f0_p10_st=np.percentile(s, 10), f0_p90_st=np.percentile(s, 90),
                 f0_range_st=np.percentile(s, 90) - np.percentile(s, 10), f0_mean_hz=v.mean())

    # voice quality
    try:
        pp = call(snd, "To PointProcess (periodic, cc)", floor, ceil)
        d["jitter_local"] = call(pp, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
        d["jitter_rap"] = call(pp, "Get jitter (rap)", 0, 0, 0.0001, 0.02, 1.3)
        d["shimmer_local"] = call([snd, pp], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6)
        d["shimmer_apq3"] = call([snd, pp], "Get shimmer (apq3)", 0, 0, 0.0001, 0.02, 1.3, 1.6)
    except Exception:
        pass
    try:
        h = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=floor, silence_threshold=0.1, periods_per_window=1.0).values
        h = h[h > -200]
        if h.size:
            d["hnr_mean_db"] = float(h.mean())
    except Exception:
        pass
    try:
        pcg = call(snd, "To PowerCepstrogram", 60, 0.002, 5000, 50)
        d["cpps_db"] = call(pcg, "Get CPPS", "yes", 0.02, 0.0005, 60, 330, 0.05,
                            "Parabolic", 0.001, 0.05, "Exponential decay", "Robust")
    except Exception:
        pass

    # intensity, pauses, phonation
    inten = snd.to_intensity(minimum_pitch=floor, time_step=0.01)
    iv = inten.values[0]
    it = inten.xs()
    try:
        tg = call(inten, "To TextGrid (silences)", -25, 0.25, 0.05, "silent", "sounding")
        n = int(call(tg, "Get number of intervals", 1))
        iv_list = [(call(tg, "Get start time of interval", 1, k), call(tg, "Get end time of interval", 1, k),
                    call(tg, "Get label of interval", 1, k)) for k in range(1, n + 1)]
        snd_iv = [(a, b) for a, b, l in iv_list if l == "sounding"]
        if snd_iv:
            span0, span1 = snd_iv[0][0], snd_iv[-1][1]
            pauses = [(a, b) for a, b, l in iv_list if l == "silent" and a >= span0 and b <= span1]
            phon = sum(b - a for a, b in snd_iv)
            ptot = sum(b - a for a, b in pauses)
            d.update(speech_span_s=span1 - span0, phonation_time_s=phon, n_pauses=len(pauses),
                     pause_total_s=ptot, pause_mean_s=(ptot / len(pauses)) if pauses else 0.0,
                     pause_ratio=ptot / (span1 - span0) if span1 > span0 else np.nan,
                     pauses_per_min=len(pauses) / ((span1 - span0) / 60) if span1 > span0 else np.nan)
            mask = np.zeros_like(it, dtype=bool)
            for a, b in snd_iv:
                mask |= (it >= a) & (it <= b)
            if mask.any():
                d["intensity_mean_db_rel"] = float(iv[mask].mean())   # uncalibrated: within-speaker use only
                d["intensity_sd_db"] = float(iv[mask].std())
            # syllable nuclei: intensity peaks >= 2 dB prominence, above median, voiced
            thr = np.median(iv[mask]) if mask.any() else np.median(iv)
            pk, _ = find_peaks(iv, prominence=2.0, distance=5)
            pk = [p for p in pk if iv[p] > thr and mask[p]
                  and pitch.get_value_at_time(it[p]) == pitch.get_value_at_time(it[p])]  # not NaN = voiced
            d["n_syllables_est"] = len(pk)
            d["speech_rate_syl_s"] = len(pk) / (span1 - span0) if span1 > span0 else np.nan
            d["articulation_rate_syl_s"] = len(pk) / phon if phon > 0 else np.nan
    except Exception:
        pass
    d["voiced_frac_of_phonation"] = (len(v) * 0.01) / d["phonation_time_s"] if d.get("phonation_time_s") else np.nan
    return d


_SMILE = None
def egemaps(y):
    global _SMILE
    try:
        import opensmile
        if _SMILE is None:
            _SMILE = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02,
                                     feature_level=opensmile.FeatureLevel.Functionals)
        f = _SMILE.process_signal(y.astype(np.float32), TARGET_SR).iloc[0]
        return {f"egemaps_{k}": float(v) for k, v in f.items()}
    except Exception:
        return {}


# ---------------------------------------------------------------- per participant
def process_participant(key, entry, root, use_egemaps):
    pid, grp, date = key
    rows, errors = [], []
    loaded = []
    for idx, p in entry["files"]:
        try:
            chans, sr, nch = load_channels(p)
            loaded.append((idx, p, chans, sr, nch))
        except Exception as ex:
            errors.append(f"{p.name}: load {ex}")
    # speaker-level F0 range, per channel, from all files of this speaker
    ranges = {}
    for c in (0, 1):
        allf = [first_pass_f0(ch[c]) for _, _, ch, _, _ in loaded if len(ch) > c]
        allf = np.concatenate(allf) if allf else np.array([])
        if allf.size >= 50:
            q25, q75 = np.percentile(allf, [25, 75])
            ranges[c] = (max(50.0, 0.75 * q25), min(800.0, 1.5 * q75))
        else:
            ranges[c] = (75.0, 500.0)
    for rank, (idx, p, chans, sr, nch) in enumerate(loaded):
        for c, y in enumerate(chans):
            base = dict(pid=pid, group=grp, date=date, wav_index=idx, wav_rank=rank, channel="LR"[c],
                        wav_relpath=str(p.relative_to(root)), file_tier=entry["tier"], orig_sr=sr,
                        orig_channels=nch, snr_proxy_db=snr_proxy(y),
                        f0_floor_hz=ranges[c][0], f0_ceiling_hz=ranges[c][1])
            try:
                base.update(praat_features(y, *ranges[c]))
            except Exception as ex:
                errors.append(f"{p.name} ch{c}: praat {ex}")
            if use_egemaps:
                base.update(egemaps(y))
            rows.append(base)
    return rows, errors


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=max(1, min(16, (os.cpu_count() or 4) - 2)))
    ap.add_argument("--limit", type=int, default=0, help="process only N participants (speed test)")
    ap.add_argument("--no-egemaps", action="store_true")
    a = ap.parse_args()
    root, out = Path(a.root), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    sel = select_files(root)
    keys = sorted(sel)
    if a.limit:
        keys = keys[: a.limit]
    print(f"[info] participants: {len(keys)}  files: {sum(len(sel[k]['files']) for k in keys)}  workers: {a.workers}")
    t0, rows, errors = time.time(), [], []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(process_participant, k, sel[k], root, not a.no_egemaps): k for k in keys}
        for n, f in enumerate(as_completed(futs), 1):
            try:
                r, e = f.result(); rows += r; errors += e
            except Exception as exn:
                errors.append(f"participant failed: {exn}")
            if n % 10 == 0 or n == len(keys):
                print(f"  {n}/{len(keys)} participants, {time.time() - t0:.0f} s", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "PRIVATE_features_long.csv", index=False)
    (out / "PRIVATE_errors.txt").write_text("\n".join(errors))

    # channel choice: higher median SNR over the participant's files, fixed across recordings
    ch = (df.groupby(["pid", "group", "date", "channel"]).snr_proxy_db.median().unstack("channel"))
    if "R" in ch:
        ch["chosen"] = np.where(ch["R"] > ch["L"], "R", "L")
        ch["snr_diff_db"] = ch["L"] - ch["R"]
    else:
        ch["chosen"] = "L"; ch["snr_diff_db"] = np.nan
    ch.reset_index().to_csv(out / "PRIVATE_channel_choice.csv", index=False)

    # ---------------- PUBLIC, blind QC
    def q(s):
        s = pd.to_numeric(s, errors="coerce").dropna()
        return None if s.empty else dict(n=int(len(s)), median=round(float(s.median()), 4),
                                         q25=round(float(s.quantile(.25)), 4), q75=round(float(s.quantile(.75)), 4))
    praat_cols = [c for c in df.columns if not c.startswith("egemaps_") and c not in
                  ("pid", "group", "date", "wav_index", "wav_rank", "channel", "wav_relpath", "file_tier",
                   "orig_sr", "orig_channels")]
    eg_cols = [c for c in df.columns if c.startswith("egemaps_")]
    L = df[df.channel == "L"].set_index(["pid", "group", "date", "wav_rank"])
    R = df[df.channel == "R"].set_index(["pid", "group", "date", "wav_rank"])
    common = L.index.intersection(R.index)
    agree = {}
    for c in praat_cols + eg_cols[:0]:
        if c not in L or c not in R:
            continue
        a_, b_ = L.loc[common, c].astype(float), R.loc[common, c].astype(float)
        ok = a_.notna() & b_.notna()
        r_level = float(np.corrcoef(a_[ok], b_[ok])[0, 1]) if ok.sum() > 10 else None
        # within-speaker change VSA rank1 - rank0, compared across channels
        def delta(X):
            w = X[c].astype(float).unstack("wav_rank")
            return (w[1] - w[0]) if 1 in w and 0 in w else pd.Series(dtype=float)
        dL, dR = delta(L.loc[common]), delta(R.loc[common])
        j = dL.index.intersection(dR.index); okd = dL[j].notna() & dR[j].notna()
        r_delta = float(np.corrcoef(dL[j][okd], dR[j][okd])[0, 1]) if okd.sum() > 10 else None
        agree[c] = dict(r_LR_level=None if r_level is None else round(r_level, 3),
                        r_LR_delta_rank1_minus_rank0=None if r_delta is None else round(r_delta, 3))
    eg_agree = []
    for c in eg_cols:
        a_, b_ = L.loc[common, c].astype(float), R.loc[common, c].astype(float)
        ok = a_.notna() & b_.notna()
        if ok.sum() > 10 and a_[ok].std() > 0 and b_[ok].std() > 0:
            eg_agree.append(np.corrcoef(a_[ok], b_[ok])[0, 1])
    per_part = df.groupby(["pid", "group", "date"])
    sr_const = per_part.orig_sr.nunique()
    pub = dict(
        generated=time.strftime("%Y-%m-%dT%H:%M:%S"),
        n_participants_by_group=Counter(k[1] for k in keys),
        n_participants_by_files=Counter(len(sel[k]["files"]) for k in keys),
        file_tier_counts=Counter(sel[k]["tier"] for k in keys),
        n_rows=int(len(df)), n_errors=len(errors),
        error_types=Counter(re.sub(r".*: (\w+) .*", r"\1", e) for e in errors),
        runtime_s=round(time.time() - t0),
        sr_constant_within_participant=int((sr_const == 1).sum()), sr_varies_within_participant=int((sr_const > 1).sum()),
        chosen_channel=Counter(ch["chosen"]),
        chosen_channel_by_orig_sr=Counter(f"{s}_{c}" for s, c in zip(per_part.orig_sr.first().reindex(ch.index), ch["chosen"])),
        snr_L_minus_R_db=q(ch["snr_diff_db"]),
        f0_floor_hz=q(df.f0_floor_hz.drop_duplicates()), f0_ceiling_hz=q(df.f0_ceiling_hz.drop_duplicates()),
        f0_speaker_median_hz_hist=Counter(int(v // 25 * 25) for v in per_part.f0_mean_hz.median().dropna()) if "f0_mean_hz" in df else {},
        feature_distribution_all_recordings={c: q(df[c]) for c in praat_cols},
        feature_missing_rate={c: round(float(df[c].isna().mean()), 4) for c in praat_cols + eg_cols if df[c].isna().any()},
        channel_agreement_praat=agree,
        channel_agreement_egemaps_r_level=q(pd.Series(eg_agree)),
    )

    def clean(o):
        if isinstance(o, Counter): o = dict(o)
        if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [clean(v) for v in o]
        if isinstance(o, np.integer): return int(o)
        if isinstance(o, np.floating): return None if np.isnan(o) else float(o)
        if isinstance(o, float) and np.isnan(o): return None
        return o
    pub = clean(pub)
    (out / "features_qc_PUBLIC.json").write_text(json.dumps(pub, indent=2, ensure_ascii=False))
    md = ["# A03 feature extraction QC (PUBLIC, blind: no group/time effects)", "",
          f"- participants: {pub['n_participants_by_group']}  files per participant: {pub['n_participants_by_files']}",
          f"- file tier (1 = original/, 2 = vsa/): {pub['file_tier_counts']}",
          f"- rows: {pub['n_rows']}  errors: {pub['n_errors']} {pub['error_types']}  runtime: {pub['runtime_s']} s",
          f"- chosen channel: {pub['chosen_channel']}  by sr: {pub['chosen_channel_by_orig_sr']}",
          f"- SNR L-R (dB): {pub['snr_L_minus_R_db']}", "",
          "## Channel agreement (Praat features)", "", "| feature | r level | r delta (rank1-rank0) |", "|---|---|---|"]
    md += [f"| {k} | {v['r_LR_level']} | {v['r_LR_delta_rank1_minus_rank0']} |" for k, v in agree.items()]
    (out / "features_qc_PUBLIC.md").write_text("\n".join(md) + "\n")
    print(f"[done] {len(df)} rows, {len(errors)} errors -> {out}")


if __name__ == "__main__":
    main()
