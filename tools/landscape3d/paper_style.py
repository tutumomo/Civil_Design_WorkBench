# -*- coding: utf-8 -*-
"""把 3D 算圖壓成「手繪／水彩紙」質感（交付用的景觀意象圖）。

為什麼要另做這一步
------------------
Cycles 出來的圖再怎麼調材質，都還是「CG 渲染」的味道：乾淨、飽和、均勻。
景觀意象圖要的是「用麥克筆／水彩在紙上畫的」——所以出圖後再疊三層：

1. **紙紋**：多尺度雜訊 + 纖維，做成米白紙面（乘算），邊緣略泛黃。
2. **水彩化**：輕微模糊色彩（保留線稿）、降飽和、提亮暗部（水彩不會純黑）。
3. **筆觸**：Sobel 邊緣取線，壓成墨線；再加一層極輕的手抖位移，避免線條太「電腦」。

用法（專案 .venv，需要 numpy／Pillow）：
    .venv/bin/python tools/landscape3d/paper_style.py in.png out.png [--strength 1.0] [--ink 0.55]

設計原則：**可重跑、參數可調、不覆寫輸入**；同一張圖重跑結果一致（固定亂數種子）。
"""
from __future__ import annotations

import argparse
import math

import numpy as np
from PIL import Image, ImageFilter


def fbm(h, w, octaves=(4, 12, 40, 120), weights=(0.45, 0.30, 0.17, 0.08), seed=7):
    """多尺度雜訊（以縮放後的低解析雜訊放大疊加，模擬紙張纖維粗細）。"""
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w), dtype=np.float32)
    for oct_i, cells, wgt in zip(range(len(octaves)), octaves, weights):
        small = rng.random((max(2, int(h / cells)), max(2, int(w / cells)))).astype(np.float32)
        img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        acc += np.asarray(img, dtype=np.float32) / 255.0 * wgt
    acc -= acc.min()
    acc /= max(1e-6, acc.max())
    return acc


def fibers(h, w, seed=11, n=90):
    """紙纖維：短斜線，讓紙面有方向性。"""
    rng = np.random.default_rng(seed)
    canvas = np.zeros((h, w), dtype=np.float32)
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    for y0, x0 in zip(ys, xs):
        length = int(rng.integers(30, 160))
        ang = rng.uniform(-0.35, 0.35) + (0.0 if rng.random() < 0.7 else math.pi / 2)
        alpha = float(rng.uniform(0.03, 0.10))
        for t in range(length):
            y = int(y0 + math.sin(ang) * t)
            x = int(x0 + math.cos(ang) * t)
            if 0 <= y < h and 0 <= x < w:
                canvas[y, x] = max(canvas[y, x], alpha)
    k = Image.fromarray((canvas * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    return np.asarray(k, dtype=np.float32) / 255.0


def sobel(gray):
    g = gray.astype(np.float32)
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    ky = kx.T
    out = np.zeros_like(g)
    for ky_i in range(1, g.shape[0] - 1):
        pass
    # 以影像位移向量化（比逐點快很多）
    def shift(a, dy, dx):
        b = np.zeros_like(a)
        b[1:-1, 1:-1] = a[1 + dy: a.shape[0] - 1 + dy, 1 + dx: a.shape[1] - 1 + dx]
        return b
    gx = (shift(g, -1, -1) * kx[0, 0] + shift(g, 0, -1) * kx[1, 0] + shift(g, 1, -1) * kx[2, 0]
          + shift(g, -1, 1) * kx[0, 2] + shift(g, 0, 1) * kx[1, 2] + shift(g, 1, 1) * kx[2, 2])
    gy = (shift(g, -1, -1) * ky[0, 0] + shift(g, -1, 0) * ky[0, 1] + shift(g, -1, 1) * ky[0, 2]
          + shift(g, 1, -1) * ky[2, 0] + shift(g, 1, 0) * ky[2, 1] + shift(g, 1, 1) * ky[2, 2])
    out = np.sqrt(gx * gx + gy * gy)
    out /= max(1e-6, out.max())
    return out


def paper_style(src, dst, strength=1.0, ink=0.5, paper=(0.965, 0.945, 0.900),
                desat=0.88, seed=2026):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    rgb = np.asarray(im, dtype=np.float32) / 255.0

    # ---------- 1. 水彩化：柔化色塊（線稿另外疊，所以可以放心糊一點）----------
    soft = np.asarray(im.filter(ImageFilter.GaussianBlur(1.1)), dtype=np.float32) / 255.0
    rgb = rgb * 0.55 + soft * 0.45

    # 降飽和 + 提亮暗部（水彩不壓純黑）
    gray = rgb.mean(axis=2, keepdims=True)
    rgb = gray + (rgb - gray) * desat
    rgb = 0.055 + rgb * 0.945

    # ---------- 2. 線稿：Sobel 取邊，做成墨色邊緣 ----------
    lum = rgb.mean(axis=2)
    edges = sobel(lum)
    edges = np.clip((edges - 0.05) * 2.2, 0.0, 1.0) ** 0.85
    ink_mask = (edges * ink)[..., None]

    # ---------- 3. 紙紋 ----------
    tex = fbm(h, w, seed=seed)
    fib = fibers(h, w, seed=seed + 1)
    paper_rgb = np.array(paper, dtype=np.float32)
    tex_mix = (tex * 0.85 + fib * 0.9)
    tex_mix = 0.94 + tex_mix * 0.12                     # 0.94..1.06
    paper_layer = paper_rgb[None, None, :] * tex_mix[..., None]

    # 紙面吸收：把 CG 顏色「染」到紙上（乘算），但保留亮部不壓死
    out = rgb * (paper_layer / paper_rgb.mean()) * 0.55 + rgb * 0.45
    out *= tex_mix[..., None] ** 0.35

    # ---------- 4. 墨線疊上去 ----------
    out = out * (1.0 - ink_mask * 0.85)

    # ---------- 5. 不均勻照明／邊緣微暗（掃描紙感）----------
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w * 0.5, h * 0.5
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / math.sqrt(2)
    vig = 1.0 - 0.18 * (r ** 2.2)
    glow = 1.0 + 0.05 * fbm(h, w, octaves=(200, 400), weights=(0.6, 0.4), seed=seed + 3)
    out *= (vig * glow)[..., None]

    # ---------- 6. 收尾：細顆粒 + 微暖 ----------
    grain = (np.random.default_rng(seed + 5).random((h, w, 1)).astype(np.float32) - 0.5)
    out = np.clip(out + grain * 0.012 * strength, 0.0, 1.0)
    out[..., 0] = np.clip(out[..., 0] * 1.012, 0, 1)
    out[..., 2] = np.clip(out[..., 2] * 0.990, 0, 1)

    Image.fromarray((out * 255.0 + 0.5).astype(np.uint8)).save(dst, optimize=True)
    return dst


def main():
    ap = argparse.ArgumentParser(description="3D 算圖 → 手繪／水彩紙質感")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--ink", type=float, default=0.5)
    a = ap.parse_args()
    paper_style(a.src, a.dst, strength=a.strength, ink=a.ink)
    print("written:", a.dst)


if __name__ == "__main__":
    main()
