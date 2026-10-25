# -*- coding: utf-8 -*-
"""批量处理「用户自己抠好、但导成了不透明黑底」的素材：
   黑底还原 alpha → 归一化 → 640x360 播放变体 → 装进 pet pack。

用法: python tools/batch_user_keyed.py [--only 名字]
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PACK = os.path.join(os.path.expanduser("~"), ".dsh", "dsh-pet", "pet", "hypurr-animation")
QA = os.path.join(ROOT, "video", "_qa")
STEP02 = os.path.join(ROOT, "video", "step02_userkeyed")
STEP03 = os.path.join(ROOT, "video", "step03_userkeyed")
STEP04 = os.path.join(ROOT, "video", "step04_userkeyed")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

# (目标名, 源文件, 备注)
JOBS = [
    ("凭空扑蝴蝶", os.path.join(PACK, "凭空扑蝴蝶.mp4"), "黑底 mp4 1280x720"),
    ("工作状态-清点归档", os.path.join(PACK, "工作状态-清点归档.mp4.mp4"), "黑底 mp4 1280x720（注意：时长只有 5.08s）"),
    ("被鼠标拖拽悬空反馈", os.path.join(PACK, "被鼠标拖拽悬空反馈.mp4"), "黑底 mp4 **640x360**"),
    ("原地坐下张望", os.path.join(os.path.expanduser("~"), "Desktop", "原地坐下张望.mov"), "黑底 mov **640x360**"),
    ("原地转身回头", os.path.join(os.path.expanduser("~"), "Desktop", "原地转身回头.mov"), "黑底 mov **640x360**"),
    ("工作状态-忙碌点按", os.path.join(os.path.expanduser("~"), "Desktop", "工作状态-忙碌点按.mov"), "黑底 mov 1280x720"),
]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def run(args, label):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [x.strip() for x in (r.stdout or "").strip().split("\n") if x.strip()][-2:]
    for t in tail:
        log("    " + t)
    if r.returncode != 0:
        log("    [XX] %s 失败 rc=%d: %s" % (label, r.returncode, (r.stderr or "")[-300:]))
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只处理这一个名字")
    a = ap.parse_args()

    for d in (STEP02, STEP03, STEP04):
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))

    done = []
    for name, src, note in JOBS:
        if a.only and a.only != name:
            continue
        if not os.path.exists(src):
            log("跳过 %s（源不存在：%s）" % (name, src))
            continue
        log("=== %s  [%s] ===" % (name, note))
        dst = os.path.join(STEP02, name + ".webm")
        if not run([PY, os.path.join(ROOT, "tools", "key_from_black.py"), src, dst], "还原 alpha"):
            continue
        done.append(name)

    if not done:
        log("没有可处理的文件")
        return 1

    log("=== 归一化（%d 条）===" % len(done))
    run([PY, os.path.join(ROOT, "tools", "normalize.py"),
         "--in", STEP02, "--out", STEP03], "normalize")

    log("=== 640x360 播放变体 ===")
    run([PY, os.path.join(ROOT, "tools", "encode_playback.py"),
         "--in", STEP03, "--out", STEP04], "encode")

    log("=== 装进 pet pack ===")
    for name in done:
        f = os.path.join(STEP04, name + ".webm")
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(PACK, name + ".webm"))
            log("    + %s.webm (%.2f MB)" % (name, os.path.getsize(f) / 1e6))
        else:
            log("    - 缺 %s.webm" % name)

    log("=== 清理用户给的临时容器文件（已被 webm 取代）===")
    for name, src, _ in JOBS:
        if a.only and a.only != name:
            continue
        if os.path.dirname(src) == PACK and os.path.exists(src):
            os.remove(src)
            log("    已移除 %s" % os.path.basename(src))
    log("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())