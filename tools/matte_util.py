"""抠像/量测共用工具：HSV 判定 + 形态学重建（连通域）。

为什么不只用色相判定：
  1. 橄榄绿外套 #3A5D48（色相≈144°）与绿幕（≈117°）只差 27°，窗口一宽就吃掉外套；
  2. 各模型都会打水印：即梦是绿底"AI 生成"（会被色相判定顺带抠掉），
     豆包是**白色**"豆包AI生成"且**逐帧移动**（低饱和 → 色相判定抓不到）。
  → 所以再来一道"连通域"：只保留与角色主体连通的那一块，
    水印、光柱、飘落的碎屑等独立小块一律丢弃。
"""
import numpy as np
from PIL import Image, ImageFilter


def rgb_to_hsv_np(a):
    """a:(...,3) uint8/float → hue(0-360), sat(0-1), val(0-255)"""
    a = np.asarray(a).astype(np.float32)
    mx = a.max(axis=-1); mn = a.min(axis=-1); d = mx - mn
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    dz = np.where(d == 0, 1, d)
    hr = ((g - b) / dz) % 6
    hg = (b - r) / dz + 2
    hb = (r - g) / dz + 4
    hue = np.where(mx == r, hr, np.where(mx == g, hg, hb)) * 60.0
    hue = np.where(d == 0, 0.0, hue) % 360
    sat = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0.0)
    return hue, sat, mx


def border_hue(arr):
    """从画幅四边采样背景色相（圆形平均）。"""
    border = np.concatenate([arr[:4].reshape(-1, 3), arr[-4:].reshape(-1, 3),
                             arr[:, :4].reshape(-1, 3), arr[:, -4:].reshape(-1, 3)])
    h, s, v = rgb_to_hsv_np(border)
    sel = s >= 0.2
    rad = np.deg2rad(h[sel] if sel.any() else h)
    return float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360)


def bg_mask(arr, bg_hue, hue_tol=18.0, sat_min=0.20):
    """背景掩码：只认"背景色相 ± 容差"且够饱和的像素。"""
    hue, sat, val = rgb_to_hsv_np(arr)
    dh = np.abs((hue - bg_hue + 180) % 360 - 180)
    return (dh <= hue_tol) & (sat >= sat_min)


def _dilate(m, k):
    """方形膨胀 k 像素（用 PIL 的 MaxFilter，C 实现，比 numpy 逐次 roll 快）。"""
    if k <= 0:
        return m
    im = Image.fromarray((m.astype(np.uint8) * 255), "L")
    im = im.filter(ImageFilter.MaxFilter(2 * k + 1))
    return np.asarray(im) > 0


def reconstruct(mask, seed, max_iter=4000):
    """形态学重建：mask 中与 seed 连通的部分。

    ⚠️ 必须每轮只膨胀 **1 像素**（3x3）。曾经用"逐轮放大膨胀核"（1,2,4,8…）来加速，
    结果大核可以直接"跳过"空隙落在 mask 里的另一块上 —— 水印会被并进角色，
    实测表现为量出来的构图数字完全不对。宁慢勿错。
    """
    reach = seed & mask
    if not reach.any():
        return reach
    for _ in range(max_iter):
        nxt = _dilate(reach, 1) & mask
        if nxt.sum() == reach.sum():
            return reach
        reach = nxt
    return reach


def main_component(mask, seed_xy=None, factor=4, refine_iter=24):
    """返回 mask 中"主体"连通域。

    seed 默认取离画面中心最近的 mask 像素（角色恒在画面中央，水印/碎屑都在边角）。
    为提速：先在 factor 倍降采样上做完整重建，再回填到原分辨率做少量轮次细化
    （细化才能把胡须、尾巴尖这类细结构补回来）。
    """
    h, w = mask.shape
    if seed_xy is None:
        cy, cx = h // 2, w // 2
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return mask
        i = np.argmin((ys - cy) ** 2 + (xs - cx) ** 2)
        seed_xy = (ys[i], xs[i])

    small = mask[::factor, ::factor]
    sy, sx = min(seed_xy[0] // factor, small.shape[0] - 1), min(seed_xy[1] // factor, small.shape[1] - 1)
    if not small[sy, sx]:
        ys, xs = np.nonzero(small)
        if len(xs) == 0:
            return mask
        i = np.argmin((ys - sy) ** 2 + (xs - sx) ** 2)
        sy, sx = ys[i], xs[i]
    seed = np.zeros_like(small)
    seed[sy, sx] = True
    comp_small = reconstruct(small, seed)

    comp = np.repeat(np.repeat(comp_small, factor, axis=0), factor, axis=1)[:h, :w]
    comp = comp & mask
    if refine_iter > 0:
        comp = reconstruct(mask, comp, max_iter=refine_iter)
    return comp