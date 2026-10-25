# -*- coding: utf-8 -*-
"""从「抠好图但导成了不透明底色」的文件还原透明通道（VP9-alpha webm）。

背景：mp4/h265 这类容器通常装不下 alpha。在剪辑软件里抠完再导出成 mp4/mov 时，
透明区域会被压成**纯黑**（实测四角 #000000）。alpha 并没有完全丢：
    「直通 alpha 合成到黑底」：out = color × alpha
    → alpha=1 的像素颜色原样保留（深色外套仍是原色）
    → 只有半透明的抗锯齿过渡被压暗

关键难点：**不能按亮度算 alpha**。猫的墨线描边本身就是深色（实测 #0D191D 一档），
按亮度算会把它判成透明 → 描边被吃掉、猫变成"缺一圈边"。
所以用**连通域**区分两种黑：
    · 与画幅边缘连通的黑色 = 真背景 → alpha 0
    · 靠近亮部（前景）的黑色 = 墨线/描边 → alpha 255（保住）

性能：形态学重建在全分辨率逐轮膨胀会很慢（大背景要几百轮）。
所以先在 factor 倍降采样上完成重建，再回原分辨率做少量轮次细化
（与 matte_util.main_component 同一套路）。

用法：
    python tools/key_from_black.py <in.mp4> <out.webm> [--dark-thresh 30] [--protect 2] [--fps 24]
"""
import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from matte_util import _dilate, reconstruct  # noqa: E402

from ffmpeg_path import FFMPEG, FFPROBE  # noqa: E402  （env FFMPEG/FFPROBE → PATH → 常见位置）
OK, BAD = "[OK]", "[XX]"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass


def probe(v, entries):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", entries, "-of", "csv=p=0", v],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").strip()


def probe_wh(v):
    w, h = probe(v, "stream=width,height").split(",")[:2]
    return int(w), int(h)


def probe_fps(v):
    s = probe(v, "stream=r_frame_rate")
    try:
        if "/" in s:
            n, d = s.split("/")
            f = float(n) / float(d) if float(d) else 30.0
        else:
            f = float(s)
    except Exception:
        f = 30.0
    return f if 1 <= f <= 240 else 30.0


def border_seed(shape):
    seed = np.zeros(shape, bool)
    seed[0, :] = seed[-1, :] = True
    seed[:, 0] = seed[:, -1] = True
    return seed


def bg_from_border(dark, seed, factor=4, refine=16):
    """与画幅边缘连通的暗色区域（= 真背景）。降采样加速 + 原分辨率细化。"""
    h, w = dark.shape
    small = dark[::factor, ::factor]
    sseed = seed[::factor, ::factor]
    comp_small = reconstruct(small, sseed)
    comp = np.repeat(np.repeat(comp_small, factor, axis=0), factor, axis=1)[:h, :w]
    comp = comp & dark
    if refine > 0:
        comp = reconstruct(dark, comp, max_iter=refine)
    return comp


def alpha_from_black(arr, seed, dark_thresh=30, protect=2, factor=4, refine=16):
    """返回 (alpha uint8, 统计信息 dict)。"""
    arrf = arr.astype(np.float32)
    mx = arrf.max(axis=2)
    dark = mx <= dark_thresh
    bg = bg_from_border(dark, seed, factor=factor, refine=refine)

    # 保护墨线：靠近亮部的暗像素不能当背景（否则描边被吃掉）
    bright = ~dark
    if protect > 0:
        bg = bg & ~_dilate(bright, protect)

    alpha = np.where(bg, 0, 255).astype(np.uint8)
    return alpha, {"bg": float(bg.mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--dark-thresh", type=int, default=30)
    ap.add_argument("--protect", type=int, default=2, help="保护墨线的半径（像素）")
    ap.add_argument("--factor", type=int, default=4, help="重建降采样倍率")
    ap.add_argument("--refine", type=int, default=16, help="原分辨率细化轮次")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--keep-fps", action="store_true")
    a = ap.parse_args()

    W, H = probe_wh(a.src)
    src_fps = probe_fps(a.src)
    print("输入 %s  %dx%d  %.2ffps" % (os.path.basename(a.src), W, H, src_fps))
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)) or ".", exist_ok=True)

    p_in = subprocess.Popen([FFMPEG, "-v", "error", "-i", a.src,
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            stdout=subprocess.PIPE)
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
           "-s", "%dx%d" % (W, H), "-r", "%.4f" % src_fps, "-i", "-", "-an"]
    if not a.keep_fps:
        cmd += ["-vf", "fps=%d" % a.fps]
    cmd += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "30", "-b:v", "0",
            "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", a.dst]
    p_out = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    fs = W * H * 3
    n = 0
    acc_bg = 0.0
    seed = border_seed((H, W))
    while True:
        buf = b""
        while len(buf) < fs:
            chunk = p_in.stdout.read(fs - len(buf))
            if not chunk:
                break
            buf += chunk
        if len(buf) < fs:
            break
        arr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        alpha, st = alpha_from_black(arr, seed, a.dark_thresh, a.protect, a.factor, a.refine)
        acc_bg += st["bg"]
        p_out.stdin.write(np.dstack([arr, alpha]).tobytes())
        n += 1
        if n % 24 == 0:
            print("  已处理 %d 帧" % n)

    p_in.stdout.close(); p_in.wait()
    p_out.stdin.close(); rc = p_out.wait()
    if n:
        print("%s 完成 %d 帧；判定背景 %.1f%%" % (OK if rc == 0 else BAD, n, acc_bg / n * 100))
    print("输出: %s (%.2f MB)" % (a.dst, os.path.getsize(a.dst) / 1e6 if os.path.exists(a.dst) else 0))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())