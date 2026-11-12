#!/usr/bin/env python3
"""
A03 Step 1b: group analysis of vocal change (analysis plan = README section 8).

Inputs (on the research disk):
  results/a03_features_v1/PRIVATE_features_long.csv      (Step 1a)
  results/a03_protocol_audit_v2/PRIVATE_vsa_table.csv     (Step 0, optional: timing subset)
  results/a03_protocol_audit_v2/PRIVATE_issues.csv        (Step 0, optional: exclusion flags)
  results/a03_protocol_audit_v2/PRIVATE_protocol_events.csv (optional: TSST panel notes)
  SPSS .sav/.zip                                          (group, sex, start time, THC, SBP, HR, cortisol)

Analyses:
  H1   ANCOVA  delta ~ group + baseline + sex + start time + format, contrast TSST-REST
  H2a  same model, contrast TSST-TEEB (+ TOST, bounds +-0.5 st for the primary outcome)
  H2b  + delta SBP (and delta HR in the ECG subset)
  H3   LMM over recordings: y ~ SBP_within + logCort_within + between parts + time + group, (1|pid)
  Sensitivity, exploratory (all features, eGeMAPS, group x time trajectories), figures.

Outputs: PUBLIC = group-level only; PRIVATE = participant table.
"""
import argparse, json, re, shutil, sys, tempfile, warnings, zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.multitest import multipletests

warnings.filterwarnings("ignore")

PRIMARY = "f0_mean_st"
SECONDARY = ["f0_range_st", "cpps_db", "speech_span_s"]
SESOI = 0.5                       # TOST bound for the primary outcome (semitones)
CORT_FACTOR = 2.76                # ug/L -> nmol/L
CORT_FOR_RANK = {0: 1, 1: 3, 2: 4, 3: 5, 4: 6}   # recording rank -> cortisol sample
META = {"pid", "group", "date", "wav_index", "wav_rank", "channel", "wav_relpath", "file_tier",
        "orig_sr", "orig_channels", "f0_floor_hz", "f0_ceiling_hz", "duration_total_s", "snr_proxy_db"}


def norm_pid(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    d = re.sub(r"\D", "", str(x))
    return (d.lstrip("0") or "0") if d else None


def hours(t):
    return t.hour + t.minute / 60 if hasattr(t, "hour") else np.nan


# ---------------------------------------------------------------- data loading
def load_spss(path, tmp):
    import pyreadstat
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            sav = [n for n in z.namelist() if n.lower().endswith(".sav")][0]
            z.extract(sav, tmp); path = Path(tmp) / sav
    want = (["participant_id", "A03", "a03_type", "Geschlecht_codiert", "Alter", "UhrzeitErhebungsstart",
             "a03_drug_test_pos_neg", "ECG_phase_1", "ECG_phase_2"]
            + [f"Cortisol_Mittelwert_{i}" for i in range(1, 7)] + [f"RR_sys_t{i}" for i in range(1, 6)])
    _, meta = pyreadstat.read_sav(str(path), metadataonly=True)
    df, _ = pyreadstat.read_sav(str(path), usecols=[c for c in want if c in meta.column_names])
    df = df[df["A03"] == 1].copy()
    df["pid"] = df["participant_id"].map(norm_pid)
    df["group"] = df["a03_type"].map({1: "TSST", 2: "TEEB", 3: "REST"})
    df["female"] = df["Geschlecht_codiert"]
    df["start_h"] = df["UhrzeitErhebungsstart"].map(hours)
    df["thc_pos"] = (df.get("a03_drug_test_pos_neg") == 2).astype(int)
    for i in range(1, 7):
        c = f"Cortisol_Mittelwert_{i}"
        df[f"cort{i}_nmol"] = df[c] * CORT_FACTOR
        df[f"lcort{i}"] = np.log(df[f"cort{i}_nmol"].where(df[f"cort{i}_nmol"] > 0))
    df = df.drop_duplicates("pid").set_index("pid")
    return df


def load_features(path):
    f = pd.read_csv(path, dtype={"pid": str, "date": str})
    f["pid"] = f["pid"].map(norm_pid)
    # eGeMAPS names contain dots (e.g. ...From27.5Hz...), which break model formulas -> sanitize
    f = f.rename(columns={c: re.sub(r"\W", "_", c) for c in f.columns if c.startswith("egemaps_")})
    feats = [c for c in f.columns if c not in META and pd.api.types.is_numeric_dtype(f[c])]
    keys = ["pid", "date", "wav_rank"]
    meta = f.groupby(keys).agg(wav_index=("wav_index", "first"), orig_sr=("orig_sr", "first")).reset_index()
    by_ch = {ch: f[f.channel == ch].set_index(keys)[feats] for ch in ("L", "R")}
    avg = f.groupby(keys)[feats].mean().reset_index().merge(meta, on=keys)
    # if a pid appears in >1 folder, keep the folder with most files
    nf = avg.groupby(["pid", "date"]).size().rename("n_files").reset_index()
    keep = nf.sort_values("n_files", ascending=False).drop_duplicates("pid")
    avg = avg.merge(keep, on=["pid", "date"])
    return avg, by_ch, feats


def pick_pair(rec):
    """rows for VSA0 and VSA1 of one participant: rank if 5 files, else wav_index 0 and 1."""
    if len(rec) == 5:
        r0, r1 = rec[rec.wav_rank == 0], rec[rec.wav_rank == 1]
    else:
        r0, r1 = rec[rec.wav_index == 0], rec[rec.wav_index == 1]
    return (r0.iloc[0], r1.iloc[0]) if len(r0) and len(r1) else (None, None)


def time_rank(rec):
    """map rows to VSA time 0-4: rank if 5 files, else wav_index if it lies in 0-4."""
    rec = rec.copy()
    rec["time"] = rec.wav_rank if len(rec) == 5 else rec.wav_index.where(rec.wav_index.between(0, 4))
    return rec.dropna(subset=["time"])


# ---------------------------------------------------------------- models
def ancova(d, y, covars, robust=False, rlm=False):
    d = d.dropna(subset=[f"d_{y}", f"b_{y}"] + [c for c in covars])
    rhs = " + ".join(["C(group, Treatment('REST'))", f"b_{y}"] + covars)
    form = f"d_{y} ~ {rhs}"
    if rlm:
        res = smf.rlm(form, d, M=sm.robust.norms.HuberT()).fit()
    else:
        res = smf.ols(form, d).fit(cov_type="HC3" if robust else "nonrobust")
    names = list(res.params.index)
    ts, te = "C(group, Treatment('REST'))[T.TSST]", "C(group, Treatment('REST'))[T.TEEB]"
    out = dict(n=int(res.nobs), n_by_group=d.group.value_counts().to_dict())
    resid_sd = float(np.sqrt(res.scale)) if not rlm else float(np.std(res.resid, ddof=len(names)))
    df_r = float(res.df_resid)
    for lab, vec in (("TSST_vs_REST", {ts: 1}), ("TSST_vs_TEEB", {ts: 1, te: -1}), ("TEEB_vs_REST", {te: 1})):
        L = np.array([vec.get(n, 0) for n in names], dtype=float)
        tt = res.t_test(L)
        est, se = float(np.squeeze(tt.effect)), float(np.squeeze(tt.sd))
        p = float(np.squeeze(tt.pvalue))
        crit = stats.t.ppf(0.975, df_r) if not rlm else 1.96
        out[lab] = dict(est=est, se=se, ci95=[est - crit * se, est + crit * se], p=p,
                        d_adj=est / resid_sd if resid_sd > 0 else np.nan)
    out["resid_sd"] = resid_sd
    out["df_resid"] = df_r
    out["_res"] = res
    return out


def tost(c, bound, df_r):
    est, se = c["est"], c["se"]
    p_low = 1 - stats.t.cdf((est + bound) / se, df_r)
    p_up = stats.t.cdf((est - bound) / se, df_r)
    crit = stats.t.ppf(0.95, df_r)
    return dict(bound=bound, p_tost=float(max(p_low, p_up)), ci90=[est - crit * se, est + crit * se],
                equivalent=bool(max(p_low, p_up) < 0.05))


def hedges_g(a, b):
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    if len(a) < 2 or len(b) < 2:
        return np.nan
    sp = np.sqrt(((len(a) - 1) * a.var() + (len(b) - 1) * b.var()) / (len(a) + len(b) - 2))
    j = 1 - 3 / (4 * (len(a) + len(b)) - 9)
    return float((a.mean() - b.mean()) / sp * j)


def fmt(c):
    return f"{c['est']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}], p = {c['p']:.4f}, d_adj = {c['d_adj']:+.2f}"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--spss", required=True)
    ap.add_argument("--audit-dir", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=out)

    spss = load_spss(a.spss, tmp)
    avg, by_ch, feats = load_features(a.features)
    eg = [c for c in feats if c.startswith("egemaps_")]
    praat = [c for c in feats if not c.startswith("egemaps_")]
    flow = {"features_participants": int(avg.pid.nunique())}

    # ---- flags from audit (optional)
    flags = pd.DataFrame(index=sorted(avg.pid.unique()))
    flags["suspect_label"] = 0; flags["panel_incomplete"] = 0; flags["vsa01_time_ok"] = np.nan
    if a.audit_dir:
        ad = Path(a.audit_dir)
        if (ad / "PRIVATE_issues.csv").exists():
            iss = pd.read_csv(ad / "PRIVATE_issues.csv", dtype={"pid": str})
            iss["pid"] = iss.pid.map(norm_pid)
            sus = set(iss[iss.issue == "tsst_keywords_in_nonTSST_protocol"].pid)
            flags["suspect_label"] = flags.index.isin(sus).astype(int)
        if (ad / "PRIVATE_protocol_events.csv").exists():
            ev = pd.read_csv(ad / "PRIVATE_protocol_events.csv", dtype={"pid": str})
            ev["pid"] = ev.pid.map(norm_pid)
            txt = ev[ev.group == "TSST"].assign(t=lambda x: x.note.astype(str) + " " + x.value.astype(str))
            pan = set(txt[txt.t.str.contains(r"gremium|nur weiblich|nur männlich|nur ein", case=False, regex=True)].pid)
            flags["panel_incomplete"] = flags.index.isin(pan).astype(int)
        if (ad / "PRIVATE_vsa_table.csv").exists():
            vt = pd.read_csv(ad / "PRIVATE_vsa_table.csv", dtype={"pid": str})
            vt["pid"] = vt.pid.map(norm_pid)
            ok = vt[vt.vsa_order.isin([0, 1])].groupby("pid").clock.apply(lambda s: int(s.notna().sum() == 2))
            flags["vsa01_time_ok"] = ok.reindex(flags.index)
    sr_var = avg.groupby("pid").orig_sr.nunique()
    flags["sr_varies"] = (sr_var.reindex(flags.index) > 1).astype(int)

    # ---- participant-level change table
    rows = []
    for pid, rec in avg.groupby("pid"):
        r0, r1 = pick_pair(rec)
        if r0 is None or pid not in spss.index:
            continue
        s = spss.loc[pid]
        row = dict(pid=pid, group=s.group, female=s.female, age=s.get("Alter"), start_h=s.start_h,
                   thc_pos=s.thc_pos, sr96=int(r0.orig_sr == 96000), n_files=int(len(rec)),
                   d_sbp=s.get("RR_sys_t2") - s.get("RR_sys_t1"),
                   d_hr=s.get("ECG_phase_2") - s.get("ECG_phase_1"),
                   d_cort_T3=s.get("cort3_nmol") - s.get("cort1_nmol"),
                   d_cort_T4=s.get("cort4_nmol") - s.get("cort1_nmol"))
        for f_ in feats:
            row[f"b_{f_}"], row[f"p_{f_}"] = r0[f_], r1[f_]
            row[f"d_{f_}"] = r1[f_] - r0[f_]
        rows.append(row)
    d = pd.DataFrame(rows).set_index("pid").join(flags)
    d = d[d.group.notna()]
    flow["analysable_H1_H2"] = d.group.value_counts().to_dict()
    flow["dropped_no_VSA0_VSA1_or_not_in_spss"] = int(avg.pid.nunique() - len(d))
    d.to_csv(out / "PRIVATE_change_table.csv")

    COV = ["female", "start_h", "sr96"]
    res = dict(flow=flow, settings=dict(primary=PRIMARY, secondary=SECONDARY, sesoi_st=SESOI,
                                        covariates=COV, reference="REST", note="unregistered (exploratory status)"))

    # ---- descriptives
    desc = {}
    for y in [PRIMARY] + SECONDARY:
        desc[y] = {g: dict(n=int(x[f"d_{y}"].notna().sum()), baseline_mean=float(x[f"b_{y}"].mean()),
                           post_mean=float(x[f"p_{y}"].mean()), delta_mean=float(x[f"d_{y}"].mean()),
                           delta_sd=float(x[f"d_{y}"].std()))
                   for g, x in d.groupby("group")}
        desc[y]["hedges_g_delta_TSST_vs_REST"] = hedges_g(d[d.group == "TSST"][f"d_{y}"], d[d.group == "REST"][f"d_{y}"])
        desc[y]["hedges_g_delta_TSST_vs_TEEB"] = hedges_g(d[d.group == "TSST"][f"d_{y}"], d[d.group == "TEEB"][f"d_{y}"])
        desc[y]["r_baseline_post"] = float(d[[f"b_{y}", f"p_{y}"]].corr().iloc[0, 1])
    desc["d_sbp"] = d.groupby("group").d_sbp.agg(["count", "mean", "std"]).to_dict("index")
    desc["d_hr"] = d.groupby("group").d_hr.agg(["count", "mean", "std"]).to_dict("index")
    desc["d_cort_T4_nmol"] = d.groupby("group").d_cort_T4.agg(["count", "mean", "std"]).to_dict("index")
    res["descriptives"] = desc

    # ---- H1 / H2a
    main_res, h1_p, h2_p = {}, [], []
    for y in [PRIMARY] + SECONDARY:
        m = ancova(d, y, COV); m.pop("_res")
        main_res[y] = m
    for y in SECONDARY:
        h1_p.append(main_res[y]["TSST_vs_REST"]["p"]); h2_p.append(main_res[y]["TSST_vs_TEEB"]["p"])
    for lab, ps in (("TSST_vs_REST", h1_p), ("TSST_vs_TEEB", h2_p)):
        adj = multipletests(ps, method="holm")[1]
        for y, p in zip(SECONDARY, adj):
            main_res[y][lab]["p_holm_secondary"] = float(p)
    pm = main_res[PRIMARY]
    pm["TSST_vs_TEEB"]["tost"] = tost(pm["TSST_vs_TEEB"], SESOI, pm["df_resid"])
    pm["TSST_vs_REST"]["tost"] = tost(pm["TSST_vs_REST"], SESOI, pm["df_resid"])
    res["H1_H2a_ancova"] = main_res

    # ---- H2b: + delta SBP ; + delta HR (subset)
    h2b = {}
    for y in [PRIMARY] + SECONDARY:
        m1 = ancova(d, y, COV + ["d_sbp"]); m1.pop("_res")
        sub = d[d.d_hr.notna()]
        m2 = ancova(sub, y, COV); m2.pop("_res")
        m3 = ancova(sub, y, COV + ["d_hr"]); m3.pop("_res")
        h2b[y] = dict(plus_dSBP=m1, hr_subset_without_dHR=m2, hr_subset_plus_dHR=m3)
    res["H2b_arousal_adjusted"] = h2b

    # ---- sensitivity (primary + secondary, H1 and H2a contrasts)
    sens = {}
    excl = (d.suspect_label == 1) | (d.thc_pos == 1) | (d.panel_incomplete == 1) | (d.sr_varies == 1)
    variants = {
        "main": (d, COV, {}),
        "robust_HC3": (d, COV, dict(robust=True)),
        "huber_rlm": (d, COV, dict(rlm=True)),
        "baseline_only_covariate": (d, [], {}),
        "exclude_flagged": (d[~excl], COV, {}),
        "five_files_only": (d[d.n_files == 5], COV, {}),
        "vsa0_vsa1_timestamps_present": (d[d.vsa01_time_ok == 1], COV, {}),
    }
    for y in [PRIMARY] + SECONDARY:
        sens[y] = {}
        for name, (dd, cv, kw) in variants.items():
            try:
                m = ancova(dd, y, cv, **kw); m.pop("_res")
                sens[y][name] = {k: m[k] for k in ("n", "TSST_vs_REST", "TSST_vs_TEEB")}
            except Exception as ex:
                sens[y][name] = f"failed: {ex}"
        for ch in ("L", "R"):
            X = by_ch[ch].reset_index()
            X["pid"] = X.pid.map(norm_pid)
            alt = d.copy()
            for pid in alt.index:
                rec = X[X.pid == pid].merge(avg[avg.pid == pid][["pid", "date", "wav_rank", "wav_index"]],
                                            on=["pid", "date", "wav_rank"])
                r0, r1 = pick_pair(rec.assign(n=len(rec))) if len(rec) else (None, None)
                if r0 is not None:
                    alt.loc[pid, f"b_{y}"], alt.loc[pid, f"d_{y}"] = r0[y], r1[y] - r0[y]
            m = ancova(alt, y, COV); m.pop("_res")
            sens[y][f"channel_{ch}_only"] = {k: m[k] for k in ("n", "TSST_vs_REST", "TSST_vs_TEEB")}
    sens["n_flagged_excluded"] = int(excl.sum())
    sens["flag_counts"] = dict(suspect_label=int(d.suspect_label.sum()), thc_pos=int(d.thc_pos.sum()),
                               panel_incomplete=int(d.panel_incomplete.sum()), sr_varies=int(d.sr_varies.sum()))
    res["sensitivity"] = sens

    # ---- long table (all recordings) for H3 and trajectories
    L = []
    for pid, rec in avg.groupby("pid"):
        if pid not in spss.index:
            continue
        s = spss.loc[pid]
        rec = time_rank(rec)
        for _, r in rec.iterrows():
            t = int(r.time)
            row = dict(pid=pid, group=s.group, female=s.female, start_h=s.start_h, sr96=int(r.orig_sr == 96000),
                       time=t, sbp=s.get(f"RR_sys_t{t + 1}"), lcort=s.get(f"lcort{CORT_FOR_RANK[t]}"),
                       cort_nmol=s.get(f"cort{CORT_FOR_RANK[t]}_nmol"))
            for f_ in [PRIMARY] + SECONDARY:
                row[f_] = r[f_]
            L.append(row)
    L = pd.DataFrame(L)
    L = L[L.group.notna()]
    for v in ("sbp", "lcort"):
        L[f"{v}_b"] = L.groupby("pid")[v].transform("mean")
        L[f"{v}_w"] = L[v] - L[f"{v}_b"]
    h3, traj = {}, {}
    for y in [PRIMARY] + SECONDARY:
        dd = L.dropna(subset=[y, "sbp_w", "lcort_w", "female", "sr96"])
        try:
            m = smf.mixedlm(f"{y} ~ sbp_w + lcort_w + sbp_b + lcort_b + C(time) + C(group, Treatment('REST')) + female + sr96",
                            dd, groups=dd["pid"]).fit(reml=True)
            ci = m.conf_int()
            h3[y] = {k: dict(est=float(m.params[k]), ci95=[float(ci.loc[k, 0]), float(ci.loc[k, 1])], p=float(m.pvalues[k]))
                     for k in ("sbp_w", "lcort_w", "sbp_b", "lcort_b")}
            h3[y]["n_obs"], h3[y]["n_participants"] = int(m.nobs), int(dd.pid.nunique())
        except Exception as ex:
            h3[y] = f"failed: {ex}"
        dd = L.dropna(subset=[y, "female", "start_h", "sr96"])
        try:
            m = smf.mixedlm(f"{y} ~ C(group, Treatment('REST')) * C(time) + female + start_h + sr96",
                            dd, groups=dd["pid"]).fit(reml=True)
            ci = m.conf_int()
            tr = {}
            for k in m.params.index:
                if ":" in k:
                    g = "TSST" if "TSST" in k else "TEEB"
                    t = re.search(r"C\(time\)\[T\.(\d)", k).group(1)
                    tr[f"{g}_minus_REST_change_to_VSA{t}"] = dict(est=float(m.params[k]),
                                                                  ci95=[float(ci.loc[k, 0]), float(ci.loc[k, 1])],
                                                                  p=float(m.pvalues[k]))
            traj[y] = tr
        except Exception as ex:
            traj[y] = f"failed: {ex}"
    res["H3_within_person_coupling"] = h3
    res["exploratory_group_x_time_lmm"] = traj

    # ---- exploratory: every feature (H1/H2a contrasts), BH-FDR within Praat and within eGeMAPS
    rel = {}
    for f_ in feats:
        a_, b_ = by_ch["L"][f_].unstack("wav_rank"), by_ch["R"][f_].unstack("wav_rank")
        if 0 in a_ and 1 in a_ and 0 in b_ and 1 in b_:
            da, db = (a_[1] - a_[0]).dropna(), (b_[1] - b_[0]).dropna()
            j = da.index.intersection(db.index)
            rel[f_] = float(np.corrcoef(da[j], db[j])[0, 1]) if len(j) > 10 and da[j].std() > 0 and db[j].std() > 0 else np.nan
    expl = []
    for fam, cols in (("praat", praat), ("egemaps", eg)):
        for f_ in cols:
            try:
                m = ancova(d, f_, COV); m.pop("_res")
            except Exception:
                continue
            for lab in ("TSST_vs_REST", "TSST_vs_TEEB", "TEEB_vs_REST"):
                c = m[lab]
                expl.append(dict(family=fam, feature=f_, contrast=lab, n=m["n"], est=c["est"],
                                 ci_low=c["ci95"][0], ci_high=c["ci95"][1], p=c["p"], d_adj=c["d_adj"],
                                 reliability_r_delta=rel.get(f_, np.nan)))
    E = pd.DataFrame(expl)
    if len(E):
        E["q_fdr"] = np.nan
        for (fam, lab), idx in E.groupby(["family", "contrast"]).groups.items():
            E.loc[idx, "q_fdr"] = multipletests(E.loc[idx, "p"], method="fdr_bh")[1]
        E["reliable_r_ge_0.70"] = E.reliability_r_delta >= 0.70
        E.sort_values(["family", "contrast", "p"]).to_csv(out / "exploratory_all_features_PUBLIC.csv", index=False)
        res["exploratory_top"] = (E[E.contrast != "TEEB_vs_REST"].sort_values("p").head(15)
                                  [["family", "feature", "contrast", "est", "p", "q_fdr", "d_adj", "reliability_r_delta"]]
                                  .to_dict("records"))

    # ---- figure: group trajectories (change from VSA0), mean +- SE
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        panels = [PRIMARY] + SECONDARY + ["sbp", "cort_nmol"]
        titles = {"f0_mean_st": "F0 mean (st)", "f0_range_st": "F0 range (st)", "cpps_db": "CPPS (dB)",
                  "speech_span_s": "Reading time (s)", "sbp": "Systolic BP (mmHg)", "cort_nmol": "Cortisol (nmol/L)"}
        cols = {"TSST": "#c0392b", "TEEB": "#2471a3", "REST": "#7f8c8d"}
        fig, axes = plt.subplots(2, 3, figsize=(13, 7.5))
        for ax, v in zip(axes.flat, panels):
            X = L.dropna(subset=[v]).copy()
            base = X[X.time == 0].set_index("pid")[v]
            X["chg"] = X[v] - X.pid.map(base)
            for g in ("TSST", "TEEB", "REST"):
                s = X[X.group == g].groupby("time").chg.agg(["mean", "sem", "count"])
                ax.errorbar(s.index + {"TSST": -0.08, "TEEB": 0, "REST": 0.08}[g], s["mean"], yerr=s["sem"],
                            marker="o", capsize=3, color=cols[g], label=f"{g}")
            ax.axhline(0, color="k", lw=0.6)
            ax.set_xticks(range(5)); ax.set_xticklabels([f"VSA{i}" for i in range(5)])
            ax.set_title(f"Δ {titles[v]} from VSA0"); ax.grid(alpha=0.3)
        axes.flat[0].legend()
        fig.tight_layout(); fig.savefig(out / "trajectories_PUBLIC.png", dpi=150); plt.close(fig)
    except Exception as ex:
        print(f"[warn] figure failed: {ex}")

    # ---- write
    def clean(o):
        if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [clean(v) for v in o]
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating, float)): return None if np.isnan(o) else round(float(o), 5)
        return o
    res = clean(res)
    (out / "analysis_1b_summary_PUBLIC.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))

    md = ["# A03 Step 1b — group analysis of vocal change (PUBLIC, group level only)", "",
          "Status: **unregistered analysis**; plan as in README section 8. Reference group = REST.",
          f"Covariates: baseline + {', '.join(COV)}. Contrasts: estimate [95% CI], p, d_adj (estimate / residual SD).", "",
          f"Analysable (VSA0 + VSA1): {flow['analysable_H1_H2']}", "",
          "## Descriptives (raw change VSA1 − VSA0)", "", "| feature | group | n | baseline | post | Δ mean (SD) |", "|---|---|---|---|---|---|"]
    for y in [PRIMARY] + SECONDARY:
        for g in ("TSST", "TEEB", "REST"):
            x = res["descriptives"][y].get(g)
            if x:
                md.append(f"| {y} | {g} | {x['n']} | {x['baseline_mean']:.3f} | {x['post_mean']:.3f} | {x['delta_mean']:+.3f} ({x['delta_sd']:.3f}) |")
    md += ["", "## H1 / H2a (ANCOVA on change)", "", "| feature | TSST − REST (H1) | TSST − TEEB (H2a) | TEEB − REST |", "|---|---|---|---|"]
    for y in [PRIMARY] + SECONDARY:
        m = res["H1_H2a_ancova"][y]
        extra = lambda c: (f"; Holm p = {c['p_holm_secondary']:.4f}" if "p_holm_secondary" in c else "")
        md.append(f"| {y}{' (primary)' if y == PRIMARY else ''} | {fmt(m['TSST_vs_REST'])}{extra(m['TSST_vs_REST'])} | "
                  f"{fmt(m['TSST_vs_TEEB'])}{extra(m['TSST_vs_TEEB'])} | {fmt(m['TEEB_vs_REST'])} |")
    t = res["H1_H2a_ancova"][PRIMARY]["TSST_vs_TEEB"]["tost"]
    md += ["", f"TOST (primary, TSST − TEEB, ±{SESOI} st): 90% CI [{t['ci90'][0]:+.3f}, {t['ci90'][1]:+.3f}], "
               f"p_TOST = {t['p_tost']:.4f}, equivalent = {t['equivalent']}", "",
           "## H2b (adding arousal covariates)", "", "| feature | model | n | TSST − REST | TSST − TEEB |", "|---|---|---|---|---|"]
    for y in [PRIMARY] + SECONDARY:
        for k, m in res["H2b_arousal_adjusted"][y].items():
            md.append(f"| {y} | {k} | {m['n']} | {fmt(m['TSST_vs_REST'])} | {fmt(m['TSST_vs_TEEB'])} |")
    md += ["", "## Sensitivity (primary outcome)", "", "| variant | n | TSST − REST | TSST − TEEB |", "|---|---|---|---|"]
    for k, m in res["sensitivity"][PRIMARY].items():
        if isinstance(m, dict):
            md.append(f"| {k} | {m['n']} | {fmt(m['TSST_vs_REST'])} | {fmt(m['TSST_vs_TEEB'])} |")
    md += ["", f"Flags: {res['sensitivity']['flag_counts']}", "", "## H3 (within-person coupling, LMM)", ""]
    for y, m in res["H3_within_person_coupling"].items():
        if isinstance(m, dict):
            md.append(f"- {y} (n = {m['n_participants']}, obs = {m['n_obs']}): SBP_within {m['sbp_w']['est']:+.4f} "
                      f"[{m['sbp_w']['ci95'][0]:+.4f}, {m['sbp_w']['ci95'][1]:+.4f}] p = {m['sbp_w']['p']:.4f}; "
                      f"logCort_within {m['lcort_w']['est']:+.4f} [{m['lcort_w']['ci95'][0]:+.4f}, {m['lcort_w']['ci95'][1]:+.4f}] p = {m['lcort_w']['p']:.4f}")
    md += ["", "## Exploratory: group × time LMM (difference in change from VSA0 vs REST)", ""]
    for y, tr in res["exploratory_group_x_time_lmm"].items():
        if isinstance(tr, dict):
            md.append(f"- **{y}**: " + "; ".join(f"{k.replace('_minus_REST_change_to_', ' ')}: {v['est']:+.3f} (p = {v['p']:.3f})" for k, v in tr.items()))
    if "exploratory_top" in res:
        md += ["", "## Exploratory: 15 smallest p over all features (see CSV for all)", "",
               "| family | feature | contrast | est | p | q (FDR) | d_adj | rel. r(Δ) |", "|---|---|---|---|---|---|---|---|"]
        for r in res["exploratory_top"]:
            md.append(f"| {r['family']} | {r['feature']} | {r['contrast']} | {r['est']:+.4f} | {r['p']:.4f} | {r['q_fdr']:.3f} | "
                      f"{r['d_adj']:+.2f} | {r['reliability_r_delta'] if r['reliability_r_delta'] is not None else 'NA'} |")
    md += ["", "Figure: trajectories_PUBLIC.png"]
    (out / "analysis_1b_report_PUBLIC.md").write_text("\n".join(md) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)   # remove the extracted SPSS copy
    print(f"[done] -> {out}")


if __name__ == "__main__":
    main()
