# -*- coding: utf-8 -*-
"""把「已带 alpha 的素材」直接贴合到播放规格（640x360），只重采样一次。

为什么不用 normalize.py + encode_playback.py 两步：
  那两步是给「AI 直出的 1280x720 品红底」用的（先抠像 → 放大到 2160x1215 统一画布
  → 再缩到 640x360）。用户自己抠好的素材通常已经是最终尺寸（甚至就是 640x360），
  再走那条路会「放大再缩小」，多一次重采样、白掉一点清晰度。
  这里改成：量出源素材的站立高/脚底/中心 → 直接算缩放与偏移 → 一次渲染到 640x360。

规格（与 normalize.py 同一套，换算到 640x360）：
  站立高度 = 900 × 360/1215 = 266.67 px
  脚底 y   = 1115 × 360/1215 = 330.37 px
  中心 x   = 1080 × 360/2160 = 320 px

贴合方式：等比缩放后，若比画布大就居中裁剪（裁掉的都是透明背景），
否则用透明边补齐。

用法：
    python tools/fit_playback.py <in> <out.webm> [--crf 30] [--no-unsharp]
    python tools/fit_playback.py <in> <out.webm> --check     # 只量不渲染
"""
import argparse
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ffmpeg_path import FFMPEG, FFPROBE  # noqa: E402  （env FFMPEG/FFPROBE → PATH → 常见位置）

CANVAS_W, CANVAS_H = 2160, 1215
TARGET_H = 900.0
FEET_Y = 1115.0
OUT_W, OUT_H = 640, 360
TARGET_H_OUT = TARGET_H * OUT_H / CANVAS_H      # 266.67
FEET_Y_OUT = FEET_Y * OUT_H / CANVAS_H          # 330.37
CENTER_X_OUT = CANVAS_W / 2 * OUT_W / CANVAS_W  # 320.0

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
        n, d = s.split("/") if "/" in s else (s, 1)
        f = float(n) / float(d) if float(d) else 30.0
    except Exception:
        f = 30.0
    return f if 1 <= f <= 240 else 30.0


def has_alpha(v):
    """是否带 alpha —— 必须**实测**，不能信 ffprobe。

    坑：VP9 把 alpha 存在单独的平面里，ffprobe 常把这类文件报成 `yuv420p`；
    反过来，读 RGBA 时若不强制 `-c:v libvpx-vp9`，ffmpeg 会选到不含 alpha 的
    解码路径，读出来 alpha 全是 255 —— 两种误判都实测踩过。
    所以这里直接解一帧看 alpha 是否真的有 0 与非 0。
    """
    W, H = probe_wh(v)
    pre = ["-c:v", "libvpx-vp9"] if v.lower().endswith(".webm") else []
    r = subprocess.run([FFMPEG, "-v", "error"] + pre + ["-ss", "0.5", "-i", v,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                       capture_output=True)
    if len(r.stdout) < W * H * 4:
        return False
    al = np.frombuffer(r.stdout[:W * H * 4], np.uint8).reshape(H, W, 4)[..., 3]
    return bool(al.min() < 10 and al.max() > 245)


def grab_rgba(v, t, W, H):
    # webm 必须强制 libvpx-vp9 解码器，否则读不到 alpha（见 has_alpha 注释）
    pre = ["-c:v", "libvpx-vp9"] if v.lower().endswith(".webm") else []
    r = subprocess.run([FFMPEG, "-v", "error"] + pre + ["-ss", "%.3f" % t, "-i", v,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                       capture_output=True)
    if len(r.stdout) < W * H * 4:
        return None
    return np.frombuffer(r.stdout[:W * H * 4], np.uint8).reshape(H, W, 4)


def measure(v, dur, W, H, n_probe=5):
    """按 normalize.py 的口径量：取首尾各 n_probe 帧，用不透明掩码算站立高/脚底/中心。"""
    fps = probe_fps(v)
    step = 1.0 / max(fps, 1)
    times = [i * step for i in range(n_probe)] + \
            [max(0.0, dur - (i + 1) * step) for i in range(n_probe)]
    hs, feets, cxs = [], [], []
    for t in times:
        a = grab_rgba(v, t, W, H)
        if a is None:
            continue
        vis = a[..., 3] > 128
        if vis.sum() < 50:
            continue
        ys, xs = np.nonzero(vis)
        hs.append(ys.max() - ys.min() + 1)
        feets.append(ys.max())
        cxs.append(np.median(xs))
    if not hs:
        return None
    return {"h": float(np.median(hs)), "feet": float(np.median(feets)),
            "cx": float(np.median(cxs)), "frames": len(hs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?", help="输出 webm（--check 时可省略）")
    ap.add_argument("--crf", type=int, default=30)
    ap.add_argument("--no-unsharp", action="store_true")
    ap.add_argument("--fps", type=int, default=24, help="输出帧率（0=保持源帧率）；包内统一 24fps")
    ap.add_argument("--check", action="store_true", help="只量不渲染")
    a = ap.parse_args()

    W, H = probe_wh(a.src)
    fps = probe_fps(a.src)
    dur = float(probe(a.src, "format=duration") or 0)
    alpha = has_alpha(a.src)
    print("输入 %s  %dx%d  %.2ffps  %.2fs  alpha=%s" % (
        os.path.basename(a.src), W, H, fps, dur, "有" if alpha else "**没有**"))

    m = measure(a.src, dur, W, H)
    if m is None:
        print("[XX] 量不到前景（全透明？）")
        return 1
    print("  实测: 站立高 %.1f  脚底 y %.1f  中心 x %.1f  （%d 帧取样）" % (
        m["h"], m["feet"], m["cx"], m["frames"]))

    # 目标值按源分辨率换算（规格是相对 2160x1215 画布定义的）
    # 目标值必须按**输出**像素算（640x360 的规格），不能按源分辨率换算。
    # 之前写成 TARGET_H * H / CANVAS_H：源也是 640x360 时恰好等价，所以一直没暴露；
    # 换成 854x480 的源就错了（站立高算成 355.6 而不是 266.7 -> 成品大 24%）。
    tgt_h = TARGET_H_OUT
    tgt_feet = FEET_Y_OUT
    tgt_cx = CENTER_X_OUT
    s = tgt_h / m["h"]
    print("  目标(按源分辨率): 站立高 %.1f  脚底 y %.1f  中心 x %.1f" % (tgt_h, tgt_feet, tgt_cx))
    print("  需要: 缩放 ×%.4f" % s)

    if a.check:
        return 0

    if not alpha:
        print("[XX] 源没有 alpha 通道 —— 请重新导出带 alpha 的版本（PNG 序列 / VP9-alpha webm / ProRes 4444 mov）")
        return 1
    if not a.dst:
        print("[XX] 缺少输出路径")
        return 1

    sw, sh = int(round(W * s / 2)) * 2, int(round(H * s / 2)) * 2   # 保持偶数
    dx = int(round(CENTER_X_OUT - m["cx"] * s))
    dy = int(round(FEET_Y_OUT - m["feet"] * s))
    print("  缩放后 %dx%d，位移 dx=%d dy=%d" % (sw, sh, dx, dy))

    # 缩放后比画布大 → 裁掉多余（都是透明背景）；小 → 用透明边补齐
    if sw >= OUT_W and sh >= OUT_H:
        cx0 = int(round(m["cx"] * s - CENTER_X_OUT))
        cy0 = int(round(m["feet"] * s - FEET_Y_OUT))
        cx0 = max(0, min(sw - OUT_W, cx0))
        cy0 = max(0, min(sh - OUT_H, cy0))
        tail = "crop=%d:%d:%d:%d" % (OUT_W, OUT_H, cx0, cy0)
    else:
        px = max(0, min(OUT_W - sw, dx))
        py = max(0, min(OUT_H - sh, dy))
        tail = "pad=%d:%d:%d:%d:color=0x00000000" % (OUT_W, OUT_H, px, py)

    chain = "scale=%d:%d:flags=lanczos,%s" % (sw, sh, tail)
    if a.fps:
        chain += ",fps=%d" % a.fps
    if not a.no_unsharp:
        chain += ",unsharp=3:3:0.6:3:3:0"
    print("  滤镜链: %s" % chain)

    os.makedirs(os.path.dirname(os.path.abspath(a.dst)) or ".", exist_ok=True)
    cmd = [FFMPEG, "-v", "error", "-y", "-i", a.src, "-an", "-vf", chain,
           "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", str(a.crf),
           "-b:v", "0", "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", a.dst]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("[XX] 渲染失败: %s" % (r.stderr or "")[-400:])
        return 1
    print("[OK] 输出 %s (%.2f MB)" % (a.dst, os.path.getsize(a.dst) / 1e6))

    m2 = measure(a.dst, dur, OUT_W, OUT_H)
    if m2:
        print("  交叉校验: 站立高 %.1f (目标 %.1f)  脚底 y %.1f (目标 %.1f)  中心 x %.1f (目标 %.1f)" % (
            m2["h"], TARGET_H_OUT, m2["feet"], FEET_Y_OUT, m2["cx"], CENTER_X_OUT))
        ok = abs(m2["h"] - TARGET_H_OUT) <= 3 and abs(m2["feet"] - FEET_Y_OUT) <= 3 \
             and abs(m2["cx"] - CENTER_X_OUT) <= 4
        print("  结论: %s" % ("贴合成功 ✓" if ok else "仍有偏差，需人工检查"))
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())