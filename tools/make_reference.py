"""把任意"角色图"加工成素材链可用的合规首帧（默认品红背景，可指定颜色）。

用法:
    python tools/make_reference.py <源图> [--out <输出png>] [--bg "#FF00FF"] [--height-pct 65] [--head-pct 20] [--feet-pct 85]
    python tools/make_reference.py <源图> --also-720p <输出png>

做的事（全部是"统一缩放 + 平移 + 遮罩" + 换填充色，不重新生成，角色像素级不变）：
  1. 按 HSV 色相把源图背景抠掉（**背景色由源图四周采样，绿/品红/蓝都能处理**）
  2. 显式遮罩左上角水印区（即梦/剪映的"AI 生成"角标），填成 --bg 指定的颜色
  3. 等比缩放到"角色高度 = height_pct%"，水平居中、脚底落在 feet_pct%
  4. 合成到 --bg 纯色画布，导出 PNG（16:9）

⚠️ 为什么要能换色：图生视频的**首帧背景会被模型继承** —— 首帧绿幕，出来的视频就还是绿幕。
   本猫穿橄榄绿外套，绿幕抠像会绿对绿（吃外套/闪烁/绿边），所以改用**品红 #FF00FF**。
"""
import argparse, os, sys
import numpy as np
from PIL import Image

DEFAULT_BG = "#FF00FF"          # 品红：离角色本色（橄榄绿 145-170°、藏青 227°、粉 330°）都够远


def hex_rgb(s):
    s = s.strip().lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


OK, WARN, BAD = "[OK]", "[!!]", "[XX]"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def rgb_to_hsv(a):
    """a: (H,W,3) float 0-255 → hue(0-360), sat(0-1), val(0-255)"""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    d = mx - mn
    hue = np.zeros_like(mx)
    nz = d > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        hr = np.where(mx == r, ((g - b) / np.where(d == 0, 1, d)) % 6, 0)
        hg = np.where(mx == g, (b - r) / np.where(d == 0, 1, d) + 2, 0)
        hb = np.where(mx == b, (r - g) / np.where(d == 0, 1, d) + 4, 0)
        hue = np.where(mx == r, hr, np.where(mx == g, hg, hb)) * 60.0
    hue = np.where(nz, hue, 0)
    sat = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0)
    return hue % 360, sat, mx


def box_blur(m, r):
    """快速的方框模糊（给 alpha 边缘做羽化，避免依赖 scipy）。"""
    out = m.astype(np.float32)
    for _ in range(r):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0) +
               np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default=None)
    ap.add_argument("--also-720p", default=None, help="额外再导出一个 1280x720 版本")
    ap.add_argument("--height-pct", type=float, default=65.0)
    ap.add_argument("--head-pct", type=float, default=20.0)
    ap.add_argument("--feet-pct", type=float, default=85.0)
    ap.add_argument("--wm-w", type=float, default=0.22, help="左上水印区宽度占比")
    ap.add_argument("--wm-h", type=float, default=0.14, help="左上水印区高度占比")
    ap.add_argument("--hue-tol", type=float, default=18.0, help="背景色相容差（度）。外套是橄榄绿时别调大")
    ap.add_argument("--bg", default=DEFAULT_BG, help="输出背景填充色（hex），默认品红 #FF00FF")
    ap.add_argument("--no-wm", action="store_true", help="不遮罩左上角")
    a = ap.parse_args()
    BG = hex_rgb(a.bg)

    im = Image.open(a.src).convert("RGB")
    W, H = im.size
    arr = np.asarray(im).astype(np.float32)
    print("源图: %s  %dx%d" % (os.path.basename(a.src), W, H))

    # 1) 绿幕判定：先采样背景色相，只在"背景色相 ±容差"内判为绿色背景。
    #    ⚠️ 容差必须窄：本角色的外套是橄榄绿 #3A5D48（色相 ≈144°），
    #    背景纯绿是 120°；窗口一宽就会把外套一起抠掉（这个坑实测踩过）。
    border = np.concatenate([arr[:4].reshape(-1, 3), arr[-4:].reshape(-1, 3),
                             arr[:, :4].reshape(-1, 3), arr[:, -4:].reshape(-1, 3)])
    hue, sat, val = rgb_to_hsv(arr)
    bh, bs, bv = rgb_to_hsv(border.reshape(1, -1, 3))
    bh = bh.ravel()
    rad = np.deg2rad(bh[bs.ravel() >= 0.2]) if (bs.ravel() >= 0.2).any() else np.deg2rad(bh)
    bg_hue = float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360)
    dh = np.abs((hue - bg_hue + 180) % 360 - 180)
    is_bg = (dh <= a.hue_tol) & (sat >= 0.20)
    print("背景色相 %.1f°（采样自四周），判定窗口 ±%.0f°；背景占比 %.1f%%" % (
        bg_hue, a.hue_tol, is_bg.mean() * 100))

    # 2) 显式遮罩左上水印区
    wm = np.zeros_like(is_bg)
    if not a.no_wm:
        wm[:int(H * a.wm_h), :int(W * a.wm_w)] = True
        print("水印遮罩区: %dx%d px（左上 %.0f%% x %.0f%%）" % (int(W * a.wm_w), int(H * a.wm_h), a.wm_w * 100, a.wm_h * 100))

    fg = ~(is_bg | wm)
    ys, xs = np.nonzero(fg)
    if len(xs) == 0:
        print(BAD + " 抠完没有内容了，检查源图背景是否为纯色（绿/品红都可以）")
        return 1
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    print("角色 bbox: x %d-%d  y %d-%d  （%.0f x %.0f px）" % (x0, x1, y0, y1, x1 - x0 + 1, y1 - y0 + 1))
    print("原图构图: 头顶 %.1f%%  脚底 %.1f%%  左 %.1f%%  右 %.1f%%" % (
        y0 / H * 100, (y1 + 1) / H * 100, x0 / W * 100, (x1 + 1) / W * 100))

    # 关键自检：只看"躯干中心"那一小块（bbox 中心、纵向 60~85%）是否被误判成背景。
    # 不要用"bbox 内背景占比"当判据 —— 猫的包围盒里本来就有大量真背景（耳间、腿间、身侧），
    # 那条判据恒为 30%+，只会误导（实测踩过）。
    cy0 = y0 + int((y1 - y0) * 0.60); cy1 = y0 + int((y1 - y0) * 0.85)
    cx0 = x0 + int((x1 - x0) * 0.40); cx1 = x0 + int((x1 - x0) * 0.60)
    torso_bg = is_bg[cy0:cy1, cx0:cx1].mean() * 100
    if torso_bg > 20.0:
        print(BAD + " 躯干中心有 %.1f%% 像素被判成背景 —— 抠像窗口正在吃掉角色本体（换 key 色或收窄容差）" % torso_bg)
    else:
        print(OK + " 躯干中心背景残留 %.1f%%（正常，说明角色本体没被吃掉）" % torso_bg)

    # 3) 抠出角色 RGBA（alpha 做一点羽化，让边缘平滑过渡到背景色，抠像更干净）
    alpha = fg.astype(np.float32)
    alpha = np.clip(box_blur(alpha, 1) * 1.6, 0, 1)
    alpha[wm] = 0
    cat = Image.fromarray(np.dstack([arr, alpha * 255]).astype(np.uint8), "RGBA")
    cat = cat.crop((x0, y0, x1 + 1, y1 + 1))

    def compose(out_path, CW, CH):
        target_h = CH * a.height_pct / 100.0
        scale = target_h / cat.height
        target_w = max(int(round(cat.width * scale)), 1)
        th = max(int(round(target_h)), 1)
        c = cat.resize((target_w, th), Image.LANCZOS)
        canvas = Image.new("RGB", (CW, CH), BG)
        px = int(round(CW / 2 - target_w / 2))
        py = int(round(CH * a.feet_pct / 100.0 - c.height))
        canvas.paste(c, (px, py), c)
        canvas.save(out_path)
        print("\n%s -> %s (%dx%d)  背景 %s" % (OK, out_path, CW, CH, a.bg))
        print("   角色高 %d px = %.1f%% 画幅，头顶 %.1f%%，脚底 %.1f%%，水平居中" % (
            c.height, c.height / CH * 100, py / CH * 100, (py + c.height) / CH * 100))
        a2 = np.asarray(canvas).astype(np.float32)
        d2 = np.sqrt(((a2 - np.array(BG, np.float32)) ** 2).sum(axis=2))
        pure = d2 < 24
        # pure = "整幅里与目标背景色一致的像素"（≈背景面积）；角色内部的同色像素极少
        print("   背景填充 = 纯 %s，占画幅 %.1f%%；其余 %.1f%% 为角色（合成时逐像素保证背景纯净）" % (
            a.bg, pure.mean() * 100, (1 - pure.mean()) * 100))
        return out_path

    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.src)), "ref-magenta-stand.png")
    compose(out, W, H)
    if a.also_720p:
        compose(a.also_720p, 1280, 720)
    return 0


if __name__ == "__main__":
    sys.exit(main())