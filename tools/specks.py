# -*- coding: utf-8 -*-
# 清除成品 webm 里「不与主体连通的品红残留小块」(水印边晕/抠像漏网)
# 用法: python tools/specks.py <webm> [--dry] [--out x.webm]
import argparse, os, shutil, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from matte_util import main_component
from ffmpeg_path import FFMPEG as FF, FFPROBE as FP  # noqa: E402  （env FFMPEG/FFPROBE → PATH → 常见位置）
def pr(v, e):
    return (subprocess.run([FP,"-v","error","-select_streams","v:0","-show_entries",e,"-of","csv=p=0",v],capture_output=True,text=True).stdout or "").strip()
def wh(v):
    a = pr(v,"stream=width,height").split(","); return int(a[0]), int(a[1])
def fps(v):
    s = pr(v,"stream=r_frame_rate")
    try:
        n,d = s.split("/"); f = float(n)/float(d)
    except Exception:
        f = 24.0
    return f if 1 <= f <= 240 else 24.0

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("--out")
ap.add_argument("--dry", action="store_true")
ap.add_argument("--hue-tol", type=float, default=40.0)
ap.add_argument("--sat-min", type=float, default=0.35)
ap.add_argument("--wipe", help="x0,y0,x1,y1 rect wipe")
ap.add_argument("--min-alpha", type=int, default=128, help="视为前景的 alpha 门槛；水印残影常是半透明，配合低值可彻底清掉")
ap.add_argument("--corners-only", action="store_true", help="只在四个角内清理（水印专用，最不误伤）")
ap.add_argument("--anywhere", action="store_true", help="不加边缘限制（默认只在四边带内清，保护中间的特效）")
ap.add_argument("--edge-frac", type=float, default=0.12)
a = ap.parse_args()

W, H = wh(a.src)
F = fps(a.src)
print("输入 %s  %dx%d  %.2ffps" % (os.path.basename(a.src), W, H, F))
pi = subprocess.Popen([FF,"-v","error","-c:v","libvpx-vp9","-i",a.src,
                       "-f","rawvideo","-pix_fmt","rgba","-"], stdout=subprocess.PIPE)
dst = a.out or (os.path.splitext(a.src)[0] + ".cleaned.webm")
po = None
if not a.dry:
    po = subprocess.Popen([FF,"-v","error","-y","-f","rawvideo","-pix_fmt","rgba",
                           "-s","%dx%d" % (W,H), "-r","%.4f" % F, "-i","-","-an",
                           "-c:v","libvpx-vp9","-pix_fmt","yuva420p","-crf","30",
                           "-b:v","0","-auto-alt-ref","0","-deadline","good",
                           "-cpu-used","4", dst], stdin=subprocess.PIPE)

fs = W * H * 4
n = 0; tot = 0; aff = []
while True:
    buf = b""
    while len(buf) < fs:
        c = pi.stdout.read(fs - len(buf))
        if not c: break
        buf += c
    if len(buf) < fs: break
    fr = np.frombuffer(buf, np.uint8).reshape(H, W, 4).copy()
    al = fr[..., 3]
    rgb = fr[..., :3].astype(np.float32)
    mx = rgb.max(2); mn = rgb.min(2); d = mx - mn
    r, g, b = rgb[...,0], rgb[...,1], rgb[...,2]
    dz = np.where(d == 0, 1, d)
    hue = np.where(mx == r, ((g-b)/dz) % 6,
                   np.where(mx == g, (b-r)/dz + 2, (r-g)/dz + 4)) * 60
    sat = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0)
    dh = np.abs((hue - 298 + 180) % 360 - 180)
    mag = (dh <= a.hue_tol) & (sat >= a.sat_min)
    if not a.anywhere:
        eb = np.zeros((H, W), bool)
        fw = max(4, int(a.edge_frac * W)); fh = max(4, int(a.edge_frac * H))
        if a.corners_only:
            eb[:fh, :fw] = True; eb[:fh, -fw:] = True
            eb[-fh:, :fw] = True; eb[-fh:, -fw:] = True
        else:
            eb[:fh, :] = True; eb[-fh:, :] = True; eb[:, :fw] = True; eb[:, -fw:] = True
        mag = mag & eb
    vis = al > a.min_alpha
    if vis.any():
        k = vis & ~main_component(vis) & mag
        c = int(k.sum())
        if c:
            fr[k, 3] = 0
            fr[k, 0] = fr[k, 1] = fr[k, 2] = 0
            tot += c; aff.append((n, c))
    if a.wipe:
        x0, y0, x1, y1 = [int(v) for v in a.wipe.split(",")]
        fr[y0:y1, x0:x1, 3] = 0
        fr[y0:y1, x0:x1, 0] = fr[y0:y1, x0:x1, 1] = fr[y0:y1, x0:x1, 2] = 0
    if po is not None:
        po.stdin.write(fr.tobytes())
    n += 1

pi.stdout.close(); pi.wait()
rc = 0
if po is not None:
    po.stdin.close(); rc = po.wait()
print("处理 %d 帧；共清除 %d px；涉及 %d 帧" % (n, tot, len(aff)))
if aff:
    print("  清除最多: %s" % ", ".join("%d帧(%dpx)" % x for x in sorted(aff, key=lambda y: -y[1])[:6]))
if a.dry:
    print("(dry: 未写文件)")
    sys.exit(0)
if rc != 0:
    print("编码失败"); sys.exit(1)
print("输出: %s (%.2f MB)" % (dst, os.path.getsize(dst) / 1e6))
if not a.out:
    bak = a.src + ".orig"
    if not os.path.exists(bak):
        shutil.copy2(a.src, bak)
    shutil.copy2(dst, a.src)
    os.remove(dst)
    print("已覆盖: %s" % os.path.basename(a.src))
