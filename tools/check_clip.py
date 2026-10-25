"""素材自检：拿 dsh-pet 素材链的规格去验收每一条生成的绿幕视频。

用法:
    python tools/check_clip.py <video.mp4> [--out <预览目录>]

检查项（依据 dsh-pet 的 scripts/normalize_step03.py 与 chroma_step02.py）:
  1. 分辨率 / 帧率 / 时长 / 有无音轨
  2. 绿幕基准色是否均匀（抠像按 HSV 色相自适应，色差过大才会出问题）
  3. 角色构图：头顶 ≈20%、脚底 ≈85%、高度 ≈65%、左右居中
  4. 逐帧漂移：水平/垂直中心、角色高度是否稳定（漂移会让归一化对不齐）
  5. 安全区：内容是否触碰/超出画幅（会被裁切）
  6. 四角异物（水印等）
  7. 首帧 vs 末帧差异（锚点是否一致——素材链靠首末帧算缩放与对位）
"""
import subprocess, argparse, os, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from matte_util import main_component  # noqa: E402

from ffmpeg_path import FFMPEG, FFPROBE  # noqa: E402  （env FFMPEG/FFPROBE → PATH → 常见位置）

SW, SH = 160, 90          # 缩略扫描尺寸
DIST = 70                 # 与绿幕基准色的距离阈值
IGNORE_TL = True          # 忽略左上角水印区（即梦/剪映会在左上角打"AI 生成"水印）
TL_W, TL_H = 0.22, 0.14   # 忽略区：宽 22%、高 14%
OK, WARN, BAD = "[OK]", "[!!]", "[XX]"

# Windows 控制台常是 GBK，强制 UTF-8 输出，避免中文/符号报 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def probe(v):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames",
                        "-show_entries", "format=duration,size", "-of", "json", v],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    import json
    return json.loads(r.stdout)


def real_frames(v):
    """真实帧数。⚠️ 容器的 nb_frames 常是错的（即梦标称 121 帧 / 声明 60fps，实际 24fps）。"""
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
                        "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", v],
                       capture_output=True, text=True)
    try:
        return int((r.stdout or "0").strip())
    except Exception:
        return 0


def scan(v):
    """缩放后逐帧扫描，返回每帧的角色 bbox/中心（百分比制）。

    关键：只量"与角色主体连通"的那一块（matte_util.main_component），
    否则水印/光柱/飘落碎屑会把包围盒撑大，量出来的构图全是错的。
    """
    p = subprocess.run([FFMPEG, "-v", "error", "-i", v, "-vf",
                        "scale=%d:%d,fps=12" % (SW, SH), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True)
    fs = SW * SH * 3
    n = len(p.stdout) // fs
    if n == 0:
        raise RuntimeError("解不出帧：ffmpeg 输出为空")
    fr = np.frombuffer(p.stdout[:n * fs], np.uint8).reshape(n, SH, SW, 3).astype(int)
    corners = np.concatenate([fr[0, :6, :6].reshape(-1, 3), fr[0, :6, -6:].reshape(-1, 3),
                              fr[0, -6:, :6].reshape(-1, 3), fr[0, -6:, -6:].reshape(-1, 3)])
    ref = corners.mean(axis=0)
    rows = []
    dropped = []
    for i in range(n):
        d = np.sqrt(((fr[i] - ref) ** 2).sum(axis=2))
        m = d > DIST
        if IGNORE_TL:
            m[:int(SH * TL_H), :int(SW * TL_W)] = False
        if m.sum() == 0:
            continue
        char = main_component(m, factor=1)      # 缩略图很小，直接整分辨率重建
        dropped.append(float((m & ~char).mean()))
        ys, xs = np.nonzero(char)
        if len(xs) == 0:
            continue
        rows.append(dict(t=i / 12.0,
                         top=ys.min() / SH * 100, bot=(ys.max() + 1) / SH * 100,
                         left=xs.min() / SW * 100, right=(xs.max() + 1) / SW * 100,
                         cx=xs.mean() / SW * 100, cy=ys.mean() / SH * 100,
                         h=(ys.max() - ys.min() + 1) / SH * 100,
                         w=(xs.max() - xs.min() + 1) / SW * 100))
    if dropped:
        avg = sum(dropped) / len(dropped) * 100
        if avg > 0.05:
            print("  (已剔除与角色不连通的杂块/水印：平均占画面 %.2f%%)" % avg)
    return ref, rows


def corners_hits(v, ref, H, W):
    """全分辨率抽 6 帧，检查四角是否有水印/异物。"""
    res = {}
    for k, t in enumerate([0.0, 0.2, 0.4, 0.6, 0.8]):
        p = subprocess.run([FFMPEG, "-v", "error", "-ss", "%.3f" % t, "-i", v,
                            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True)
        if len(p.stdout) < H * W * 3:
            continue
        a = np.frombuffer(p.stdout[:H * W * 3], np.uint8).reshape(H, W, 3).astype(int)
        d = np.sqrt(((a - ref) ** 2).sum(axis=2))
        m = d > DIST
        zones = {"左上": (slice(0, int(H * .14)), slice(0, int(W * .22))),
                 "右上": (slice(0, int(H * .14)), slice(int(W * .78), W)),
                 "左下": (slice(int(H * .86), H), slice(0, int(W * .22))),
                 "右下": (slice(int(H * .86), H), slice(int(W * .78), W))}
        for nm, sl in zones.items():
            v2 = float(m[sl].mean() * 100)
            res[nm] = max(res.get(nm, 0.0), v2)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default=None, help="预览图输出目录")
    a = ap.parse_args()
    v = a.video
    info = probe(v)
    st = [s for s in info["streams"] if s.get("codec_type") == "video"][0]
    au = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    W, H = int(st["width"]), int(st["height"])
    dur = float(info["format"]["duration"])
    fps = st["r_frame_rate"]

    print("=" * 68)
    print("素材: %s" % os.path.basename(v))
    print("规格: %dx%d  %s  时长 %.2fs  音轨 %s" % (W, H, fps, dur, "有" if au else "无"))
    print("=" * 68)

    ref, rows = scan(v)
    print("绿幕基准色: #%02X%02X%02X" % tuple(ref.astype(int)))
    if not rows:
        print(BAD + " 没有检测到任何角色内容")
        return 1

    def rng(k):
        x = np.array([r[k] for r in rows])
        return x.min(), x.max(), x[0], x[-1]

    checks = []

    def chk(name, ok, txt):
        if ok is None:
            mark = WARN
        else:
            mark = OK if bool(ok) else BAD      # 注意：numpy 布尔不能用 is True 判断
        checks.append((name, None if ok is None else bool(ok), txt))
        print("  %s %-14s %s" % (mark, name, txt))

    print("\n--- 构图（首帧 / 全片范围）---")
    for key, lo, hi, tn in [("top", 15, 25, "头顶"), ("bot", 80, 90, "脚底")]:
        mn, mx, f0, fl = rng(key)
        ok = lo <= f0 <= hi
        chk(tn, ok, "首帧 %.1f%%（规格 %d~%d%%），全片 %.1f~%.1f%%" % (f0, lo, hi, mn, mx))
    mn, mx, f0, fl = rng("h")
    chk("角色高度", 58 <= f0 <= 72, "首帧 %.1f%%（规格 ≈65%%），全片 %.1f~%.1f%%" % (f0, mn, mx))
    mn, mx, f0, fl = rng("cx")
    drift = mx - mn
    chk("水平漂移", drift < 2.0, "跨度 %.2f%%（<2%% 为稳）" % drift)
    mn, mx, f0, fl = rng("cy")
    chk("垂直漂移", mx - mn < 6.0, "跨度 %.2f%%（原地跳会偏大，仅参考）" % (mx - mn))

    print("\n--- 安全区（内容距画幅边缘 ≥10%）---")
    for key, tn, lim in [("top", "上", 10), ("bot", "下", 90), ("left", "左", 10), ("right", "右", 90)]:
        vals = np.array([r[key] for r in rows])
        if tn in ("上", "左"):
            worst = vals.min()
            ok = worst >= lim
            chk("边缘" + tn, ok, "最紧 %.1f%%（要求 ≥%d%%）" % (worst, lim))
        else:
            worst = vals.max()
            ok = worst <= lim
            chk("边缘" + tn, ok, "最紧 %.1f%%（要求 ≤%d%%）" % (worst, lim))

    print("\n--- 四角异物（水印）---")
    ch = corners_hits(v, ref, H, W)
    for nm, pc in ch.items():
        chk(nm, pc < 0.2, "非绿内容 %.3f%%" % pc)

    print("\n--- 首末帧一致性（锚点）---")
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="clipqa_")
    nb = int(st.get("nb_frames") or 0)
    # 用绝对时间戳抽帧（-sseof 贴太近会抽不出帧，实测踩过）
    last_t = max(dur - 0.25, 0.0)
    shots = []
    for nm, t in (("first", 0.0), ("last", last_t)):
        f = os.path.join(tmpd, nm + ".png")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "%.3f" % t, "-i", v,
                        "-frames:v", "1", f], capture_output=True)
        if not os.path.exists(f):   # 兜底：换 sseof 再试一次
            subprocess.run([FFMPEG, "-v", "error", "-y", "-sseof", "-0.5", "-i", v,
                            "-frames:v", "1", f], capture_output=True)
        shots.append(f if os.path.exists(f) else None)
    if all(shots):
        a0 = np.asarray(Image.open(shots[0]).convert("RGB")).astype(int)
        a1 = np.asarray(Image.open(shots[1]).convert("RGB")).astype(int)
        diff = float(np.abs(a0 - a1).mean())
        chk("首末帧差", diff < 8.0, "首帧 vs 末帧(%.2fs) 平均像素差 %.2f（<8 视为同一姿态）" % (last_t, diff))
    else:
        chk("首末帧差", None, "抽帧失败，未能比较")

    print("\n--- 提示 ---")
    if abs(dur - 10.0) > 0.6:
        print(WARN + " 时长 %.2fs ≠ 10s：单段循环动作（待机/说话）可以接受；" % dur)
        print("   需要多阶段节奏的动作（敲键盘/整理/庆祝）建议重新出 10s。")
    if au:
        print(WARN + " 带音轨：我会在抠像时用 -an 丢掉，避免 webm 里混进无效音轨。")
    if fps not in ("24/1", "30/1"):
        # 容器里报的 r_frame_rate 未必是真实帧率，按「真实抽帧数 / 时长」复算
        rf = real_frames(v)
        eff = (rf / dur) if (rf and dur) else 0
        if 22.0 <= eff <= 26.5:
            print("[OK] 帧率：容器标称 %s，实测 %.2f fps（%d 帧 / %.2fs ≈24fps，与素材链一致）" % (fps, eff, rf, dur))
        elif eff:
            print(WARN + " 帧率：容器标称 %s，实测 %.2f fps（%d 帧 / %.2fs）；素材链按 24fps 输出，会被重采样。" % (fps, eff, rf, dur))
        else:
            print(WARN + " 帧率：容器标称 %s，未能实测" % fps)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        step = max(nb // 4, 1) if nb else 30
        sel = "+".join("eq(n\\,%d)" % (i * step) for i in range(4))
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", v, "-vf",
                        "select='%s',scale=%d:%d,tile=2x2" % (sel, W // 2, H // 2),
                        "-vsync", "0", "-frames:v", "1", os.path.join(a.out, "sheet.png")],
                       capture_output=True)
        print("\n预览图: " + os.path.join(a.out, "sheet.png"))

    bad = [c for c in checks if c[1] is False]
    print("\n结果: %d 项通过 / %d 项不通过" % (len(checks) - len(bad), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())