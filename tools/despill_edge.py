# -*- coding: utf-8 -*-
# 边缘去溢色（品红版 despill）：只修轮廓外圈 1-2px 的品红污染，不动猫身内部。
# 原理：品红溢色 = G 通道被压低（R、B 偏高）。把 G 抬到 min(R,B) 即可中和。
# 保护：只在「色相 298±35° 且饱和>=0.2」时才修 → 猫的粉耳朵(~340°)在窗口外，不会被误改。
# 用法: python tools/despill_edge.py <webm> [--ring 2] [--strength 1.0] [--dry]
import argparse, os, shutil, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from matte_util import _dilate, reconstruct
from PIL import Image, ImageFilter
from ffmpeg_path import FFMPEG as FF, FFPROBE as FP  # noqa: E402  （env FFMPEG/FFPROBE → PATH → 常见位置）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

def pr(v, e):
    return (subprocess.run([FP,"-v","error","-select_streams","v:0","-show_entries",e,"-of","csv=p=0",v],
            capture_output=True,text=True).stdout or "").strip()

def wh(v):
    a = pr(v,"stream=width,height").split(","); return int(a[0]), int(a[1])

def fps(v):
    s = pr(v,"stream=r_frame_rate")
    try:
        n,d = s.split("/"); f = float(n)/float(d)
    except Exception:
        f = 24.0
    return f if 1 <= f <= 240 else 24.0

BG_HUE = 298.0

def magenta_ness(rgb):
    mx = rgb.max(2); mn = rgb.min(2); d = mx - mn
    r_, g_, b_ = rgb[...,0], rgb[...,1], rgb[...,2]
    dz = np.where(d == 0, 1, d)
    hue = np.where(mx == r_, ((g_-b_)/dz) % 6,
                   np.where(mx == g_, (b_-r_)/dz + 2, (r_-g_)/dz + 4)) * 60
    sat = np.where(mx > 0, d/np.maximum(mx,1e-6), 0)
    dh = np.abs((hue - BG_HUE + 180) % 360 - 180)
    return (dh <= 35) & (sat >= 0.20)

def fix_frame(a4, ring_px, strength, bleed=2, kill_black=-1, protect=3, alpha_open=0, alpha_feather=0.0):
    al = a4[...,3]
    rgb = a4[...,:3].astype(np.float32)
    # (1) 边界去溢色：G 抬到 min(R,B)
    ring = _dilate(al < 8, ring_px) & (al >= 8)
    k = 0
    if ring.any():
        mn_rb = np.minimum(rgb[...,0], rgb[...,2])
        spill = ring & magenta_ness(rgb) & (rgb[...,1] < mn_rb - 1.0)
        k = int(spill.sum())
        if k:
            need = mn_rb - rgb[...,1]
            rgb[...,1] = np.where(spill, rgb[...,1] + need*strength, rgb[...,1])
    # (1.5) 清除「与透明区连通的不透明黑块」——用户导出的素材常见（抠图没抠净，留成实心黑）
    if kill_black >= 0:
        mxv = rgb.max(2)
        blackish = mxv <= kill_black
        seed = al < 8
        blob = reconstruct(blackish, seed, max_iter=2000)
        if protect > 0:
            bright = mxv > (kill_black + 25)
            blob = blob & ~_dilate(bright, protect)
        nk = int(blob.sum())
        if nk:
            rgb[blob] = 0
            al = al.copy(); al[blob] = 0
            a4[...,3] = al
    # (1.8) alpha 形态学开运算：切掉蒙版毛刺（用户手抠常见边缘锯齿），再羽化 1px 补回抗锯齿
    if alpha_open > 0 or alpha_feather > 0:
        im = Image.fromarray(al, "L")
        if alpha_open > 0:
            k = 2 * int(alpha_open) + 1
            im = im.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))
        if alpha_feather > 0:
            im = im.filter(ImageFilter.GaussianBlur(float(alpha_feather)))
        al = np.asarray(im)
        a4[...,3] = al
    # (2) 透明侧颜色外渗：透明像素的 RGB 仍带品红，4:2:0 色度下采样会把它平均回边缘。
    #     透明像素视觉上不可见，所以把它的 RGB 换成邻近不透明色即可，代价为零。
    if bleed > 0:
        op = (al >= 8).astype(np.float32)
        near = _dilate(al >= 8, bleed) & (al < 8)
        if near.any() and op.any():
            den = np.asarray(Image.fromarray((op*255).astype(np.uint8), "L")
                             .filter(ImageFilter.BoxBlur(bleed)), np.float32)/255.0
            den = np.maximum(den, 1e-6)
            for c in range(3):
                num = np.asarray(Image.fromarray(np.clip(rgb[...,c]*op, 0, 255).astype(np.uint8), "L")
                                 .filter(ImageFilter.BoxBlur(bleed)), np.float32)
                rgb[...,c] = np.where(near, num/den, rgb[...,c])
    a4[...,:3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return k


ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("--out")
ap.add_argument("--kill-black", type=int, default=-1, help="亮度<=此值且与透明区连通的区域清成透明（如 45）")
ap.add_argument("--alpha-open", type=int, default=0, help="alpha 开运算半径（切毛刺）")
ap.add_argument("--alpha-feather", type=float, default=0.0, help="alpha 羽化半径（补抗锯齿）")
ap.add_argument("--protect", type=int, default=3, help="保护靠近亮部的暗色（描边/眼睛）的半径")
ap.add_argument("--ring", type=int, default=2, help="边界环宽度（像素）")
ap.add_argument("--strength", type=float, default=1.0)
ap.add_argument("--bleed", type=int, default=2, help="透明侧颜色外渗宽度（抵消 4:2:0 色度回拉）")
ap.add_argument("--dry", action="store_true")
a = ap.parse_args()

W, H = wh(a.src); F = fps(a.src)
print("输入 %s  %dx%d  %.2ffps" % (os.path.basename(a.src), W, H, F))
pi = subprocess.Popen([FF,"-v","error","-c:v","libvpx-vp9","-i",a.src,
                       "-f","rawvideo","-pix_fmt","rgba","-"], stdout=subprocess.PIPE)
dst = a.out or (os.path.splitext(a.src)[0] + ".despilled.webm")
po = None
if not a.dry:
    po = subprocess.Popen([FF,"-v","error","-y","-f","rawvideo","-pix_fmt","rgba",
                           "-s","%dx%d" % (W,H), "-r","%.4f" % F, "-i","-","-an",
                           "-c:v","libvpx-vp9","-pix_fmt","yuva420p","-crf","30",
                           "-b:v","0","-auto-alt-ref","0","-deadline","good",
                           "-cpu-used","4", dst], stdin=subprocess.PIPE)
fs = W*H*4; n = 0; tot = 0; aff = []
while True:
    b = b""
    while len(b) < fs:
        c = pi.stdout.read(fs - len(b))
        if not c: break
        b += c
    if len(b) < fs: break
    fr = np.frombuffer(b, np.uint8).reshape(H, W, 4).copy()
    k = fix_frame(fr, a.ring, a.strength, a.bleed, a.kill_black, a.protect, a.alpha_open, a.alpha_feather)
    if k:
        tot += k; aff.append((n, k))
    if po is not None:
        po.stdin.write(fr.tobytes())
    n += 1
pi.stdout.close(); pi.wait()
rc = 0
if po is not None:
    po.stdin.close(); rc = po.wait()
print("处理 %d 帧；修正 %d px；涉及 %d 帧" % (n, tot, len(aff)))
if aff:
    print("  修正最多: %s" % ", ".join("%d帧(%dpx)" % x for x in sorted(aff, key=lambda y: -y[1])[:6]))
if a.dry:
    print("(dry: 未写文件)"); sys.exit(0)
if rc != 0:
    print("编码失败"); sys.exit(1)
print("输出: %s (%.2f MB)" % (dst, os.path.getsize(dst)/1e6))
if not a.out:
    bak = a.src + ".predespill"
    if not os.path.exists(bak): shutil.copy2(a.src, bak)
    shutil.copy2(dst, a.src); os.remove(dst)
    print("已覆盖: %s" % os.path.basename(a.src))
