#!/usr/bin/env python3
"""
A03 Step 2a: zero-shot arousal / dominance / valence from the audEERING wav2vec2 model
(audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim, research use only, CC BY-NC-SA 4.0).

No training on A03 data. Each recording is resampled to 16 kHz, each stereo channel is cut
into 6 s windows (3 s hop); window predictions are averaged per file and channel.

Outputs (in --out):
  PRIVATE_w2v2_long.csv        one row per participant x file x channel
  PRIVATE_w2v2_embeddings.npz  mean pooled hidden state (1024-d) per row, same order as the csv
"""
import argparse, math, re, sys, time, warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
NAME_RE = re.compile(r"(?P<date>\d{8})_(?P<pid>[0-9A-Za-z]+)_(?P<group>TSST|TEEB|REST)", re.I)
SKIP_DIRS = {"processed", "processed_norm", "trimmed"}
SR = 16000
MODEL = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
WIN_S, HOP_S, MAX_S = 6.0, 3.0, 180.0


def norm_pid(x):
    d = re.sub(r"\D", "", str(x))
    return (d.lstrip("0") or "0") if d else None


def select_files(root):
    """Same rule as Step 1a: vsa/original/ preferred, else files directly in vsa/; never derivatives."""
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
        by_part[(norm_pid(m["pid"]), m["group"].upper(), m["date"])].append((tier, int(idx[-1]) if idx else None, p))
    out = {}
    for key, files in by_part.items():
        best = min(t for t, _, _ in files)
        seen, uniq = set(), []
        for i, p in sorted((i, p) for t, i, p in files if t == best and i is not None):
            if i not in seen:
                seen.add(i); uniq.append((i, p))
        out[key] = uniq
    return out


def load_channels(path):
    import soundfile as sf
    from scipy.signal import resample_poly
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    g = math.gcd(SR, sr)
    return [x[:, c] if sr == SR else resample_poly(x[:, c], SR // g, sr // g).astype(np.float32)
            for c in range(min(x.shape[1], 2))], x.shape[0] / sr


def windows(y):
    w, h = int(WIN_S * SR), int(HOP_S * SR)
    y = y[: int(MAX_S * SR)]
    if len(y) < w:
        return [np.pad(y, (0, w - len(y)))] if len(y) >= SR else []
    return [y[s:s + w] for s in range(0, len(y) - w + 1, h)]


def build_model(device):
    """Version-robust loader (transformers 4.x and 5.x).
    The encoder is loaded with the standard Wav2Vec2Model class (which handles key renames);
    the 2-layer regression head is a plain nn.Module filled from the checkpoint's classifier.* tensors.
    A self-check against the model card's reference output (silent 1 s input) is printed."""
    import torch, torch.nn as nn
    from huggingface_hub import snapshot_download
    from transformers import Wav2Vec2Config, Wav2Vec2FeatureExtractor, Wav2Vec2Model

    path = Path(snapshot_download(MODEL, allow_patterns=["*.json", "*.bin", "*.safetensors", "*.txt"]))
    config = Wav2Vec2Config.from_pretrained(path)
    fe = Wav2Vec2FeatureExtractor.from_pretrained(path)
    encoder = Wav2Vec2Model.from_pretrained(path).to(device).eval()

    sd = {}
    st_files = sorted(path.glob("*.safetensors"))
    if st_files:
        from safetensors.torch import load_file
        for f in st_files:
            sd.update(load_file(str(f)))
    else:
        for f in sorted(path.glob("*.bin")):
            sd.update(torch.load(str(f), map_location="cpu"))

    # encoder sanity: one weight must equal the checkpoint tensor
    k = "wav2vec2.feature_projection.projection.weight"
    if k in sd and not torch.allclose(encoder.feature_projection.projection.weight.detach().cpu(), sd[k].float()):
        raise RuntimeError("encoder weights do not match the checkpoint")

    dense = nn.Linear(config.hidden_size, config.hidden_size)
    out_proj = nn.Linear(config.hidden_size, config.num_labels)
    need = ["classifier.dense.weight", "classifier.dense.bias", "classifier.out_proj.weight", "classifier.out_proj.bias"]
    missing = [n for n in need if n not in sd]
    if missing:
        raise RuntimeError(f"classifier weights missing in checkpoint: {missing}")
    with torch.no_grad():
        dense.weight.copy_(sd[need[0]]); dense.bias.copy_(sd[need[1]])
        out_proj.weight.copy_(sd[need[2]]); out_proj.bias.copy_(sd[need[3]])
    dense, out_proj = dense.to(device).eval(), out_proj.to(device).eval()

    def predict(batch):
        """batch: list of equal-length float32 arrays -> (embeddings [n,1024], scores [n,3])"""
        iv = fe(batch, sampling_rate=SR, return_tensors="pt", padding=True)["input_values"].to(device)
        with torch.no_grad():
            hid = encoder(iv)[0].mean(dim=1)
            log = out_proj(torch.tanh(dense(hid)))
        return hid.float().cpu().numpy(), log.float().cpu().numpy()

    ref = np.array([0.5460754, 0.6062266, 0.40431657])
    got = predict([np.zeros(SR, dtype=np.float32)])[1][0]
    ok = np.allclose(got, ref, atol=0.02)
    print(f"[check] silent-input output {np.round(got, 4)} vs model card {np.round(ref, 4)} -> {'OK' if ok else 'MISMATCH'}", flush=True)
    if not ok:
        raise RuntimeError("model output does not reproduce the model card reference; not using it")
    return predict


def mock_predict(batch):
    rng = np.random.default_rng(len(batch))
    return rng.normal(size=(len(batch), 1024)).astype(np.float32), rng.uniform(0.3, 0.7, size=(len(batch), 3)).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--mock", action="store_true", help="skip the model (pipeline test only)")
    a = ap.parse_args()
    root, out = Path(a.root), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.mock:
        predict, device = mock_predict, "mock"
    else:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        predict = build_model(device)
    sel = select_files(root)
    keys = sorted(sel)[: a.limit] if a.limit else sorted(sel)
    print(f"[info] device: {device}  participants: {len(keys)}  files: {sum(len(sel[k]) for k in keys)}", flush=True)

    rows, embs, t0 = [], [], time.time()
    for n, key in enumerate(keys, 1):
        pid, grp, date = key
        for rank, (idx, p) in enumerate(sel[key]):
            try:
                chans, dur = load_channels(p)
            except Exception as ex:
                print(f"[warn] unreadable file skipped ({ex})"); continue
            for c, y in enumerate(chans):
                ws = windows(y)
                if not ws:
                    continue
                H, S = [], []
                for i in range(0, len(ws), a.batch):
                    h, s = predict(ws[i:i + a.batch]); H.append(h); S.append(s)
                H, S = np.concatenate(H), np.concatenate(S)
                rows.append(dict(pid=pid, group=grp, date=date, wav_index=idx, wav_rank=rank, channel="LR"[c],
                                 duration_total_s=round(dur, 2), n_windows=len(ws),
                                 w2v2_arousal=float(S[:, 0].mean()), w2v2_dominance=float(S[:, 1].mean()),
                                 w2v2_valence=float(S[:, 2].mean()), w2v2_arousal_sd=float(S[:, 0].std())))
                embs.append(H.mean(axis=0))
        if n % 10 == 0 or n == len(keys):
            print(f"  {n}/{len(keys)} participants, {time.time() - t0:.0f} s", flush=True)
    pd.DataFrame(rows).to_csv(out / "PRIVATE_w2v2_long.csv", index=False)
    np.savez_compressed(out / "PRIVATE_w2v2_embeddings.npz", emb=np.stack(embs).astype(np.float32))
    print(f"[done] {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
