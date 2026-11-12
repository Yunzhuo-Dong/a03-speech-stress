# A03 Speech & Stress — Decision Log and Baseline Statistics

> **Historical document (2026-11-06).** Written before the group analyses were run. Open items in Section 9 were partly resolved later; final results are in [final_report.md](final_report.md).

**Project:** Mannheim A03 speech analysis (TU Dresden NIC)
**Last updated:** 2026-11-06
**Status:** Data audit and blind feature extraction complete. Confirmatory analysis **not yet run**, pending pre-registration.

All numbers below are group-level aggregates. No participant identifiers are included.

---

## 1. Summary

- The three A03 arms form a **dissociation design**:
  - **TSST**: psychosocial stress with HPA (cortisol) response.
  - **TEEB**: moderate ergometer cycling, i.e. sympathetic/physical arousal without HPA response.
  - **REST**: newspaper reading.
- Recording times are **highly consistent across groups**. The earlier "strict timing QC" (50 participants) was driven mainly by spreadsheet row-order artefacts and missing timestamps, not by real timing problems.
- Protocol ↔ SPSS ↔ audio linkage is **reliable**. Cortisol values agree in 733 of 737 checks and SBP values in 605 of 611.
- Acoustic features were extracted **blind**: no group or time effects on speech have been inspected yet.
- Proposed primary outcome: **change in mean F0 (semitones), VSA1 − VSA0**. It is the most replicated vocal stress marker and has the highest measurement reliability in this dataset (inter-channel r = 0.985 for the change score).

---

## 2. Decision log

Status: **Decided** = settled by the data or by protocol documentation. **Proposed** = needs confirmation by the supervisor before pre-registration.

| # | Decision | Rationale | Status |
|---|---|---|---|
| D1 | Group label = `a03_type`. The SPSS variable `Group` is not used. | Protocol headers agree with `a03_type` in every case. All 3 label conflicts involve `Group`. | Decided |
| D2 | Cortisol unit = µg/L; convert to nmol/L with factor 2.76. | The protocol instruction sheet specifies µg/L; values (≈ 1–15) are consistent with salivary cortisol. | Decided |
| D3 | Cortisol responder = max(T2–T4) − T1 ≥ 1.5 nmol/L (≈ 0.54 µg/L). | Established research criterion (Miller et al., 2013; verify citation). The earlier D2 threshold (1.5 µg/L ≈ 4.1 nmol/L) was ~3× too strict and ignored T2 peaks. | Proposed |
| D4 | Pair VSA recordings with protocol rows by **table order**, not by the VSA label written in the protocol. | Only 76/121 protocols have standard labels 0–4. The rest have missing labels, typos (20, 80, 82, 90, 118) or offsets (1–5, 2–6). | Decided |
| D5 | Pair wav files by **rank** of their file index. | Some participants' files are numbered 1–5 or have gaps. | Decided |
| D6 | Audio source = `vsa/original/`; fall back to files directly in `vsa/` (6 participants). Never use `processed/`, `processed_norm/` or `trimmed/`. | The derivative folders exist for ~46 participants only and are processed copies. | Decided |
| D7 | Resample all audio to 16 kHz. Recording format (96 kHz vs 44.1 kHz) enters models as a covariate. | Format changes with year and is mildly unbalanced in 2021 (TSST 64% at 96 kHz vs ~44% in the other arms). It is constant within 115/116 participants. | Decided |
| D8 | Extract features **per channel** and average the **feature values** of L and R. No signal averaging, no SNR-based channel selection. | The channels are different signals (L/R correlation median 0.8, minimum −0.4), so signal averaging risks phase cancellation. SNR is practically identical (median L−R = −0.03 dB), so SNR-based selection is arbitrary (57 L / 59 R). | Decided |
| D9 | Inter-channel correlation of the change score is the **reliability criterion**. Features need r ≥ 0.70 to be confirmatory; all others are exploratory only. | Group-blind and objective. | Proposed |
| D10 | Per-speaker two-pass F0 range: floor = 0.75 × q25, ceiling = 1.5 × q75 of a 60–700 Hz first pass, pooled over the speaker's recordings. | Does not require sex; identical settings across a speaker's 5 recordings (De Looze & Hirst method; verify citation). | Decided |
| D11 | Session start time is a covariate in all models. | Start times range 08:30–16:30; Spearman ρ = −0.53 with baseline cortisol. | Decided |
| D12 | TEEB is analysed as its own arm and is never pooled with REST. | TEEB has the largest heart-rate increase but no cortisol response. Pooling it with REST (as in earlier experiments D3/D5) mislabels arousal as "non-stress". | Decided |
| D13 | Primary window = VSA1 (≈ 1–3 min after the task). VSA2 coincides with the group cortisol peak (T4). | Timing analysis (Section 4). | Decided |
| D14 | Blinding: no speech outcome is compared across groups or time points before pre-registration. | Avoids analytic flexibility; supports manuscript credibility. | Decided |
| D15 | Earlier 15-participant Mannheim test sets are no longer treated as untouched holdouts. Future predictive work uses repeated nested CV over the full cohort. | A test set of 15 with ~5 positives has AUROC CIs of about ±0.25 or wider, and these test sets were reused across experiments D1–D5. | Decided |
| D16 | SPSS/protocol value disagreements (4 cortisol, 6 SBP, 7 start times) are resolved manually from the protocol's raw entries. | One known SPSS error: a T6 mean stored as 2.325 while the duplicates are 0.41/0.44. | Proposed |

---

## 3. Cohort and data quality

### 3.1 Cohort

| Group | SPSS A03 | Protocols | Features extracted | Strict complete* | Strict + cortisol T1/T4 |
|---|---:|---:|---:|---:|---:|
| TSST | 40 | 39 | 39 | 32 | 32 |
| TEEB | 41 | 41 | 37 | 28 | 27 |
| REST | 40 | 41 | 40 | 30 | 29 |
| **Total** | **121** | **121** | **116** | **90** | **88** |

\* Strict complete = protocol + 5 wav files + all 5 VSA timestamps. H1/H2 only require VSA0 and VSA1, so their analysable sample is larger.

Files per participant (feature extraction): 5 files for 110 participants, 4 for 3, 3 for 2, 6 for 1.

### 3.2 Demographics (SPSS, A03, n = 121)

| Group | Male / Female | Age, mean (SD) |
|---|---|---|
| TSST | 27 / 13 | 38.1 (12.5) |
| TEEB | 25 / 16 | 38.6 (13.8) |
| REST | 24 / 16 | 38.6 (13.7) |

### 3.3 Linkage checks

| Check | Agree | Disagree |
|---|---:|---:|
| Cortisol values, protocol vs SPSS (`Cortisol_Mittelwert_k`) | 733 | 4 |
| SBP, protocol vs SPSS (`RR_sys_t1..t5`) | 605 | 6 |
| Group, protocol vs `a03_type` | all | 0 |
| Group, protocol vs `Group` | — | 3 |
| Session start, protocol vs SPSS (> 15 min apart) | — | 7 |

`RR_sys_t1..t5` are confirmed to be the blood pressures measured at VSA0..VSA4. Each recording therefore has a matched physiological label.

### 3.4 Known data issues (to resolve or handle in sensitivity analyses)

- **Suspected mislabelled participant:** one REST protocol note describes TSST experiences ("very stressed during the talk", "arithmetic was OK"). The protocol and `a03_type` both say REST. Needs manual check.
- **Incomplete TSST panel:** one TSST session had only the female panel member present.
- **THC-positive:** 3 participants.
- **SPSS entry errors:**
  - one duplicate cortisol value entered as 248 (the stored mean is correct);
  - one T6 mean stored incorrectly;
  - `AUC_i` is labelled "outlier excluded" but still contains a value of 2464;
  - `Cortisol_Increase_T1_to_T4` is a 0/1 indicator, not a magnitude.
- **High cortisol:** 14 participants have cortisol > 10 µg/L (10 of them TSST). These are kept, with robust or log-scale analysis.
- **Protocol bookkeeping:**
  - 43 protocols with rows out of time order;
  - 57 VSA rows without timestamps;
  - 2 participant-ID mismatches between file name and protocol header;
  - 2 participants with duplicate protocols;
  - 5 protocols without audio; 1 participant with audio but no protocol.
- **Sampling rate:** 1 participant's sampling rate changes within the session.

---

## 4. Protocol timing

### 4.1 VSA recordings, minutes from task onset (median [IQR])

| Group | VSA0 | VSA1 | VSA2 | VSA3 | VSA4 |
|---|---|---|---|---|---|
| TSST | −9 [−11, −7.5] | 17 [16, 20] | 41 [39, 43.5] | 67 [62, 70] | 167 [163, 177] |
| TEEB | −8 [−10, −7] | 14 [13, 18] | 38.5 [36, 43] | 63 [60, 68] | 168 [161, 174] |
| REST | −8 [−9, −6] | 17 [15, 18] | 38.5 [36, 41] | 65.5 [60, 67] | 171 [161, 181] |

VSA1 relative to the start of the last task row, median [IQR]:

- TSST: 12 [11, 13] min after the start of "TSST Durchführung"
- TEEB: 9 [8, 10] min after the start of the 8-min ride
- REST: 12 [11, 12] min after the start of the second "Zeitung lesen" row

In all arms, VSA1 is recorded within roughly 1–3 minutes after the task ends.

### 4.2 Fixed recording ↔ cortisol pairing (no exceptions)

| Recording | VSA0 | VSA1 | VSA2 | VSA3 | VSA4 |
|---|---|---|---|---|---|
| Paired cortisol sample | T1 | T3 | T4 | T5 | T6 |

T2 (+3–4 min) has no recording.

### 4.3 Intervening tasks (identical in all arms)

| Between | Task |
|---|---|
| VSA1 → VSA2 | BarLab alcohol-cue exposure |
| VSA2 → VSA3 | IAT and DPT |
| VSA3 → VSA4 | ~70 min fMRI |

### 4.4 Cortisol sampling, minutes from task onset (median)

| Group | T1 | T2 | T3 | T4 | T5 | T6 |
|---|---:|---:|---:|---:|---:|---:|
| TSST | −9 | 4 | 17 | 42 | 67 | 161.5 |
| TEEB | −8 | 3 | 14 | 38 | 63 | 159 |
| REST | −8 | 3 | 17 | 39 | 66 | 160 |

---

## 5. Physiological manipulation check (SPSS)

These are non-speech outcomes; reporting them does not break speech blinding.

### 5.1 Salivary cortisol, group means (µg/L)

| Group | T1 | T2 | T3 | T4 | T5 | T6 | T4 − T1 | Responders* |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TSST | 4.01 | 3.58 | 4.93 | **6.53** | 4.45 | 2.80 | +2.51 | 78% |
| TEEB | 4.15 | 3.92 | 3.83 | 3.37 | 2.90 | 1.97 | −0.82 | 27% |
| REST | 4.42 | 3.86 | 3.84 | 3.51 | 2.97 | 2.49 | −0.84 | 28% |

\* max(T2–T4) − T1 ≥ 1.5 nmol/L.

- In TSST, the individual peak is at T4 for 28/40 participants, T3 for 9 and T2 for 3.
- TSST +2.51 µg/L ≈ +6.9 nmol/L, a typical TSST response.
- The ~27% "responders" in the control arms reflect noise and the circadian decline.

### 5.2 Heart rate and blood pressure

Heart rate, mean (bpm; available for 67 participants):

| Group | Rest phase | Task phase | Change |
|---|---:|---:|---:|
| TSST | 75.0 | 93.3 | +18 |
| TEEB | 72.7 | **104.1** | **+31** |
| REST | 73.0 | 85.3 | +12 |

Systolic BP at each recording, mean (mmHg; n ≈ 117–120):

| Group | VSA0 | VSA1 | VSA2 | VSA3 | VSA4 | VSA1 − VSA0 |
|---|---:|---:|---:|---:|---:|---:|
| TSST | 130.2 | 144.3 | 136.7 | 131.3 | 135.6 | +14.1 |
| TEEB | 128.8 | 138.0 | 132.6 | 128.3 | 132.2 | +9.2 |
| REST | 130.6 | 136.7 | 135.2 | 132.1 | 134.0 | +6.1 |

---

## 6. Audio properties (original files)

**Formats**

- 544 files from 110 participants in `vsa/original/`, plus 30 files from 6 participants directly in `vsa/`.
- Sampling rate: 96 kHz for 385 original files, 44.1 kHz for 159.
- All files are stereo; bit depth is PCM 16, 24 or 32.

**Sampling rate by year** (share of recordings at 96 kHz)

| Year | TSST | TEEB | REST |
|---|---:|---:|---:|
| 2020 | 93% | 93% | 93% |
| 2021 | 64% | 43% | 45% |
| 2022 | 66% | 72% | 63% |

**Stereo channels** (original files, n = 544)

- No file has identical channels.
- L/R signal correlation: median 0.80 [0.60, 0.90], minimum −0.40.
- L − R level difference: median 0.7 dB.

**Level and noise.** Speech level (≈ −28 dBFS RMS), noise floor (≈ −52 to −54 dB) and SNR proxy (≈ 27–29 dB) are similar across groups and recording indices. The noise floor is balanced across groups within each year.

**Recording duration (s, median)**

| VSA0 | VSA1 | VSA2 | VSA3 | VSA4 |
|---:|---:|---:|---:|---:|
| 45.3 | 43.3 | 42.6 | 41.5 | 41.7 |

The monotonic decline is a practice effect, consistent with re-reading the same text (still to be confirmed by transcription). This is why the REST arm is essential as a control for time effects.

---

## 7. Feature extraction QC (blind)

Run: 116 participants, 1148 file × channel rows, 0 errors, 763 s with 16 workers. No missing values.

**Speaker F0 (median of a speaker's recordings).** The distribution is bimodal:

| F0 bin (Hz) | 75 | 100 | 125 | 150 | 175 | 200 | 225 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Speakers | 13 | 43 | 13 | 10 | 21 | 15 | 1 |

This is consistent with the ~2:1 male/female ratio. Speaker F0 floor: median 84 Hz; ceiling: median 217 Hz.

### 7.1 Feature distributions (all recordings and channels, median [IQR])

| Feature | Median [IQR] |
|---|---|
| F0 mean (st re 100 Hz) | 3.91 [0.99, 10.27] |
| F0 mean (Hz) | 127.0 [107.2, 184.6] |
| F0 SD (st) | 2.80 [2.26, 3.20] |
| F0 range p10–p90 (st) | 7.26 [5.71, 8.41] |
| Jitter local | 0.028 [0.024, 0.032] |
| Jitter RAP | 0.013 [0.011, 0.015] |
| Shimmer local | 0.124 [0.108, 0.137] |
| Shimmer APQ3 | 0.050 [0.042, 0.057] |
| HNR (dB) | 11.6 [9.7, 13.8] |
| CPPS (dB) | 7.42 [6.86, 7.91] |
| Recording duration (s) | 42.9 [39.4, 47.0] |
| Speech span / reading time (s) | 41.7 [38.6, 45.8] |
| Phonation time (s) | 31.2 [24.9, 34.4] |
| Number of pauses | 16 [12, 24] |
| Total pause time (s) | 10.3 [7.5, 17.6] |
| Mean pause (s) | 0.63 [0.56, 0.75] |
| Pause ratio | 0.24 [0.18, 0.42] |
| Pauses per minute | 22.6 [17.7, 33.8] |
| Intensity mean (dB, uncalibrated) | 62.8 [59.7, 67.0] |
| Intensity SD (dB) | 7.24 [6.69, 7.82] |
| Speech rate (syll/s, estimated) | 3.05 [2.45, 3.46] |
| Articulation rate (syll/s, estimated) | 4.26 [3.82, 4.69] |
| Voiced fraction of phonation | 0.69 [0.63, 0.80] |
| SNR proxy (dB) | 26.1 [24.1, 28.6] |

**Note.** Jitter (2.8%) and shimmer (12.4%) are far above sustained-vowel norms. In connected reading they mainly reflect prosody and voicing onsets, not vocal-fold perturbation. CPPS is the preferred voice-quality measure for connected speech.

### 7.2 Measurement reliability: inter-channel agreement

L and R are two simultaneous recordings of the same speech, so their agreement estimates measurement reliability. "Δ" is the within-speaker change VSA1 − VSA0, which is what the confirmatory analyses use.

| Feature | r (level) | r (Δ) | Use (D9) |
|---|---:|---:|---|
| Reading time (speech span) | 0.999 | 1.000 | confirmatory |
| Total pause time | 0.996 | 0.999 | confirmatory-eligible |
| F0 median (st) | 1.000 | 0.988 | confirmatory-eligible |
| F0 mean (st) | 1.000 | 0.985 | **primary** |
| F0 p90 (st) | 1.000 | 0.986 | confirmatory-eligible |
| F0 SD (st) | 0.998 | 0.977 | confirmatory-eligible |
| CPPS | 0.982 | 0.961 | confirmatory |
| F0 range (st) | 0.997 | 0.959 | confirmatory |
| Mean pause duration | 0.814 | 0.913 | confirmatory-eligible |
| F0 p10 (st) | 0.999 | 0.897 | confirmatory-eligible |
| Jitter RAP | 0.952 | 0.856 | exploratory (validity, see 7.1) |
| Shimmer APQ3 | 0.924 | 0.849 | exploratory (validity) |
| Intensity mean | 0.925 | 0.832 | exploratory (uncalibrated) |
| Shimmer local | 0.927 | 0.816 | exploratory (validity) |
| Jitter local | 0.957 | 0.800 | exploratory (validity) |
| Number of syllables (est.) | 0.859 | 0.789 | exploratory |
| Phonation time | 0.834 | 0.782 | exploratory |
| Speech / articulation rate | 0.87 | 0.770 | exploratory (reading time preferred) |
| Pause ratio | 0.835 | 0.762 | exploratory |
| HNR | 0.954 | **0.672** | exploratory (unreliable Δ) |
| Pauses per minute | 0.797 | **0.588** | exploratory (unreliable Δ) |
| Intensity SD | 0.840 | **0.503** | exploratory (unreliable Δ) |
| Number of pauses | 0.796 | **0.443** | exploratory (unreliable Δ) |
| Voiced fraction | 0.675 | **0.390** | exploratory (unreliable Δ) |

eGeMAPS (88 functionals): inter-channel r (level) median 0.96 [0.88, 0.98]. All eGeMAPS features are exploratory.

---

## 8. Proposed pre-registered analysis plan

To be confirmed (Section 9) and registered on OSF **before** any speech outcome is compared across groups. The analysis code will be attached to the registration.

**Sample**

- H1/H2: all participants with VSA0 and VSA1.
- H3: all participants with ≥ 3 recordings.
- Group = `a03_type`.

**Outcome definitions**

- Primary: ΔF0 mean (st) = VSA1 − VSA0, with features averaged over L/R.
- Secondary (Holm-corrected, family of 3): ΔF0 range (st), ΔCPPS, Δreading time.

**H1 — stress effect.** ANCOVA: Δ ~ group + baseline value + sex + session start time + recording format. Contrast TSST − REST, two-sided, α = .05.

**H2 — specificity** (same ANCOVA):

- **H2a:** contrast TSST − TEEB, two-sided, plus a TOST equivalence test with bounds ±0.5 st for the primary outcome.
- **H2b:** add ΔSBP (VSA1 − VSA0) as a covariate. Does the TSST effect remain after accounting for cardiovascular arousal? Heart rate is analysed in the n = 67 subset only.

**H3 — within-person coupling.** Linear mixed model over all recordings:

F0 ~ SBP_within + log-cortisol_within + time point + group + (1 | participant)

Physiological predictors are person-mean centred. Recording ↔ cortisol pairing follows Section 4.2.

**Sensitivity analyses**

- Exclude: the suspected mislabelled REST participant, THC-positive participants, the incomplete-panel TSST session, and the participant whose sampling rate changes.
- Strict-timing subset only.
- Single-channel (L, R) instead of averaged features.
- Robust regression.

**Exploratory**

- All other features and eGeMAPS.
- Full five-point trajectories (group × time LMM).
- Cortisol-responder analyses.
- Predictive models (repeated nested CV).
- Follow-up outcomes (PSS, drinking diary).

**Power note.** With ~38 per arm, a two-group contrast has 80% power for d ≈ 0.65 on raw change scores. ANCOVA adjustment for baseline (expected high pre–post correlation for F0) increases power. Effect sizes are reported with 95% CIs.

---

## 9. Open items requiring confirmation

- [ ] Confirm the primary outcome (ΔF0 mean) and the secondary family (F0 range, CPPS, reading time).
- [ ] Confirm the equivalence bound for H2a (proposed ±0.5 st; check against published TSST F0 effects).
- [ ] Confirm the responder definition (D3) and the reliability threshold r ≥ 0.70 (D9).
- [ ] Manually check: the suspected mislabelled REST participant; 4 cortisol / 6 SBP / 7 start-time disagreements; 2 ID mismatches; 2 duplicate protocols.
- [ ] Confirm by transcription (e.g. Whisper large-v3 on a few participants) that the same text is read at every VSA.
- [ ] Verify the citations named in this README (Miller et al., 2013; De Looze & Hirst; Giddens et al., 2013; Pisanski et al., 2018).
- [ ] Decide who registers the plan on OSF.

---

## 10. Scripts and outputs

All paths are relative to `$AUDIO_PROJECT`.

| Step | Script | Output |
|---|---|---|
| 0 — protocol / audio / SPSS audit (v2) | `src/a03_protocol_audit/run.sh` | `results/a03_protocol_audit_v2/` |
| 1a — blind feature extraction | `src/a03_features/run.sh` (`test`, `start`, `status`) | `results/a03_features_v1/` |
| 1b — confirmatory analysis | to be written after registration | — |

**Output rules**

- Shareable outputs are `*_PUBLIC.json` and `*_PUBLIC.md` (aggregates only).
- `PRIVATE_*` files contain participant-level data and stay on the research disk.
