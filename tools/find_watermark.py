# -*- coding: utf-8 -*-
# 检测「静止的水印残留」：水印位置固定、角色每帧在动 -> 用 alpha 的时间稳定性来分离。
# 判据：某像素在整段里 alpha 均值>阈值 且 标准差很小（静止） 且 位于画面边缘带。
# 只输出候选像素的统计与预览，不修改文件；加 --apply 才落盘。
# 用法: python tools/find_watermark.py <webm或目录> [--band 0.22] [--std-max 6] [--min-alpha 8] [--apply]
import argparse, glob, os, shutil, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

def analyze(path, band=0.22, std_max=6.0, min_alpha=8, step=2):
    W, H = wh(path)
    fs = W * H * 4
    p = subprocess.Popen([FF,"-v","error","-c:v","libvpx-vp9","-i",path,
                          "-f","rawvideo","-pix_fmt","rgba","-"], stdout=subprocess.PIPE)
    n = 0
    s1 = np.zeros((H, W), np.float64)
    s2 = np.zeros((H, W), np.float64)
    last = None
    while True:
        b = b""
        while len(b) < fs:
            c = p.stdout.read(fs - len(b))
            if not c: break
            b += c
        if len(b) < fs: break
        if n % step == 0:
            a = np.frombuffer(b, np.uint8).reshape(H, W, 4)[..., 3].astype(np.float64)
            s1 += a; s2 += a * a; last = a
        n += 1
    p.stdout.close(); p.wait()
    k = max(1, (n + step - 1) // step)
    mean = s1 / k
    var = np.maximum(s2 / k - mean * mean, 0.0)
    std = np.sqrt(var)
    # 边缘带
    # 只扫四个角：水印都在角上。之前用「四边带」会把底边带压在猫脚上
    #（脚底 y=330 最稳不动），结果把猫脚当成了水印。
    band_mask = np.zeros((H, W), bool)
    bw = max(4, int(band * W)); bh = max(4, int(band * H))
    band_mask[:bh, :bw] = True          # 左上
    band_mask[:bh, -bw:] = True         # 右上
    band_mask[-bh:, :bw] = True         # 左下
    band_mask[-bh:, -bw:] = True        # 右下
    static = (mean > min_alpha) & (std < std_max) & band_mask
    return static, mean, std, (W, H), n

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--band", type=float, default=0.22)
    ap.add_argument("--std-max", type=float, default=6.0)
    ap.add_argument("--min-alpha", type=int, default=8)
    ap.add_argument("--apply", action="store_true", help="真的抹掉（不指定则只报告）")
    ap.add_argument("--preview-dir", default=None)
    a = ap.parse_args()

    files = []
    if os.path.isdir(a.target):
        files = sorted(glob.glob(os.path.join(a.target, "*.webm")))
    else:
        files = [a.target]

    for p in files:
        try:
            static, mean, std, (W, H), n = analyze(p, a.band, a.std_max, a.min_alpha)
        except Exception as e:
            print("  %-22s 分析失败: %s" % (os.path.basename(p)[:-5], e)); continue
        cnt = int(static.sum())
        name = os.path.basename(p)[:-5]
        if cnt == 0:
            print("  %-22s 无水印残留候选" % name); continue
        ys, xs = np.nonzero(static)
        print("  %-22s 候选 %5d px   bbox x[%d-%d] y[%d-%d]  (画面 %dx%d, 帧数 %d)" % (
            name, cnt, xs.min(), xs.max(), ys.min(), ys.max(), W, H, n))
        if a.preview_dir:
            from PIL import Image, ImageDraw
            os.makedirs(a.preview_dir, exist_ok=True)
            # 用第一帧做底，标出会被抹掉的像素（红）
            q = subprocess.run([FF,"-v","error","-c:v","libvpx-vp9","-ss","0.5","-i",p,"-frames:v","1",
                                "-f","rawvideo","-pix_fmt","rgba","-"], capture_output=True)
            if len(q.stdout) >= W*H*4:
                a4 = np.frombuffer(q.stdout[:W*H*4], np.uint8).reshape(H, W, 4).copy()
                a4[static] = [255, 0, 0, 255]
                im = Image.fromarray(a4, "RGBA")
                bg = Image.new("RGB", (W, H), (245, 245, 245)); bg.paste(im, (0, 0), im)
                out = os.path.join(a.preview_dir, name + ".wm_preview.png"); bg.save(out)

if __name__ == "__main__":
    main()
