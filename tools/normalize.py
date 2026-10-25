"""归一化：把 step02 的透明 webm 统一到 dsh-pet 的标准画布。

复刻 dsh-pet scripts/normalize_step03.py 的机制（数值一致，便于混用）：
  · 画布 2160x1215（16:9）、24fps
  · 站立高度统一到 900px（用**首 5 帧 + 末 5 帧**的平均高度算缩放比）
  · 水平居中：用首末帧非透明像素 x 的**中位数**（防止道具把包围盒中心拉偏）
  · 脚底对齐 y=1115（距底 100）
这一步保证不同动画之间切换时，宠物不会忽然变大/变小/挪位。

用法:
    python tools/normalize.py [--in video/step02] [--out video/step03]
"""
import argparse, json, os, re, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffmpeg_path import FFMPEG, FFPROBE  # noqa: E402  （env FFMPEG/FFPROBE → PATH → 常见位置）
OK, WARN, BAD = "[OK]", "[!!]", "[XX]"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CANVAS_W, CANVAS_H = 2160, 1215
TARGET_HEIGHT = 900
FEET_Y = CANVAS_H - 100          # 1115
FPS = 24
HEAD_FRAMES = 5
TAIL_SEEK = "-0.2"
BBOX_RE = re.compile(r"x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)")


def probe_wh(v):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", v],
                       capture_output=True, text=True)
    w, h = (r.stdout or "1280,720").strip().split(",")[:2]
    return int(w), int(h)


def read_alpha(v, W, H, seek=None, frames=None):
    cmd = [FFMPEG, "-v", "error", "-c:v", "libvpx-vp9"]
    if seek:
        cmd += ["-sseof", seek]
    cmd += ["-i", v]
    if frames:
        cmd += ["-frames:v", str(frames)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    p = subprocess.run(cmd, capture_output=True)
    fs = W * H * 4
    n = len(p.stdout) // fs
    out = []
    for i in range(n):
        out.append(np.frombuffer(p.stdout[i * fs:(i + 1) * fs], np.uint8).reshape(H, W, 4)[..., 3])
    return out


def measure_standing(v, W, H):
    alphas = read_alpha(v, W, H, frames=HEAD_FRAMES) + read_alpha(v, W, H, seek=TAIL_SEEK, frames=HEAD_FRAMES)
    heights, max_ys, med_xs = [], [], []
    for a in alphas:
        ys, xs = np.where(a > 10)
        if len(xs) == 0:
            continue
        heights.append(int(ys.max() - ys.min() + 1))
        max_ys.append(int(ys.max()))
        med_xs.append(float(np.median(xs)))
    if not heights:
        raise RuntimeError("没有非透明像素")
    return dict(height=sum(heights) / len(heights),
                max_y=sum(max_ys) / len(max_ys),
                center_x=sum(med_xs) / len(med_xs))


def convert(src, dst, W, H, st):
    scale = TARGET_HEIGHT / st["height"]
    sw = int(W * scale) // 2 * 2
    sh = int(H * scale) // 2 * 2
    ox = CANVAS_W / 2 - st["center_x"] * scale
    oy = FEET_Y - st["max_y"] * scale
    fc = ("color=c=black@0:s=%dx%d:r=%d[bg];"
          "[0:v]scale=%d:%d[sc];"
          "[bg][sc]overlay=%.1f:%.1f:shortest=1,format=yuva420p[v]" % (CANVAS_W, CANVAS_H, FPS, sw, sh, ox, oy))
    subprocess.run([FFMPEG, "-v", "error", "-y", "-c:v", "libvpx-vp9", "-i", src,
                    "-filter_complex", fc, "-map", "[v]", "-an",
                    "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                    "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", dst], check=True)
    return dict(scale=scale, sw=sw, sh=sh, ox=ox, oy=oy)


def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--in", dest="ind", default=os.path.join(root, "video", "step02"))
    ap.add_argument("--out", dest="outd", default=os.path.join(root, "video", "step03"))
    a = ap.parse_args()
    os.makedirs(a.outd, exist_ok=True)

    files = sorted(f for f in os.listdir(a.ind) if f.lower().endswith(".webm"))
    if not files:
        print(BAD + " %s 里没有 webm" % a.ind)
        return 1
    rows = []
    for f in files:
        src = os.path.join(a.ind, f)
        dst = os.path.join(a.outd, f)
        W, H = probe_wh(src)
        st = measure_standing(src, W, H)
        info = convert(src, dst, W, H, st)
        rows.append(dict(name=f, src_h=st["height"], scale=info["scale"], mb=os.path.getsize(dst) / 1e6))
        print("%s %-26s 源站立高 %6.1fpx × %.4f → %dpx；输出 %dx%d，%.2f MB" % (
            OK, f, st["height"], info["scale"], TARGET_HEIGHT, CANVAS_W, CANVAS_H, os.path.getsize(dst) / 1e6))

    # 交叉校验：所有输出量一遍站立高度与脚底位置，必须一致
    print("\n--- 交叉校验（输出再量一次，三者应当一致）---")
    print("  %-26s %8s %8s %9s" % ("文件", "站立高px", "脚底y", "水平中位x"))
    for f in files:
        dst = os.path.join(a.outd, f)
        st = measure_standing(dst, CANVAS_W, CANVAS_H)
        print("  %-26s %8.1f %8.1f %9.1f" % (f, st["height"], st["max_y"] + 1, st["center_x"]))
    with open(os.path.join(a.outd, "_report.json"), "w", encoding="utf-8") as fp:
        json.dump(rows, fp, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())