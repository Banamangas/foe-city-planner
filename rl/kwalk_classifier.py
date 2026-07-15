from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


class FeasibilityCNN(nn.Module):
    def __init__(self, in_ch: int = 4, n_glob: int = 9):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, 16, 3, padding=1), nn.ReLU(),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(),
            nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.head = nn.Sequential(
            nn.Linear(32 + n_glob, 64), nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(self, x, g):
        h = self.conv(x).flatten(1)
        return self.head(torch.cat([h, g], dim=1)).squeeze(1)


def _loaders(samples, batch, seed):
    g = torch.from_numpy(samples["g"])
    gmean, gstd = g.mean(0, keepdim=True), g.std(0, keepdim=True) + 1e-6
    g = (g - gmean) / gstd
    ds = torch.utils.data.TensorDataset(
        torch.from_numpy(samples["X"]), g, torch.from_numpy(samples["y"]))
    gen = torch.Generator().manual_seed(seed)
    return torch.utils.data.DataLoader(ds, batch_size=batch, shuffle=True, generator=gen), gmean, gstd


def train(samples, *, epochs=30, lr=1e-3, batch=64, seed=0, device="cpu"):
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = FeasibilityCNN(in_ch=samples["X"].shape[1], n_glob=samples["g"].shape[1]).to(device)
    loader, gmean, gstd = _loaders(samples, batch, seed)
    model._gmean = gmean.to(device)
    model._gstd = gstd.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    pos = float(samples["y"].sum())
    neg = float(len(samples["y"]) - pos)
    pw = torch.tensor([neg / max(pos, 1.0)], device=device)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    model.train()
    for _ in range(epochs):
        for xb, gb, yb in loader:
            xb, gb, yb = xb.to(device), gb.to(device), yb.to(device)
            opt.zero_grad()
            lossf(model(xb, gb), yb).backward()
            opt.step()
    model.eval()
    return model


def predict_proba(model, X, g, device="cpu"):
    model.eval()
    with torch.no_grad():
        xb = torch.from_numpy(np.asarray(X, dtype=np.float32)).to(device)
        gb = (torch.from_numpy(np.asarray(g, dtype=np.float32)).to(device) - model._gmean) / model._gstd
        return torch.sigmoid(model(xb, gb)).cpu().numpy()


def save(model, path, H, W):
    torch.save({"state": model.state_dict(), "H": int(H), "W": int(W),
                "in_ch": model.conv[0].in_channels, "n_glob": model.head[0].in_features - 32,
                "gmean": model._gmean.cpu(), "gstd": model._gstd.cpu()}, str(path))


def load(path):
    ck = torch.load(str(path), map_location="cpu")
    model = FeasibilityCNN(in_ch=ck["in_ch"], n_glob=ck["n_glob"])
    model.load_state_dict(ck["state"])
    model._gmean = ck["gmean"]
    model._gstd = ck["gstd"]
    model.eval()
    return model, ck["H"], ck["W"]
