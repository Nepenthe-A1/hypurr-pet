"""播放变体：2160x1215 的 step03 → 640x360 的 step04（插件实际播放的尺寸）。

对应 dsh-pet 的 scripts/encode_thumbs.py 那一步。体积能降到 1/6 左右，
桌宠显示尺寸本来就只有 100~200px，没必要让它实时解码 2160 宽的 VP9。

用法:
    python tools/encode_playback.py [--in video/step03] [--out video/step04] [--w 640] [--h 360]
"""
import argparse, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffmpeg_path import FFMPEG  # noqa: E402  （env FFMPEG → PATH → 常见位置）
OK, BAD = "[OK]", "[XX]"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="ind", default=os.path.join(root, "video", "step03"))
    ap.add_argument("--out", dest="outd", default=os.path.join(root, "video", "step04"))
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=360)
    ap.add_argument("--crf", type=int, default=30)
    ap.add_argument("--unsharp", default="3:3:0.6:3:3:0",
                    help="轻微提锐。源素材被归一化放大约 1.9 倍，软度会被同步放大，"
                         "所以在最后这一步补一点锐度；置空则不提锐")
    ap.add_argument("--scale-flags", default="lanczos")
    a = ap.parse_args()
    os.makedirs(a.outd, exist_ok=True)
    files = sorted(f for f in os.listdir(a.ind) if f.lower().endswith(".webm"))
    if not files:
        print(BAD + " %s 里没有 webm" % a.ind)
        return 1
    chain = "scale=%d:%d:flags=%s" % (a.w, a.h, a.scale_flags)
    if a.unsharp:
        chain += ",unsharp=" + a.unsharp
    print("滤镜链: %s   CRF=%d" % (chain, a.crf))
    for f in files:
        src, dst = os.path.join(a.ind, f), os.path.join(a.outd, f)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-c:v", "libvpx-vp9", "-i", src,
                        "-vf", chain, "-an",
                        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                        "-crf", str(a.crf), "-b:v", "0", "-auto-alt-ref", "0",
                        "-deadline", "good", "-cpu-used", "4", dst], check=True)
        print("%s %-26s %.2f MB → %.2f MB" % (OK, f, os.path.getsize(src) / 1e6, os.path.getsize(dst) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())