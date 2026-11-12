# A03 Step 1b — Does psychosocial stress change the voice in read speech?

> **Superseded (kept for transparency).** These are the first-pass Step 1b numbers. The data issue in Section 6 (abnormally long recordings) was resolved in Step 2 with the 20–70 s duration rule, and an eGeMAPS feature-name bug was fixed. Final numbers are in [final_report.md](final_report.md); conclusions did not change.

**Date:** 2026-11-09
**Status:** Analysis plan fixed in advance (README decision log, 2026-11-06), not pre-registered. Results are **provisional** until the data issue in Section 6 is resolved.

---

## 1. Bottom line

Participants showed a **strong cardiovascular and cortisol stress response**, measured at the same moment the speech was recorded. Yet their voice during standardized reading **did not change**.

The null is informative, not inconclusive:

- An **equivalence test** rules out any F0 increase larger than **+0.12 semitones**.
- The result holds across every sensitivity analysis.

---

## 2. Design

**Arms**

| Arm | n | Manipulation |
|---|---:|---|
| TSST | 37 | Psychosocial stress: sympathetic + HPA (cortisol) |
| TEEB | 37 | Moderate cycling: sympathetic arousal, no HPA response |
| REST | 40 | Newspaper reading |

**Recordings.** The same text was read aloud at each recording (~42 s).

| Recording | Timing | Role |
|---|---|---|
| VSA0 | ~8 min before task onset | Baseline |
| VSA1 | ~1–3 min after the task ends | Primary window |

**Physiology.** Blood pressure was measured at every recording. Salivary cortisol was sampled at fixed time points.

**Outcome.** Δ = VSA1 − VSA0.

**Model.** ANCOVA: Δ ~ group + baseline + sex + session start time + recording format. Reference group = REST.

---

## 3. Manipulation check: the stressor worked

| Arm | ΔSBP at VSA1 (mmHg) | ΔHR (bpm; n = 66) | Δcortisol T4 − T1 (nmol/L) |
|---|---:|---:|---:|
| TSST | **+13.9** | +18.3 | **+7.5** |
| TEEB | +9.5 | **+30.9** | −2.2 |
| REST | +6.1 | +12.3 | −2.3 |

Two points matter here:

- **Stress was present during recording.** The BP rise was measured *at the time of the VSA1 recording*, so participants were physiologically stressed while reading.
- **The arms differ in the intended way.** TSST produces the cortisol response; TEEB produces the largest heart-rate rise without cortisol.

---

## 4. Main results

### 4.1 Primary outcome: mean F0 (semitones)

| Contrast | Estimate [95% CI] | p | 90% CI (TOST) | Equivalent within ±0.5 st? |
|---|---|---:|---|---|
| **H1:** TSST − REST | −0.12 [−0.40, +0.17] | .41 | [−0.36, +0.12] | **Yes** (p_TOST = .005) |
| **H2a:** TSST − TEEB | −0.17 [−0.46, +0.12] | .25 | [−0.41, +0.07] | **Yes** (p_TOST = .013) |
| TEEB − REST | +0.05 [−0.24, +0.34] | .73 | — | — |

Raw mean Δ (SD): TSST −0.04 (0.61), TEEB +0.14 (0.49), REST +0.06 (0.72).

### 4.2 Secondary outcomes (Holm-corrected)

| Outcome | H1: TSST − REST | H2a: TSST − TEEB |
|---|---|---|
| F0 range (st) | +0.01 [−0.38, +0.41], p = .95 | +0.18, p = .39 |
| CPPS (dB) | +0.09 [−0.12, +0.30], p = .41 | −0.02, p = .88 |
| Reading time (s)* | +1.9 [−1.3, +5.1], p = .24 | +0.8, p = .61 |

\* Affected by the data issue in Section 6.

### 4.3 Arousal-adjusted models (H2b)

| Model | H1: TSST − REST (F0) |
|---|---|
| Adding ΔSBP | −0.13 [−0.43, +0.17], p = .39 |
| HR subset (n = 66), adding ΔHR | −0.30 [−0.73, +0.12], p = .16 |

Adjusting for arousal does not reveal a masked effect.

### 4.4 Within-person coupling (H3)

Linear mixed model over all recordings: 113 participants, 550 recordings.

- **SBP.** F0 does not track within-person SBP: +0.0014 st per mmHg, p = .59. The TSST rise of 14 mmHg would therefore predict only +0.02 st.
- **Cortisol.** F0 does not track within-person log-cortisol: p = .20.
- **Other outcomes.** No coupling for F0 range, CPPS or reading time either.

---

## 5. Why this is a strong negative

1. **The stressor demonstrably worked, at the right moment.** Cortisol rose by +7.5 nmol/L, and SBP rose by +14 mmHg *during* the VSA1 recording. A null cannot be blamed on a failed manipulation or on recording "after the stress was over".

2. **Equivalence, not just non-significance.** The 90% CI for TSST − REST is [−0.36, +0.12] st. An F0 increase larger than about a tenth of a semitone is ruled out. The point estimate even goes in the opposite direction.

3. **High measurement precision.** Three numbers show that noise is not hiding an effect:
   - Within-person F0 is extremely stable: the baseline–post correlation is 0.993.
   - The change score is reliably measured: the correlation of ΔF0 between the two simultaneous microphone channels is 0.985.
   - Residual SD of ΔF0 is ≈ 0.63 st, so the design had 80% power for effects of ≈ 0.4 st (d ≈ 0.65), while the CI excludes increases above 0.12 st.

4. **Robust to every analytic choice.** Nine sensitivity analyses all agree:
   - variants: HC3 robust SE, Huber robust regression, baseline-only covariates, exclusion of flagged participants, complete-data subset, timestamp-verified subset, left channel only, right channel only;
   - H1 estimates range from −0.05 to −0.16 st, all p ≥ .32;
   - H2a estimates range from −0.13 to −0.20 st, all p ≥ .19.

5. **Convergent nulls across levels of analysis.** The following all show no stress-related change:
   - between-group change (H1, H2a);
   - arousal-adjusted models (H2b);
   - within-person physiological coupling (H3);
   - secondary voice-quality and prosody outcomes;
   - all exploratory features after FDR correction (minimum q = 0.21 for Praat features, 0.50 for eGeMAPS).

6. **Consistent with earlier project results.** Experiments D1–D5 (deep and classical classifiers) failed to separate TSST from controls. The present analysis explains why: at the group level there is no vocal signal to learn. The failure was not a modelling problem.

---

## 6. Limitations and open issues

- **Data issue (pending).** One or more TSST VSA0 recordings appear abnormally long: TSST mean baseline reading time is 84 s vs ~44 s in other arms, and SD of Δ = 237 s. This contaminates reading-time results and that participant's VSA0 features.
  - F0 conclusions are unaffected in the robust regression (−0.05 st, p = .72).
  - Fix: exclude recordings < 20 s or > 70 s (a duration-only rule) and rerun.
- **Task.** The speech is standardized reading, not spontaneous speech. Most TSST voice studies analyse the TSST speech itself.
- **Timing.** VSA1 is recorded ~1–3 min after the stressor, not during it. Physiological arousal was still elevated at that point.
- **Equivalence bound.** The ±0.5 st bound needs justification from published TSST F0 effect sizes.
- **Not pre-registered.** The analysis plan was fixed and dated before the results were seen.
- **Uncorrected isolated effects.**
  - TSST − REST change at VSA4: −0.30 st, p = .027. This is 1 of 8 trajectory tests and goes in the opposite direction.
  - TEEB vs TSST tempo cluster (see Section 7).

---

## 7. Exploratory lead (hypothesis-generating only)

After cycling (TEEB), participants read with **lower speech rate, more pausing, less phonation time and higher intensity** than after the TSST.

- Uncorrected p = .03–.04; FDR q = 0.21.
- The pattern is consistent with **respiratory load after exercise** affecting speech breathing, rather than stress per se.
- It needs an independent test.

---

## 8. Interpretation

Vocal changes reported under the TSST may depend on the **speaking situation** (being evaluated, speaking spontaneously) rather than reflecting a **persisting physiological stress state**.

In this design, a strong ongoing cardiovascular and endocrine response did not carry over into read speech. This is a relevant boundary condition for voice-based stress monitoring.

---

## 9. Next steps

1. Inspect and fix the abnormally long recordings; add the duration rule; rerun Step 1b.
2. Collect published TSST F0 effect sizes to justify the equivalence bound.
3. Optional: test the respiratory hypothesis for TEEB with breath-pause measures.

**Files:** `results/a03_analysis_1b_v1/` (PUBLIC: report, summary JSON, exploratory CSV, trajectory figure).
