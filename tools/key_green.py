"""背景抠像 → 透明 VP9-alpha WebM（dsh-pet 素材链 step02 的替代实现）。

为什么自己写（不用 dsh-pet 自带的 chroma_step02.py）：
  1. 自带脚本色相窗口写死 [70,170]。Hypurr 的外套是橄榄绿 #3A5D48（约 144 度）→ 整片外套被抠掉（实测复现）。
  2. 水印要单独处理：即梦是绿底「AI 生成」，豆包是白色且逐帧移动的「豆包AI生成」。
  3. 换品红背景后，模型会在外套上留几块背景色/暗红斑，需要局部补掉。

默认预设 magenta（品红底）：窄窗口 15 度、不去绿、开补斑。
--preset green 回到绿幕时代的参数（宽窗口 18 度 + 边界带去绿闸门）。

用法:
    python tools/key_green.py <in.mp4> <out.webm> [--preset magenta|green]

补斑判据（品红背景实测得出）：
  · 在角色内地（剪影腐蚀 speck_inner_px 后）
  · 色相与背景色相差 <=75 度、饱和 >=0.30（避开粉耳/肉垫：饱和约 0.25）
  · 明度 20~170（排除近黑线稿阴影；也排除亮紫特效，如实测问号光晕 #9184C4 明度 196）
  · R >= B-10（藏青线稿/亮紫光晕都是蓝占优 -> 避开）
  · 局部邻域里「布料（既非背景也非斑色）」占比 >0.30
  用周围布料均色直接填（不用边缘扩散：斑块边缘那圈暗红会被当正常像素运进斑心，留暗心）
"""
import argparse, os, subprocess, sys
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from matte_util import border_hue, bg_mask, main_component, rgb_to_hsv_np, _dilate  # noqa: E402

from ffmpeg_path import FFMPEG, FFPROBE  # noqa: E402  （env FFMPEG/FFPROBE → PATH → 常见位置）
OK, WARN, BAD = "[OK]", "[!!]", "[XX]"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def probe(v, entries):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", entries, "-of", "csv=p=0", v],
                       capture_output=True, text=True)
    return (r.stdout or "").strip()


def probe_wh(v):
    w, h = probe(v, "stream=width,height").split(",")[:2]
    return int(w), int(h)


def probe_fps(v):
    """真实帧率。容器元数据不可信（即梦标称 60fps，实际 24fps）。"""
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


def _min_filter(m, k):
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8), "L")
                      .filter(ImageFilter.MinFilter(2 * k + 1))) > 127


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--preset", choices=["magenta", "green"], default="magenta")
    ap.add_argument("--hue-tol", type=float, default=18.0)
    ap.add_argument("--sat-min", type=float, default=0.20)
    ap.add_argument("--feather", type=float, default=6.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--keep-all", action="store_true", help="不做连通域过滤（水印可能残留）")
    ap.add_argument("--despill", dest="despill", action="store_true", default=True)
    ap.add_argument("--no-despill", dest="despill", action="store_false")
    ap.add_argument("--spill-px", type=int, default=14)
    ap.add_argument("--spill-hue-tol", type=float, default=25.0)
    ap.add_argument("--spill-sat-min", type=float, default=0.60)
    ap.add_argument("--wm-sat-max", type=float, default=0.35, help="水印候选的饱和度上界")
    ap.add_argument("--wm-near-px", type=int, default=6,
                    help="水印候选若离内容这么近就判为投影/暗边、予以保留")
    ap.add_argument("--wm-remove", dest="wm_remove", action="store_true", default=True,
                    help="是否删除贴边低饱和小块（水印）。素材本身没有水印时建议关掉："
                         "道具的投影也贴边、也低饱和，会被误删（清点归档实测丢了 8124px 投影）")
    ap.add_argument("--no-wm-remove", dest="wm_remove", action="store_false")
    ap.add_argument("--fix-specks", dest="fix_specks", action="store_true", default=True)
    ap.add_argument("--no-fix-specks", dest="fix_specks", action="store_false")
    ap.add_argument("--speck-hue-tol", type=float, default=75.0)
    ap.add_argument("--speck-sat-min", type=float, default=0.30)
    ap.add_argument("--speck-val-min", type=float, default=20.0)
    ap.add_argument("--speck-val-max", type=float, default=170.0)
    ap.add_argument("--speck-red-dominant", type=int, default=10)
    ap.add_argument("--speck-inner-px", type=int, default=6)
    ap.add_argument("--speck-neigh", type=int, default=10)
    ap.add_argument("--speck-fabric-frac", type=float, default=0.30)
    ap.add_argument("--speck-min-px", type=int, default=15)
    ap.add_argument("--speck-fill-radius", type=int, default=11)
    # 碎屑过滤：粒子爆发时模型会撒出贴近背景色相的小颗粒（实测色相 279~281 度，
    # 而窗口是背景 299±15=283~313，刚好差 2~4 度没被抠掉；它们飘在空中，
    # 补斑逻辑（要求周围是布料）也正确地不管它们）。
    ap.add_argument("--fix-debris", dest="fix_debris", action="store_true", default=True)
    ap.add_argument("--no-fix-debris", dest="fix_debris", action="store_false")
    ap.add_argument("--debris-hue-tol", type=float, default=28.0)
    ap.add_argument("--debris-sat-min", type=float, default=0.28)
    ap.add_argument("--debris-cov-radius", type=int, default=12)
    ap.add_argument("--debris-cov-max", type=float, default=0.30,
                    help="局部覆盖度低于此值判为碎屑；成片彩色特效覆盖度高，不会被误删")
    return ap


def main():
    a = build_parser().parse_args()

    explicit = set(x.split("=")[0] for x in sys.argv[1:] if x.startswith("--"))
    if a.preset == "magenta":
        if "--hue-tol" not in explicit:
            a.hue_tol = 15.0
        if "--despill" not in explicit and "--no-despill" not in explicit:
            a.despill = False
    else:
        if "--hue-tol" not in explicit:
            a.hue_tol = 18.0
        if "--despill" not in explicit and "--no-despill" not in explicit:
            a.despill = True
    print("预设=%s：hue_tol=%.0f 度  despill=%s  fix_specks=%s" % (
        a.preset, a.hue_tol, "on" if a.despill else "off", "on" if a.fix_specks else "off"))

    W, H = probe_wh(a.src)
    src_fps = probe_fps(a.src)
    print("输入 %s  %dx%d  %.2ffps → %s（输出 %dfps）" % (
        os.path.basename(a.src), W, H, src_fps, a.dst, a.fps))
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)) or ".", exist_ok=True)

    p_in = subprocess.Popen([FFMPEG, "-v", "error", "-i", a.src,
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    p_out = subprocess.Popen([FFMPEG, "-v", "error", "-y",
                              "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "%dx%d" % (W, H),
                              "-r", "%.4f" % src_fps, "-i", "-", "-an",
                              "-vf", "fps=%d" % a.fps,
                              "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                              "-crf", "30", "-b:v", "0", "-auto-alt-ref", "0",
                              "-deadline", "good", "-cpu-used", "4", a.dst], stdin=subprocess.PIPE)

    fs = W * H * 3
    n = 0
    bg_hue = None
    acc_bg = acc_drop = acc_spill = acc_speck = acc_debris = 0.0
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

        if bg_hue is None:
            bg_hue = border_hue(arr)
            print("%s 采样背景色相 %.1f 度" % (OK, bg_hue))

        mask = bg_mask(arr, bg_hue, a.hue_tol, a.sat_min)
        hue, sat, val = rgb_to_hsv_np(arr)
        dh = np.abs((hue - bg_hue + 180) % 360 - 180)
        in_hue = np.clip((a.hue_tol - dh) / max(a.feather, 1e-6), 0, 1)

        if a.keep_all:
            keep = ~mask
        else:
            fg = ~mask
            char = main_component(fg)
            other = fg & ~char
            band = np.zeros_like(fg)
            mh, mw = int(H * 0.12), int(W * 0.12)
            band[-mh:, :] = True
            band[:, :mw] = True
            band[:, -mw:] = True
            # 水印判定要再加一条"离内容远"：
            # 豆包/AI 水印是**孤立漂在背景上**的文字小块；而角色的投影、道具的暗边
            # 往往也贴边、也低饱和（实测灰箱子底部投影 sat 0.09 / val 150），
            # 但它们**紧贴主体**（相邻几个像素）→ 用"是否靠近内容"区分，比按亮度/位置可靠。
            # 这个坑实测踩过：清点归档里灰箱子底部一条 3480px 的投影被当水印删了。
            wm_cand = other & band & (sat < a.wm_sat_max)
            if not a.wm_remove:
                wm = np.zeros_like(wm_cand)
            else:
                near = _dilate(char | (other & ~wm_cand), a.wm_near_px)
                wm = wm_cand & (~near)
            keep = _dilate(char | (other & ~wm), 2)
            acc_drop += float(wm.mean())

        alpha = np.where(mask & keep, (1.0 - in_hue) * 255, 255).astype(np.uint8)
        alpha[~keep] = 0

        out_arr = arr

        if a.despill and mask.any():
            contam = (dh <= a.spill_hue_tol) & (sat >= a.spill_sat_min)
            edge = _dilate(alpha == 0, a.spill_px) & (alpha > 0) & contam
            if edge.any():
                r = arr[..., 0].astype(np.int16)
                g = arr[..., 1].astype(np.int16)
                b = arr[..., 2].astype(np.int16)
                excess = (g - np.maximum(r, b)).astype(np.float32)
                k = np.clip(excess / 120.0, 0.0, 1.0) * edge
                alpha = np.minimum(alpha.astype(np.float32), (1.0 - k) * 255.0).astype(np.uint8)
                lim = np.maximum(r, b) + 6
                out_arr = arr.copy()
                out_arr[..., 1] = np.clip(np.where(edge & (g > lim), lim, g), 0, 255).astype(np.uint8)
                acc_spill += float(edge.mean())

        acc_bg += float(mask.mean())

        if a.fix_specks and mask.any():
            inner = _min_filter(alpha > 250, a.speck_inner_px)
            mag = ((dh <= a.speck_hue_tol) & (sat >= a.speck_sat_min)
                   & (val >= a.speck_val_min) & (val <= a.speck_val_max)
                   & (arr[..., 0].astype(np.int16) >= arr[..., 2].astype(np.int16) - a.speck_red_dominant))
            fabric = (~mask) & (~mag)
            frac = np.asarray(Image.fromarray((fabric * 255).astype(np.uint8), "L")
                              .filter(ImageFilter.BoxBlur(a.speck_neigh)), np.float32) / 255.0
            speck = inner & mag & (frac > a.speck_fabric_frac)
            if int(speck.sum()) >= a.speck_min_px:
                fixed = out_arr.copy()
                src = fabric & (~speck)
                wgt = src.astype(np.float32)
                den = np.asarray(Image.fromarray((wgt * 255).astype(np.uint8), "L")
                                 .filter(ImageFilter.BoxBlur(a.speck_fill_radius)), np.float32) / 255.0
                for c in range(3):
                    num = np.asarray(Image.fromarray(
                        (fixed[..., c].astype(np.float32) * wgt).clip(0, 255).astype(np.uint8), "L")
                        .filter(ImageFilter.BoxBlur(a.speck_fill_radius)), np.float32)
                    mean_c = num / np.maximum(den, 1e-6)
                    fixed[..., c] = np.where(speck, mean_c.clip(0, 255), fixed[..., c]).astype(np.uint8)
                out_arr = fixed
                acc_speck += float(speck.mean())

        # 碎屑过滤：贴近背景色相、饱和够、但"局部稀疏"的像素 → 判为碎屑，直接抠掉（alpha=0）。
        # 为什么需要它：粒子爆发那几帧，模型会撒出成片小颗粒，色相 279~281 度落在
        # 抠像窗口（背景±15 度）之外 2~4 度，因而不被判为背景；它们又飘在空中、
        # 周围没有布料，所以"补斑"也管不到。用"局部覆盖度"区分碎屑与成片特效：
        # 碎屑稀疏（覆盖度低），彩色纸屑/问号光晕成片（覆盖度高）→ 不会被误删。
        if a.fix_debris:
            cand = keep & (~mask) & (dh <= a.debris_hue_tol) & (sat >= a.debris_sat_min)
            if cand.any():
                cov = np.asarray(Image.fromarray((cand * 255).astype(np.uint8), "L")
                                 .filter(ImageFilter.BoxBlur(a.debris_cov_radius)), np.float32) / 255.0
                debris = cand & (cov < a.debris_cov_max)
                if debris.any():
                    alpha[debris] = 0
                    acc_debris += float(debris.mean())

        p_out.stdin.write(np.dstack([out_arr, alpha]).tobytes())
        n += 1
        if n % 48 == 0:
            print("  已处理 %d 帧" % n)

    p_in.stdout.close(); p_in.wait()
    p_out.stdin.close(); rc = p_out.wait()
    if n:
        print("%s 完成 %d 帧；背景占比 %.1f%%；水印丢弃 %.3f%%；去绿 %.3f%%；补斑 %.3f%%；碎屑清除 %.3f%%" % (
            OK if rc == 0 else BAD, n, acc_bg / n * 100, acc_drop / n * 100,
            acc_spill / n * 100, acc_speck / n * 100, acc_debris / n * 100))
    print("输出: %s (%.2f MB)" % (a.dst, os.path.getsize(a.dst) / 1e6 if os.path.exists(a.dst) else 0))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())