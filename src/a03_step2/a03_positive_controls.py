#!/usr/bin/env python3
"""
A03 Step 2b: what can the acoustic features discriminate?  (positive controls + final contrasts)

Feature sets: handcrafted Praat set, eGeMAPS (88), optional audEERING wav2vec2 outputs
(arousal / dominance / valence) and its 1024-d embedding.

Fixed rules:
  * recordings shorter than 20 s or longer than 70 s are excluded (duration only, outcome-blind)
  * features = mean of the L and R channel values
  * change scores: VSA1 - VSA0 (and VSA4 - VSA0 for the late-session control)
  * classifier: StandardScaler + L2 logistic regression, C = 0.1, no tuning;
    participant-level 5-fold CV, repeated; permutation test on the labels

Analyses
  1. Final group contrasts (ANCOVA on change) for the main outcomes and the w2v2 scores
  2. Univariate tables, every handcrafted feature, BH-FDR:
       exercise (TEEB-REST), stress (TSST-REST), stress vs exercise (TSST-TEEB),
       practice (VSA1 vs VSA0 within REST), late session (VSA4 vs VSA0, all), sex, recording format
  3. Multivariate discrimination (AUC, permutation p) and speaker identification
Outputs: PUBLIC files contain group-level results only.
"""
import argparse, json, re, shutil, tempfile, warnings, zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from joblib import Parallel, delayed
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.multitest import multipletests

warnings.filterwarnings("ignore")
DUR_MIN, DUR_MAX = 20.0, 70.0
MAIN = ["f0_mean_st", "f0_range_st", "cpps_db", "speech_span_s"]
W2V2 = ["w2v2_arousal", "w2v2_dominance", "w2v2_valence"]
PRAAT_SET = ["f0_mean_st", "f0_median_st", "f0_sd_st", "f0_p10_st", "f0_p90_st", "f0_range_st",
             "jitter_local", "jitter_rap", "shimmer_local", "shimmer_apq3", "hnr_mean_db", "cpps_db",
             "speech_span_s", "phonation_time_s", "n_pauses", "pause_total_s", "pause_mean_s", "pause_ratio",
             "pauses_per_min", "intensity_mean_db_rel", "intensity_sd_db", "speech_rate_syl_s",
             "articulation_rate_syl_s", "voiced_frac_of_phonation"]
KEYS = ["pid", "date", "wav_rank"]
COV = ["female", "start_h", "sr96"]
import os
N_REPEATS, N_PERM, PERM_REPEATS, C_REG = 20, int(os.environ.get("A03_NPERM", 300)), 3, 0.1


def norm_pid(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    d = re.sub(r"\D", "", str(x))
    return (d.lstrip("0") or "0") if d else None


def load_spss(path, tmp):
    import pyreadstat
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            sav = [n for n in z.namelist() if n.lower().endswith(".sav")][0]
            z.extract(sav, tmp); path = Path(tmp) / sav
    want = ["participant_id", "A03", "a03_type", "Geschlecht_codiert", "Alter", "UhrzeitErhebungsstart"]
    _, meta = pyreadstat.read_sav(str(path), metadataonly=True)
    df, _ = pyreadstat.read_sav(str(path), usecols=[c for c in want if c in meta.column_names])
    df = df[df["A03"] == 1].copy()
    df["pid"] = df["participant_id"].map(norm_pid)
    df["group"] = df["a03_type"].map({1: "TSST", 2: "TEEB", 3: "REST"})
    df["female"] = df["Geschlecht_codiert"]
    df["start_h"] = df["UhrzeitErhebungsstart"].map(lambda t: t.hour + t.minute / 60 if hasattr(t, "hour") else np.nan)
    return df.drop_duplicates("pid").set_index("pid")


# ---------------------------------------------------------------- statistics helpers
def ancova(d, y, covars=COV):
    d = d.dropna(subset=[f"d_{y}", f"b_{y}"] + covars)
    res = smf.ols(f"d_{y} ~ C(group, Treatment('REST')) + b_{y} + " + " + ".join(covars), d).fit()
    names = list(res.params.index)
    ts, te = "C(group, Treatment('REST'))[T.TSST]", "C(group, Treatment('REST'))[T.TEEB]"
    sd, crit = float(np.sqrt(res.scale)), stats.t.ppf(0.975, res.df_resid)
    out = dict(n=int(res.nobs))
    for lab, vec in (("TSST_vs_REST", {ts: 1}), ("TSST_vs_TEEB", {ts: 1, te: -1}), ("TEEB_vs_REST", {te: 1})):
        tt = res.t_test(np.array([vec.get(n, 0) for n in names], dtype=float))
        est, se = float(np.squeeze(tt.effect)), float(np.squeeze(tt.sd))
        out[lab] = dict(est=est, ci95=[est - crit * se, est + crit * se], p=float(np.squeeze(tt.pvalue)), d_adj=est / sd)
    return out


def one_sample(x):
    x = pd.Series(x).dropna()
    if len(x) < 5 or x.std() == 0:
        return None
    t, p = stats.ttest_1samp(x, 0)
    return dict(n=int(len(x)), mean=float(x.mean()), dz=float(x.mean() / x.std()), p=float(p))


def two_sample(a, b):
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    if len(a) < 5 or len(b) < 5:
        return None
    t, p = stats.ttest_ind(a, b, equal_var=False)
    sp = np.sqrt(((len(a) - 1) * a.var() + (len(b) - 1) * b.var()) / (len(a) + len(b) - 2))
    return dict(n=int(len(a) + len(b)), mean_diff=float(a.mean() - b.mean()), d=float((a.mean() - b.mean()) / sp) if sp > 0 else np.nan, p=float(p))


def fdr(rows, key="p"):
    ps = [r[key] for r in rows]
    if ps:
        for r, q in zip(rows, multipletests(ps, method="fdr_bh")[1]):
            r["q_fdr"] = float(q)
    return rows


def cv_auc(X, y, groups, seed, paired):
    """Out-of-fold AUC for one CV repeat. paired=True: rows 2i and 2i+1 belong to the same participant."""
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=C_REG, max_iter=2000))
    oof = np.full(len(y), np.nan)
    if paired:
        ug = np.unique(groups)
        perm = np.random.default_rng(seed).permutation(ug)
        fold_of = {g: i % 5 for i, g in enumerate(perm)}
        folds = np.array([fold_of[g] for g in groups])
        splits = [(np.where(folds != k)[0], np.where(folds == k)[0]) for k in range(5)]
    else:
        splits = StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y)
    for tr, te in splits:
        if len(np.unique(y[tr])) < 2:
            continue
        clf.fit(X[tr], y[tr]); oof[te] = clf.decision_function(X[te])
    ok = ~np.isnan(oof)
    return roc_auc_score(y[ok], oof[ok])


def discriminate(X, y, groups=None, paired=False, seed=0):
    """Mean AUC over repeats + permutation p. For paired (order) tasks the sign of each pair is permuted."""
    X, y = np.asarray(X, float), np.asarray(y, int)
    keep = ~np.isnan(X).any(axis=1)
    X, y = X[keep], y[keep]
    groups = np.asarray(groups)[keep] if groups is not None else np.arange(len(y))
    if len(np.unique(y)) < 2 or min(np.bincount(y)) < 8:
        return None
    obs = float(np.mean([cv_auc(X, y, groups, seed + r, paired) for r in range(N_REPEATS)]))

    def one_perm(i):
        rng = np.random.default_rng(10_000 + i)
        if paired:   # flip the sign of whole pairs (X = [d; -d])
            Xp = X.copy()
            for g in np.unique(groups):
                if rng.random() < 0.5:
                    Xp[groups == g] *= -1
            yp = y
        else:
            Xp, yp = X, rng.permutation(y)
        return float(np.mean([cv_auc(Xp, yp, groups, 500 + i * 7 + r, paired) for r in range(PERM_REPEATS)]))
    null = np.array(Parallel(n_jobs=-2)(delayed(one_perm)(i) for i in range(N_PERM)))
    return dict(n=int(len(y) if not paired else len(y) // 2), n_features=int(X.shape[1]), auc=obs,
                perm_p=float((1 + (null >= obs).sum()) / (1 + N_PERM)),
                null_auc_95pct=float(np.percentile(null, 95)))


def speaker_id(A, B):
    """Rank-1 identification: each participant's VSA1 vector -> nearest VSA0 vector (z-scored, Euclidean)."""
    j = A.index.intersection(B.index)
    A, B = A.loc[j].dropna(), B.loc[j].dropna()
    j = A.index.intersection(B.index)
    if len(j) < 20:
        return None
    Z = StandardScaler().fit(pd.concat([A.loc[j], B.loc[j]]).values)
    a, b = Z.transform(A.loc[j].values), Z.transform(B.loc[j].values)
    dist = ((b[:, None, :] - a[None, :, :]) ** 2).sum(-1)
    rank = (dist < np.diag(dist)[:, None]).sum(1)
    return dict(n_speakers=int(len(j)), rank1_accuracy=float((rank == 0).mean()), top5_accuracy=float((rank < 5).mean()),
                chance=float(1 / len(j)))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--spss", required=True)
    ap.add_argument("--w2v2-dir", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=out)
    spss = load_spss(a.spss, tmp)

    f = pd.read_csv(a.features, dtype={"pid": str, "date": str})
    f["pid"] = f.pid.map(norm_pid)
    # eGeMAPS names contain dots (e.g. ...From27.5Hz...), which break model formulas -> sanitize
    f = f.rename(columns={c: re.sub(r"\W", "_", c) for c in f.columns if c.startswith("egemaps_")})
    eg = [c for c in f.columns if c.startswith("egemaps_")]
    praat = [c for c in PRAAT_SET if c in f.columns]
    num = praat + eg
    avg = f.groupby(KEYS)[num + ["duration_total_s"]].mean().reset_index()
    avg = avg.merge(f.groupby(KEYS).agg(wav_index=("wav_index", "first"), orig_sr=("orig_sr", "first")).reset_index(), on=KEYS)

    emb_cols = []
    if a.w2v2_dir and (Path(a.w2v2_dir) / "PRIVATE_w2v2_long.csv").exists():
        w = pd.read_csv(Path(a.w2v2_dir) / "PRIVATE_w2v2_long.csv", dtype={"pid": str, "date": str})
        w["pid"] = w.pid.map(norm_pid)
        npz = Path(a.w2v2_dir) / "PRIVATE_w2v2_embeddings.npz"
        if npz.exists():
            E = np.load(npz)["emb"]
            if len(E) == len(w):
                emb_cols = [f"emb_{i}" for i in range(E.shape[1])]
                w = pd.concat([w, pd.DataFrame(E, columns=emb_cols, index=w.index)], axis=1)
        avg = avg.merge(w.groupby(KEYS)[W2V2 + emb_cols].mean().reset_index(), on=KEYS, how="left")
    w2 = [c for c in W2V2 if c in avg.columns]
    allfeat = num + w2 + emb_cols

    # ---- duration rule, one folder per participant, time index
    n_before = len(avg)
    bad = (avg.duration_total_s < DUR_MIN) | (avg.duration_total_s > DUR_MAX)
    dur_excl = dict(n_recordings_before=int(n_before), n_excluded=int(bad.sum()),
                    excluded_too_long=int((avg.duration_total_s > DUR_MAX).sum()),
                    excluded_too_short=int((avg.duration_total_s < DUR_MIN).sum()))
    nfiles = avg.groupby(["pid", "date"]).size().rename("n_files").reset_index()
    avg = avg.merge(nfiles.sort_values("n_files", ascending=False).drop_duplicates("pid"), on=["pid", "date"])
    avg["time"] = np.where(avg.n_files == 5, avg.wav_rank, avg.wav_index.where(avg.wav_index.between(0, 4)))
    dur_excl["excluded_by_time"] = {f"VSA{int(k)}": int(v) for k, v in avg[bad.reindex(avg.index, fill_value=False)].time.value_counts().items()} if bad.any() else {}
    avg = avg[~((avg.duration_total_s < DUR_MIN) | (avg.duration_total_s > DUR_MAX))].dropna(subset=["time"])
    avg["time"] = avg.time.astype(int)
    avg = avg[avg.pid.isin(spss.index)]
    avg = avg.drop_duplicates(["pid", "time"])

    wide = {t: avg[avg.time == t].set_index("pid") for t in range(5)}
    pids = sorted(set(wide[0].index))
    P = pd.DataFrame(index=pids).join(spss[["group", "female", "start_h"]])
    P["sr96"] = (wide[0].orig_sr.reindex(P.index) == 96000).astype(int)
    D1 = (wide[1][allfeat].reindex(P.index) - wide[0][allfeat].reindex(P.index))
    D4 = (wide[4][allfeat].reindex(P.index) - wide[0][allfeat].reindex(P.index))
    B = wide[0][allfeat].reindex(P.index)
    d = P.copy()
    for c in num + w2:
        d[f"b_{c}"], d[f"d_{c}"] = B[c], D1[c]
    d.to_csv(out / "PRIVATE_change_table_step2.csv")
    has1 = D1[MAIN[0]].notna()
    res = dict(settings=dict(duration_rule_s=[DUR_MIN, DUR_MAX], classifier=f"StandardScaler + L2 logistic regression (C={C_REG})",
                             cv=f"5-fold participant-level, {N_REPEATS} repeats", permutations=N_PERM),
               duration_exclusions=dur_excl,
               n_with_VSA0=P.group.value_counts().to_dict(),
               n_with_VSA0_and_VSA1=P[has1].group.value_counts().to_dict(),
               w2v2_available=bool(w2), w2v2_embedding_available=bool(emb_cols))

    # ---- 1. final contrasts
    res["final_contrasts_ancova"] = {y: ancova(d, y) for y in MAIN + w2}
    res["raw_change_by_group"] = {y: {g: dict(n=int(x[f"d_{y}"].notna().sum()), mean=float(x[f"d_{y}"].mean()), sd=float(x[f"d_{y}"].std()))
                                      for g, x in d.groupby("group")} for y in MAIN + w2}

    # ---- 2. univariate tables
    uni = []
    def add(control, fam, feat, r, effect_key):
        if r:
            uni.append(dict(control=control, family=fam, feature=feat, n=r["n"], effect=r[effect_key],
                            raw=r.get("est", r.get("mean", r.get("mean_diff"))), p=r["p"]))
    for fam, cols in (("praat", praat), ("egemaps", eg), ("w2v2", w2)):
        for c in cols:
            try:
                m = ancova(d, c)
                for lab, name in (("TEEB_vs_REST", "exercise: TEEB-REST (ANCOVA d_adj)"), ("TSST_vs_REST", "stress: TSST-REST (ANCOVA d_adj)"),
                                  ("TSST_vs_TEEB", "stress vs exercise: TSST-TEEB (ANCOVA d_adj)")):
                    add(name, fam, c, dict(n=m["n"], **m[lab]), "d_adj")
            except Exception:
                pass
            add("practice: VSA1-VSA0 within REST (dz)", fam, c, one_sample(D1.loc[P.group == "REST", c]), "dz")
            add("pre-post: VSA1-VSA0 within TEEB (dz)", fam, c, one_sample(D1.loc[P.group == "TEEB", c]), "dz")
            add("pre-post: VSA1-VSA0 within TSST (dz)", fam, c, one_sample(D1.loc[P.group == "TSST", c]), "dz")
            add("late session: VSA4-VSA0, all groups (dz)", fam, c, one_sample(D4[c]), "dz")
            add("sex: female-male at VSA0 (d)", fam, c, two_sample(B.loc[P.female == 1, c], B.loc[P.female == 0, c]), "d")
            add("format: 96k-44.1k at VSA0 (d)", fam, c, two_sample(B.loc[P.sr96 == 1, c], B.loc[P.sr96 == 0, c]), "d")
    U = pd.DataFrame(uni)
    U["q_fdr"] = np.nan
    for _, idx in U.groupby(["control", "family"]).groups.items():
        U.loc[idx, "q_fdr"] = multipletests(U.loc[idx, "p"], method="fdr_bh")[1]
    U.sort_values(["control", "family", "p"]).to_csv(out / "univariate_all_PUBLIC.csv", index=False)
    summ = {}
    for (ctl, fam), x in U.groupby(["control", "family"]):
        top = x.sort_values("p").head(5)
        summ.setdefault(ctl, {})[fam] = dict(n_features=int(len(x)), n_q_lt_05=int((x.q_fdr < .05).sum()),
                                             n_p_lt_05=int((x.p < .05).sum()), median_abs_effect=float(x.effect.abs().median()),
                                             top5=[dict(feature=r.feature, effect=float(r.effect), p=float(r.p), q=float(r.q_fdr)) for r in top.itertuples()])
    res["univariate_summary"] = summ

    # ---- 3. multivariate discrimination
    sets = {"praat": praat, "egemaps": eg}
    if w2: sets["w2v2_scores"] = w2
    if emb_cols: sets["w2v2_embedding"] = emb_cols
    disc = {}
    def grp_task(name, g1, g0, M):
        m = P.group.isin([g1, g0])
        for s, cols in sets.items():
            disc.setdefault(name, {})[s] = discriminate(M.loc[m, cols].values, (P.group[m] == g1).astype(int).values)
    grp_task("stress: TSST vs REST (from change VSA1-VSA0)", "TSST", "REST", D1)
    grp_task("exercise: TEEB vs REST (from change VSA1-VSA0)", "TEEB", "REST", D1)
    grp_task("stress vs exercise: TSST vs TEEB (from change VSA1-VSA0)", "TSST", "TEEB", D1)
    grp_task("group at baseline: TSST vs REST (VSA0 only, should be chance)", "TSST", "REST", B)
    for s, cols in sets.items():
        disc.setdefault("sex (VSA0)", {})[s] = discriminate(B[cols].values, P.female.fillna(-1).astype(int).clip(0).values) if P.female.notna().all() else None
        disc.setdefault("recording format 96k vs 44.1k (VSA0)", {})[s] = discriminate(B[cols].values, P.sr96.values)
        for name, M, mask in (("recording order: VSA0 vs VSA1, REST only (practice)", D1, P.group == "REST"),
                              ("recording order: VSA0 vs VSA1, TEEB only", D1, P.group == "TEEB"),
                              ("recording order: VSA0 vs VSA1, TSST only", D1, P.group == "TSST"),
                              ("recording order: VSA0 vs VSA4, all groups (late session)", D4, P.group.notna())):
            X = M.loc[mask, cols].dropna()
            if len(X) < 16:
                disc.setdefault(name, {})[s] = None; continue
            Xp = np.empty((2 * len(X), X.shape[1])); Xp[0::2], Xp[1::2] = X.values, -X.values
            yp = np.tile([1, 0], len(X)); gp = np.repeat(np.arange(len(X)), 2)
            disc.setdefault(name, {})[s] = discriminate(Xp, yp, gp, paired=True)
        disc.setdefault("speaker identification: VSA1 -> VSA0 (rank-1 accuracy)", {})[s] = speaker_id(
            wide[0][cols].reindex(P.index), wide[1][cols].reindex(P.index))
    res["multivariate_discrimination"] = disc

    # ---- figures
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        tasks = [t for t in disc if "speaker" not in t]
        fig, ax = plt.subplots(figsize=(11, 0.55 * len(tasks) + 2))
        cols = {"praat": "#2471a3", "egemaps": "#7f8c8d", "w2v2_scores": "#c0392b", "w2v2_embedding": "#d68910"}
        h = 0.8 / len(sets)
        for i, s in enumerate(sets):
            vals = [(disc[t].get(s) or {}).get("auc", np.nan) for t in tasks]
            sig = [(disc[t].get(s) or {}).get("perm_p", 1) < .05 for t in tasks]
            y = np.arange(len(tasks)) + i * h
            ax.barh(y, vals, height=h, color=cols.get(s, "k"), label=s)
            for yy, v, sg in zip(y, vals, sig):
                if sg and not np.isnan(v):
                    ax.text(v + 0.01, yy, "*", va="center")
        ax.axvline(0.5, color="k", lw=0.8, ls="--")
        ax.set_yticks(np.arange(len(tasks)) + 0.4 - h / 2); ax.set_yticklabels(tasks, fontsize=8)
        ax.invert_yaxis(); ax.set_xlim(0.3, 1.02); ax.set_xlabel("cross-validated AUC   (* permutation p < .05)")
        ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.0, 1.0)); fig.tight_layout()
        fig.savefig(out / "discrimination_auc_PUBLIC.png", dpi=150); plt.close(fig)

        x = U[(U.family == "praat") & U.control.str.startswith(("exercise", "stress: "))]
        piv = x.pivot(index="feature", columns="control", values="effect").reindex(praat)
        fig, ax = plt.subplots(figsize=(8, 0.33 * len(praat) + 1.5))
        yy = np.arange(len(piv))
        for k, (ctl, col) in enumerate(zip(sorted(piv.columns), ["#2471a3", "#c0392b"])):
            ax.barh(yy + (k - 0.5) * 0.38, piv[ctl], height=0.38, color=col, label=ctl.split(" (")[0])
        ax.axvline(0, color="k", lw=0.8); ax.set_yticks(yy); ax.set_yticklabels(piv.index, fontsize=8); ax.invert_yaxis()
        ax.set_xlabel("standardized group difference in change VSA1 − VSA0 (d_adj vs REST)"); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(out / "exercise_vs_stress_effects_PUBLIC.png", dpi=150); plt.close(fig)
    except Exception as ex:
        print(f"[warn] figure failed: {ex}")

    # ---- write
    def clean(o):
        if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [clean(v) for v in o]
        if isinstance(o, np.integer): return int(o)
        if isinstance(o, (np.floating, float)): return None if np.isnan(o) else round(float(o), 5)
        return o
    res = clean(res)
    (out / "positive_controls_summary_PUBLIC.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))

    fm = lambda c: f"{c['est']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}], p = {c['p']:.4f}, d = {c['d_adj']:+.2f}"
    md = ["# A03 Step 2 — positive controls and final contrasts (PUBLIC, group level only)", "",
          f"Duration rule {DUR_MIN:.0f}–{DUR_MAX:.0f} s: {res['duration_exclusions']}",
          f"Participants with VSA0 + VSA1: {res['n_with_VSA0_and_VSA1']}", "",
          "## 1. Final group contrasts (ANCOVA on change VSA1 − VSA0)", "",
          "| outcome | TSST − REST | TSST − TEEB | TEEB − REST |", "|---|---|---|---|"]
    for y, m in res["final_contrasts_ancova"].items():
        md.append(f"| {y} | {fm(m['TSST_vs_REST'])} | {fm(m['TSST_vs_TEEB'])} | {fm(m['TEEB_vs_REST'])} |")
    md += ["", "## 2. Univariate controls (features with FDR q < .05 / total; median |effect|; strongest feature)", "",
           "| control | family | q < .05 | median abs effect | strongest feature (effect, q) |", "|---|---|---|---|---|"]
    for ctl, fams in res["univariate_summary"].items():
        for fam, s in fams.items():
            t = s["top5"][0] if s["top5"] else None
            md.append(f"| {ctl} | {fam} | {s['n_q_lt_05']} / {s['n_features']} | {s['median_abs_effect']:.2f} | "
                      + (f"{t['feature']} ({t['effect']:+.2f}, q = {t['q']:.4f})" if t else "–") + " |")
    md += ["", "## 3. Multivariate discrimination (cross-validated AUC, permutation p)", "",
           "| task | " + " | ".join(sets) + " |", "|---|" + "---|" * len(sets)]
    for t, v in res["multivariate_discrimination"].items():
        cells = []
        for s in sets:
            r = v.get(s)
            if not r: cells.append("–")
            elif "auc" in r: cells.append(f"{r['auc']:.3f} (p = {r['perm_p']:.3f}, n = {r['n']})")
            else: cells.append(f"rank-1 {r['rank1_accuracy']:.2f}, top-5 {r['top5_accuracy']:.2f} (chance {r['chance']:.3f}, n = {r['n_speakers']})")
        md.append(f"| {t} | " + " | ".join(cells) + " |")
    md += ["", "Figures: discrimination_auc_PUBLIC.png, exercise_vs_stress_effects_PUBLIC.png", "Full univariate table: univariate_all_PUBLIC.csv"]
    (out / "positive_controls_report_PUBLIC.md").write_text("\n".join(md) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[done] -> {out}")


if __name__ == "__main__":
    main()
