#!/usr/bin/env python3
"""
A03 Step 0 audit: experiment protocols (xlsx) + VSA/STE wav files + SPSS metadata.

Read-only on all inputs. Writes into --out:
  PRIVATE_protocol_events.csv   every protocol row, parsed (participant level)
  PRIVATE_vsa_table.csv         one row per participant x VSA recording
  PRIVATE_cortisol_samples.csv  one row per participant x cortisol sample
  PRIVATE_issues.csv            one row per detected problem
  protocol_audit_summary_PUBLIC.json / .md   aggregate counts only, no IDs

Usage:
  python a03_protocol_audit.py --root <trials dir> --out <results dir>
         [--protocol-root <dir>] [--spss <.sav or .zip>] [--audio-stats]
"""
import argparse, datetime as dt, json, re, sys, tempfile, zipfile, warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)  # openpyxl data-validation noise

GROUPS = ("TSST", "TEEB", "REST")
NAME_RE = re.compile(r"(?P<date>\d{8})_(?P<pid>[0-9A-Za-z]+)_(?P<group>TSST|TEEB|REST)", re.I)
TASK_KEYS = ("tsst vorbereitung", "tsst durchführung", "tsst durchfuehrung", "zeitung lesen", "teeb")
MEASURE = {"cortisol", "vsa", "bp"}


# ---------------------------------------------------------------- helpers
def norm_pid(x):
    """Digits only, no leading zeros: '00123' -> '123', 12345.0 -> '12345'."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    d = re.sub(r"\D", "", str(x))
    return d.lstrip("0") or "0" if d else None


def to_minutes(v):
    """Clock value -> minutes after midnight. Handles time, datetime, Excel fraction, 'HH:MM'."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, dt.datetime):
        v = v.time()
    if isinstance(v, dt.time):
        return v.hour * 60 + v.minute + v.second / 60
    if isinstance(v, dt.timedelta):
        return v.total_seconds() / 60
    if isinstance(v, (int, float)):
        return float(v) * 1440 if 0 <= v < 1.5 else None
    m = re.search(r"(\d{1,2})[:.](\d{2})", str(v))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def to_offset(v):
    """'Real' column = elapsed time since Beginn. Excel stores a missing entry as a negative
    duration (shown as a 1899-12-29 datetime), which is treated as missing."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, dt.datetime):
        m = (v - dt.datetime(1899, 12, 30)).total_seconds() / 60
    elif isinstance(v, dt.time):
        m = v.hour * 60 + v.minute + v.second / 60
    elif isinstance(v, dt.timedelta):
        m = v.total_seconds() / 60
    elif isinstance(v, (int, float)):
        m = float(v) * 1440
    else:
        return None
    return m if 0 <= m <= 720 else None


def fnum(s):
    try:
        return float(str(s).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def parse_pair(s):
    """'3.29/3.1' -> (3.29, 3.1); '23.8' -> (23.8, None)."""
    if s is None:
        return None, None
    parts = re.split(r"[/;|]", str(s))
    vals = [fnum(p) for p in parts if p.strip()]
    vals = [v for v in vals if v is not None]
    return (vals + [None, None])[:2] if vals else (None, None)


def vsa_label(*cells):
    """Find the VSA file number in Messwert / Bemerkung text ('000', 'DateiNr: 004', 0)."""
    for c in cells:
        if c is None:
            continue
        if isinstance(c, (int, float)) and not (isinstance(c, float) and np.isnan(c)):
            return int(c)
        m = re.findall(r"\d{1,3}", str(c))
        if m:
            return int(m[-1])
    return None


def hhmm(m):
    return None if m is None else f"{int(m // 60):02d}:{int(round(m % 60)):02d}"


# ---------------------------------------------------------------- protocol parsing
def parse_protocol(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb["Protokoll"] if "Protokoll" in wb.sheetnames else wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    hdr_i = next((i for i, r in enumerate(rows) if r and str(r[0]).strip().lower() == "ablauf"), None)
    if hdr_i is None:
        raise ValueError("no 'Ablauf' header row")
    header = {}
    for r in rows[:hdr_i]:
        if r and r[0]:
            k = str(r[0]).strip().rstrip(":").lower()
            header[k] = r[1] if len(r) > 1 else None

    cols = {}
    for j, h in enumerate(rows[hdr_i]):
        h = str(h or "").lower()
        if "geplant" in h: cols["planned"] = j
        elif h.startswith("real"): cols["real"] = j
        elif "zeitstempel" in h: cols["ts"] = j
        elif "messwert" in h: cols["value"] = j
        elif "fehlerhaft" in h: cols["failed"] = j
        elif "bemerkung" in h: cols["note"] = j
    get = lambda r, k: (r[cols[k]] if k in cols and cols[k] < len(r) else None)

    events = []
    for r in rows[hdr_i + 1:]:
        if not r or r[0] is None or str(r[0]).strip() == "":
            continue
        events.append(dict(
            event=str(r[0]).strip(), ts_raw=get(r, "ts"), real_raw=get(r, "real"),
            value=get(r, "value"), failed=get(r, "failed"), note=get(r, "note")))

    # absolute minutes; fallback = Beginn + Real offset
    begin = next((to_minutes(e["ts_raw"]) for e in events if e["event"].lower() == "beginn"), None)
    for e in events:
        t = to_minutes(e["ts_raw"])
        src = "Zeitstempel"
        if t is None and begin is not None and to_offset(e["real_raw"]) is not None:
            t, src = begin + to_offset(e["real_raw"]), "Beginn+Real"
        e["t"], e["t_source"] = t, (src if t is not None else "missing")

    # bounds for missing times (from neighbours in table order)
    for i, e in enumerate(events):
        prev = [x["t"] for x in events[:i] if x["t"] is not None]
        nxt = [x["t"] for x in events[i + 1:] if x["t"] is not None]
        e["t_lo"] = max(prev) if prev else None
        e["t_hi"] = min(nxt) if nxt else None
    run_max, nonmono = -1, 0
    for e in events:
        e["out_of_order"] = bool(e["t"] is not None and e["t"] < run_max)
        nonmono += e["out_of_order"]
        if e["t"] is not None:
            run_max = max(run_max, e["t"])

    # task onset / last task row / documented duration
    task = [e for e in events if any(k in e["event"].lower() for k in TASK_KEYS)]
    onset = next((e["t"] for e in task if e["t"] is not None), None)
    last_task = task[-1] if task else None
    task_end = None
    if last_task and last_task["t"] is not None:
        txt = " ".join(str(last_task[k] or "") for k in ("value", "note", "failed"))
        m = re.search(r"(\d+)\s*min", txt)
        if m:
            task_end = last_task["t"] + int(m.group(1))
    meta = dict(
        header_pid=header.get("probandennummer"), header_group=header.get("probandengruppe"),
        header_date=header.get("datum"), remarks=header.get("sonstige bemerkungen"),
        begin=begin, onset=onset, last_task_start=last_task["t"] if last_task else None,
        task_end_documented=task_end, task_events=[e["event"] for e in task],
        task_notes=[str(e["note"] or e["value"] or "") for e in task], n_out_of_order=nonmono)
    return events, meta


def blocks(events):
    """Measurement blocks = consecutive runs of Cortisol/VSA/BP rows (table order)."""
    out, cur = [], []
    for i, e in enumerate(events):
        if e["event"].lower() in MEASURE:
            cur.append(i)
        elif cur:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- audio
def find_audio(root):
    """participant key -> list of dict(idx, path, pattern, subdirs) for every wav below it.
    pattern = path below the participant folder with digits masked (safe to publish)."""
    found = defaultdict(list)
    for p in root.rglob("*.wav"):
        m, pos = None, None
        for j in range(len(p.parts) - 2, -1, -1):
            m = NAME_RE.search(p.parts[j])
            if m:
                pos = j
                break
        if not m:
            continue
        below = p.parts[pos + 1:]
        idx = re.findall(r"(\d{1,3})", p.stem)
        key = (norm_pid(m["pid"]), m["group"].upper(), m["date"])
        found[key].append(dict(idx=int(idx[-1]) if idx else None, path=p,
                               pattern=re.sub(r"\d", "N", "/".join(below)),
                               subdirs=[x.lower() for x in below[:-1]]))
    return found


def wav_info(path, stats=False):
    import soundfile as sf
    info = sf.info(str(path))
    d = dict(sr=info.samplerate, channels=info.channels, subtype=info.subtype,
             duration_s=round(info.frames / info.samplerate, 2))
    if stats:
        x, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if x.shape[1] == 2:
            l, r = x[:, 0], x[:, 1]
            lr = lambda v: 20 * np.log10(np.sqrt((v ** 2).mean()) + 1e-12)
            d["lr_corr"] = round(float(np.corrcoef(l, r)[0, 1]) if l.std() > 0 and r.std() > 0 else float("nan"), 4)
            d["lr_level_diff_db"] = round(float(lr(l) - lr(r)), 2)
            d["lr_identical"] = bool(np.array_equal(l, r))
        x = x.mean(axis=1)
        hop = int(0.05 * sr)
        fr = x[: len(x) // hop * hop].reshape(-1, hop)
        rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
        db = 20 * np.log10(rms)
        d.update(rms_dbfs=round(float(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-12)), 2),
                 peak=round(float(np.abs(x).max()), 4),
                 clip_frac=round(float((np.abs(x) >= 0.999).mean()), 6),
                 noise_floor_db=round(float(np.percentile(db, 10)), 2),
                 speech_level_db=round(float(np.percentile(db, 90)), 2))
        d["snr_proxy_db"] = round(d["speech_level_db"] - d["noise_floor_db"], 2)
    return d


# ---------------------------------------------------------------- SPSS
def load_spss(path, tmpdir):
    try:
        import pyreadstat
    except ImportError:
        print("[warn] pyreadstat not installed -> SPSS checks skipped", file=sys.stderr)
        return None
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            sav = [n for n in z.namelist() if n.lower().endswith(".sav")][0]
            z.extract(sav, tmpdir)
            path = Path(tmpdir) / sav
    want = ["participant_id", "A03", "a03_type", "Group", "Geschlecht_codiert", "Alter",
            "UhrzeitErhebungsstart", "a03_date"]
    want += [f"Cortisol_Mittelwert_{i}" for i in range(1, 7)]
    want += [f"RR_sys_t{i}" for i in range(1, 6)] + [f"RR_dias_t{i}" for i in range(1, 6)]
    _, meta = pyreadstat.read_sav(str(path), metadataonly=True)
    use = [c for c in want if c in meta.column_names]
    df, _ = pyreadstat.read_sav(str(path), usecols=use)
    df = df[df["A03"] == 1].copy()
    df["pid"] = df["participant_id"].map(norm_pid)
    df["spss_type"] = df["a03_type"].map({1: "TSST", 2: "TEEB", 3: "REST"})
    if "Group" in df:
        df["spss_group"] = df["Group"].map({0: "REST", 1: "TEEB", 2: "TSST"})
    return df.set_index("pid")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="trials directory (audio, maybe protocols)")
    ap.add_argument("--protocol-root", action="append", default=[], help="extra dir(s) to search for protocol xlsx")
    ap.add_argument("--spss", default=None, help=".sav or .zip containing it")
    ap.add_argument("--out", required=True)
    ap.add_argument("--audio-stats", action="store_true", help="also read samples: level, clipping, noise floor")
    ap.add_argument("--audio-subdir", default="original",
                    help="use only wavs that have a folder of this name below the participant folder ('' = all)")
    a = ap.parse_args()

    root, out = Path(a.root), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    issues, ev_rows, vsa_rows, cort_rows = [], [], [], []
    def issue(pid, grp, kind, detail=""):
        issues.append(dict(pid=pid, group=grp, issue=kind, detail=str(detail)))

    # ---- protocols
    proto_files = {}
    for r in [root] + [Path(p) for p in a.protocol_root]:
        for p in r.rglob("*.xls*"):
            if p.name.startswith("~$"):
                continue
            m = NAME_RE.search(p.stem)
            if m:
                key = (norm_pid(m["pid"]), m["group"].upper(), m["date"])
                proto_files.setdefault(key, []).append(p)
    print(f"[info] protocol files: {sum(map(len, proto_files.values()))} for {len(proto_files)} participants")

    audio = find_audio(root)
    print(f"[info] audio folders: {len(audio)}")

    spss = load_spss(a.spss, tempfile.mkdtemp(dir=out)) if a.spss else None
    spss_status = "loaded" if spss is not None else ("not requested" if not a.spss else "failed (see log)")
    print(f"[info] SPSS: {spss_status}")

    parsed = {}
    for key, files in sorted(proto_files.items()):
        pid, grp, date = key
        if len(files) > 1:
            issue(pid, grp, "multiple_protocols", len(files))
        try:
            events, meta = parse_protocol(files[0])
        except Exception as ex:
            issue(pid, grp, "protocol_parse_error", ex); continue
        parsed[key] = (events, meta)
        hg = str(meta["header_group"] or "").strip().upper()
        if hg and hg != grp:
            issue(pid, grp, "group_filename_vs_header", hg)
        if meta["header_pid"] is not None and norm_pid(meta["header_pid"]) != pid:
            issue(pid, grp, "pid_filename_vs_header", meta["header_pid"])
        if meta["n_out_of_order"]:
            issue(pid, grp, "rows_out_of_time_order", meta["n_out_of_order"])
        if meta["onset"] is None:
            issue(pid, grp, "no_task_onset_time")
        if grp != "TSST":
            txt = " ".join(str(x or "") for e in events for x in (e["note"], e["value"], e["failed"]))
            txt += " " + str(meta["remarks"] or "")
            if re.search(r"vortrag|rechn|gremium|bewerbung", txt, re.I):
                issue(pid, grp, "tsst_keywords_in_nonTSST_protocol", "check notes")

        for i, e in enumerate(events):
            ev_rows.append(dict(pid=pid, group=grp, date=date, row=i, event=e["event"],
                                clock=hhmm(e["t"]), t_min=e["t"], t_source=e["t_source"],
                                rel_onset=None if e["t"] is None or meta["onset"] is None else round(e["t"] - meta["onset"], 1),
                                value=e["value"], failed=e["failed"], note=e["note"], out_of_order=e["out_of_order"]))

        # cortisol samples in table order
        c_idx = 0
        for i, e in enumerate(events):
            if e["event"].lower() == "cortisol":
                c_idx += 1
                v1, v2 = parse_pair(e["value"])
                cort_rows.append(dict(pid=pid, group=grp, sample=c_idx, t_min=e["t"],
                                      rel_onset=None if e["t"] is None or meta["onset"] is None else round(e["t"] - meta["onset"], 1),
                                      dup1=v1, dup2=v2,
                                      mean=None if v1 is None else (v1 if v2 is None else (v1 + v2) / 2),
                                      failed=e["failed"]))
        if c_idx != 6:
            issue(pid, grp, "cortisol_rows_not_6", c_idx)

        # VSA rows with their block partners
        bl = {i: b for b in blocks(events) for i in b}
        k, labels = 0, []
        for i, e in enumerate(events):
            if e["event"].lower() != "vsa":
                continue
            b = bl.get(i, [i])
            cort = next((events[j] for j in b if events[j]["event"].lower() == "cortisol"), None)
            bp = next((events[j] for j in b if events[j]["event"].lower() == "bp"), None)
            cort_sample = None
            if cort is not None:
                cort_sample = sum(1 for x in events[: events.index(cort) + 1] if x["event"].lower() == "cortisol")
            lab = vsa_label(e["value"], e["note"], e["failed"])
            labels.append(lab)
            sbp, dbp = parse_pair(bp["value"]) if bp else (None, None)
            t = e["t"]
            rel = lambda ref: None if t is None or ref is None else round(t - ref, 1)
            vsa_rows.append(dict(
                pid=pid, group=grp, date=date, vsa_order=k, vsa_label=lab, clock=hhmm(t), t_source=e["t_source"],
                t_lo=hhmm(e["t_lo"]) if t is None else None, t_hi=hhmm(e["t_hi"]) if t is None else None,
                rel_onset=rel(meta["onset"]), rel_last_task_start=rel(meta["last_task_start"]),
                rel_task_end_documented=rel(meta["task_end_documented"]),
                cortisol_sample=cort_sample, cortisol_mean=None if not cort else (lambda p: None if p[0] is None else (p[0] if p[1] is None else sum(p) / 2))(parse_pair(cort["value"])),
                sbp=sbp, dbp=dbp, failed=e["failed"], note=e["note"]))
            if t is None:
                issue(pid, grp, "vsa_time_missing", f"order {k}")
            k += 1
        if k != 5:
            issue(pid, grp, "vsa_rows_not_5", k)
        if labels != list(range(len(labels))):
            issue(pid, grp, "vsa_labels_nonstandard", ",".join(map(str, labels)))
        parsed[key] = (events, meta, labels)

    # ---- audio inventory + link to protocol
    vsa_df = pd.DataFrame(vsa_rows)
    import soundfile as sf
    # inventory of ALL wavs (header only), by masked sub-path pattern
    pattern_inv = defaultdict(lambda: dict(n_files=0, n_participants=set(), sr=Counter(), channels=Counter(),
                                           subtype=Counter(), dur=[]))
    for key, files in audio.items():
        for f in files:
            inv = pattern_inv[f["pattern"]]
            inv["n_files"] += 1; inv["n_participants"].add(key)
            try:
                h = sf.info(str(f["path"]))
                inv["sr"][h.samplerate] += 1; inv["channels"][h.channels] += 1; inv["subtype"][h.subtype] += 1
                inv["dur"].append(h.frames / h.samplerate)
            except Exception:
                inv["sr"]["unreadable"] += 1
    sub = a.audio_subdir.lower().strip()
    audio_rows, selected = [], {}
    for key, files in sorted(audio.items()):
        pid, grp, date = key
        if key not in parsed:
            issue(pid, grp, "audio_without_protocol")
        sel = [f for f in files if not sub or sub in f["subdirs"]]
        if not sel:
            issue(pid, grp, "no_wavs_in_audio_subdir", sub); continue
        by_idx = defaultdict(list)
        for f in sel:
            by_idx[f["idx"]].append(f)
        for i, fs in by_idx.items():
            if len(fs) > 1:
                issue(pid, grp, "multiple_wavs_same_index", f"index {i}: {len(fs)} files")
        idxs = sorted(i for i in by_idx if i is not None)
        if idxs != [0, 1, 2, 3, 4]:
            issue(pid, grp, "wav_indices_nonstandard", ",".join(map(str, idxs)))
        selected[key] = idxs
        for rank, i in enumerate(idxs):
            f = sorted(by_idx[i], key=lambda f: str(f["path"]))[0]
            try:
                info = wav_info(f["path"], a.audio_stats)
            except Exception as ex:
                issue(pid, grp, "wav_unreadable", f"{f['path'].name}: {ex}"); continue
            audio_rows.append(dict(pid=pid, group=grp, date=date, wav_index=i, wav_rank=rank,
                                   wav_name=f["path"].name, wav_relpath=str(f["path"].relative_to(root)), **info))
    for key in parsed:
        if key not in audio:
            issue(key[0], key[1], "protocol_without_audio")
    audio_df = pd.DataFrame(audio_rows)

    if len(vsa_df) and len(audio_df):
        vsa_df = vsa_df.merge(audio_df, how="left", left_on=["pid", "group", "date", "vsa_order"],
                              right_on=["pid", "group", "date", "wav_rank"])
        # does the protocol label agree with file index (by order)?
        mis = vsa_df[vsa_df["wav_index"].notna() & (vsa_df["vsa_label"] != vsa_df["wav_index"])]
        for _, r in mis.iterrows():
            issue(r.pid, r.group, "protocol_label_ne_wav_index", f"order {r.vsa_order}: label {r.vsa_label} vs file {int(r.wav_index)}")

    # ---- SPSS consistency
    cort_df = pd.DataFrame(cort_rows)
    spss_checks = Counter()
    if spss is not None:
        pids_proto = {k[0] for k in parsed}
        spss_checks["spss_A03_n"] = len(spss)
        spss_checks["protocol_pids_in_spss"] = len(pids_proto & set(spss.index))
        for pid in sorted(set(spss.index) - pids_proto):
            issue(pid, spss.loc[pid, "spss_type"], "spss_without_protocol")
        for (pid, grp, date), (events, meta, labels) in parsed.items():
            if pid not in spss.index:
                issue(pid, grp, "protocol_not_in_spss"); continue
            s = spss.loc[pid]
            if isinstance(s, pd.DataFrame):
                issue(pid, grp, "spss_duplicate_pid"); s = s.iloc[0]
            if s.get("spss_type") != grp:
                issue(pid, grp, "group_protocol_vs_a03_type", s.get("spss_type"))
            if "spss_group" in s and isinstance(s["spss_group"], str) and s["spss_group"] != grp:
                issue(pid, grp, "group_protocol_vs_Group", s["spss_group"])
            cs = cort_df[(cort_df.pid == pid) & (cort_df.group == grp)]
            for _, c in cs.iterrows():
                col = f"Cortisol_Mittelwert_{int(c['sample'])}"
                if col in s and pd.notna(s[col]) and c["mean"] is not None:
                    if abs(s[col] - c["mean"]) > 0.05:
                        issue(pid, grp, "cortisol_protocol_ne_spss", f"T{int(c['sample'])}: {c['mean']:.3f} vs {s[col]:.3f}")
                    else:
                        spss_checks["cortisol_values_agree"] += 1
                if c["dup1"] is not None and c["dup2"] is not None and c["mean"]:
                    if abs(c["dup1"] - c["dup2"]) / c["mean"] > 0.5:
                        issue(pid, grp, "cortisol_duplicates_disagree", f"T{int(c['sample'])}: {c['dup1']} / {c['dup2']}")
            vs = vsa_df[(vsa_df.pid == pid) & (vsa_df.group == grp)]
            for _, v in vs.iterrows():
                col = f"RR_sys_t{int(v.vsa_order) + 1}"
                if col in s and pd.notna(s[col]) and pd.notna(v.sbp):
                    if abs(s[col] - v.sbp) > 0.5:
                        issue(pid, grp, "sbp_protocol_ne_spss", f"t{int(v.vsa_order)+1}: {v.sbp} vs {s[col]}")
                    else:
                        spss_checks["sbp_values_agree"] += 1
            st = to_minutes(s.get("UhrzeitErhebungsstart"))
            if st is not None and meta["begin"] is not None and abs(st - meta["begin"]) > 15:
                issue(pid, grp, "start_time_protocol_ne_spss", f"{hhmm(meta['begin'])} vs {hhmm(st)}")

    # ---- write PRIVATE
    pd.DataFrame(ev_rows).to_csv(out / "PRIVATE_protocol_events.csv", index=False)
    vsa_df.to_csv(out / "PRIVATE_vsa_table.csv", index=False)
    cort_df.to_csv(out / "PRIVATE_cortisol_samples.csv", index=False)
    iss = pd.DataFrame(issues, columns=["pid", "group", "issue", "detail"])
    iss.to_csv(out / "PRIVATE_issues.csv", index=False)

    # ---- PUBLIC summary (aggregates only)
    def q(s):
        s = pd.to_numeric(s, errors="coerce").dropna()
        return None if s.empty else dict(n=int(len(s)), median=round(float(s.median()), 1),
                                         q25=round(float(s.quantile(.25)), 1), q75=round(float(s.quantile(.75)), 1),
                                         min=round(float(s.min()), 1), max=round(float(s.max()), 1))
    pub = dict(
        generated=dt.datetime.now().isoformat(timespec="seconds"),
        n_protocol_participants=Counter(k[1] for k in parsed),
        n_audio_participants=Counter(k[1] for k in audio),
        n_protocol_and_audio=Counter(k[1] for k in parsed if k in audio),
        issue_counts={i: dict(Counter(iss[iss.issue == i].group.fillna("NA"))) for i in sorted(iss.issue.unique())},
        participants_with_any_issue=int(iss[iss.issue != "spss_without_protocol"].pid.nunique()),
        vsa_label_patterns=Counter(",".join(map(str, v[2])) for v in parsed.values()),
        wav_index_patterns_all_files=Counter(",".join(map(str, sorted(x["idx"] for x in f if x["idx"] is not None))) for f in audio.values()),
        task_events_by_group={g: Counter(" > ".join(m["task_events"]) for k, (e, m, l) in parsed.items() if k[1] == g) for g in GROUPS},
        task_notes_by_group={g: Counter(" | ".join(m["task_notes"]) for k, (e, m, l) in parsed.items() if k[1] == g).most_common(5) for g in GROUPS},
        session_start_clock_h={g: q(pd.Series([m["begin"] / 60 for k, (e, m, l) in parsed.items() if k[1] == g and m["begin"] is not None])) for g in GROUPS},
        spss_status=spss_status,
        spss_checks=dict(spss_checks),
        audio_subdir_used=sub or "(all)",
        audio_path_patterns={k: dict(n_files=v["n_files"], n_participants=len(v["n_participants"]),
                                     sr=v["sr"], channels=v["channels"], subtype=v["subtype"],
                                     duration_s_median=round(float(np.median(v["dur"])), 1) if v["dur"] else None)
                             for k, v in sorted(pattern_inv.items(), key=lambda kv: -kv[1]["n_files"])},
        selected_wav_index_patterns=Counter(",".join(map(str, v)) for v in selected.values()),
    )
    # usable cohort: protocol + 5 selected wavs + all 5 VSA times known
    usable = Counter(); usable_cort = Counter()
    for key, (events, meta, labels) in parsed.items():
        if len(selected.get(key, [])) != 5 or len(labels) != 5:
            continue
        v = vsa_df[(vsa_df.pid == key[0]) & (vsa_df.group == key[1]) & (vsa_df.date == key[2])]
        if v.clock.notna().sum() == 5:
            usable[key[1]] += 1
            if spss is not None and key[0] in spss.index:
                s = spss.loc[key[0]]
                s = s.iloc[0] if isinstance(s, pd.DataFrame) else s
                if pd.notna(s.get("Cortisol_Mittelwert_1")) and pd.notna(s.get("Cortisol_Mittelwert_4")):
                    usable_cort[key[1]] += 1
    pub["usable_protocol_5wav_5times"] = usable
    pub["usable_plus_cortisol_T1_T4"] = usable_cort if spss is not None else "SPSS not loaded"
    if len(vsa_df):
        timing = {}
        for g in GROUPS:
            for o in range(5):
                s = vsa_df[(vsa_df.group == g) & (vsa_df.vsa_order == o)]
                timing[f"{g}_VSA{o}"] = dict(
                    min_from_task_onset=q(s.rel_onset), min_from_last_task_row=q(s.rel_last_task_start),
                    min_from_documented_task_end=q(s.rel_task_end_documented),
                    n_time_missing=int(s.clock.isna().sum()),
                    paired_cortisol_sample=dict(Counter(s.cortisol_sample.dropna().astype(int))))
        pub["vsa_timing"] = timing
    if len(cort_df):
        pub["cortisol_timing_min_from_onset"] = {f"{g}_T{t}": q(cort_df[(cort_df.group == g) & (cort_df["sample"] == t)].rel_onset)
                                                 for g in GROUPS for t in range(1, 7)}
    if len(audio_df):
        pub["audio_format"] = dict(sr=Counter(audio_df.sr), channels=Counter(audio_df.channels), subtype=Counter(audio_df.subtype))
        pub["audio_duration_s_by_index"] = {int(i): q(audio_df[audio_df.wav_index == i].duration_s) for i in sorted(audio_df.wav_index.dropna().unique())}
        if a.audio_stats:
            pub["audio_level_by_group_index"] = {
                f"{g}_{int(i)}": {c: q(s[c]) for c in ("rms_dbfs", "noise_floor_db", "snr_proxy_db", "clip_frac")}
                for (g, i), s in audio_df.groupby(["group", "wav_index"])}
            if "lr_corr" in audio_df:
                st = audio_df[audio_df.channels == 2]
                pub["stereo_check"] = dict(n=int(len(st)), identical_channels=int(st.lr_identical.sum()),
                                           lr_corr=q(st.lr_corr), lr_level_diff_db=q(st.lr_level_diff_db))
            pub["audio_format_by_year_group"] = {
                f"{y}_{g}": dict(sr=Counter(s.sr), subtype=Counter(s.subtype))
                for (y, g), s in audio_df.assign(y=audio_df.date.str[:4]).groupby(["y", "group"])}
            pub["audio_noise_floor_by_year_group"] = {
                f"{y}_{g}": q(s.noise_floor_db) for (y, g), s in audio_df.assign(y=audio_df.date.str[:4]).groupby(["y", "group"])}

    def clean(o):
        if isinstance(o, Counter): o = dict(o)
        if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [clean(v) for v in o]
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        return o
    pub = clean(pub)
    (out / "protocol_audit_summary_PUBLIC.json").write_text(json.dumps(pub, indent=2, ensure_ascii=False))

    md = ["# A03 protocol audit (PUBLIC, aggregates only)", ""]
    md += [f"- protocol participants: {pub['n_protocol_participants']}",
           f"- audio participants: {pub['n_audio_participants']}",
           f"- both: {pub['n_protocol_and_audio']}",
           f"- participants with any issue: {pub['participants_with_any_issue']}", "", "## Issues (count by group)", ""]
    md += [f"- {k}: {v}" for k, v in pub["issue_counts"].items()]
    md += ["", f"- SPSS: {pub['spss_status']}", f"- audio subdir used: {pub['audio_subdir_used']}",
           f"- usable (protocol + 5 wavs + 5 VSA times): {pub['usable_protocol_5wav_5times']}",
           f"- usable + cortisol T1/T4: {pub['usable_plus_cortisol_T1_T4']}", "", "## Audio path patterns", ""]
    md += [f"- `{k}`: {v['n_files']} files, {v['n_participants']} participants, sr {v['sr']}, ch {v['channels']}"
           for k, v in pub["audio_path_patterns"].items()]
    if "vsa_timing" in pub:
        md += ["", "## VSA timing, minutes from task onset (median [IQR], n missing)", "",
               "| group | VSA0 | VSA1 | VSA2 | VSA3 | VSA4 |", "|---|---|---|---|---|---|"]
        for g in GROUPS:
            cells = []
            for o in range(5):
                t = pub["vsa_timing"][f"{g}_VSA{o}"]; s = t["min_from_task_onset"]
                cells.append("–" if not s else f"{s['median']} [{s['q25']}, {s['q75']}] m{t['n_time_missing']}")
            md.append(f"| {g} | " + " | ".join(cells) + " |")
    (out / "protocol_audit_summary_PUBLIC.md").write_text("\n".join(md) + "\n")
    print(f"[done] {len(parsed)} protocols, {len(audio)} audio folders, {len(iss)} issues -> {out}")


if __name__ == "__main__":
    main()
