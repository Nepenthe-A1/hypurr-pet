# -*- coding: utf-8 -*-
"""给 dsh-pet 打「动作冷却间隔」补丁 —— 让宠物播完一个动作后安静一会儿再抽下一个。

为什么需要：
  插件源码里 pickNext() 是在动画播完时（handleEnded）**立刻**调用的，中间没有任何等待。
  于是 5 秒一条的素材会让宠物"一个动作接一个动作"，看起来停不下来。
  插件的配置里**没有任何时间/间隔字段**（animations 段只有池子和权重，
  animationWeights 的 idle 是"抽到 idle 池的概率"，不是"待机时长"），所以只能改代码。

补丁做法（最小侵入，只改 1 处）：
  把 handleEnded 末尾的裸调用 `pickNext();`
  换成 `schedulePickNext();`，并注入一个带随机延迟的实现。

可调参数（改下面的 MIN_GAP_MS / MAX_GAP_MS 即可，单位毫秒）：
  播完动画后，随机等待 [MIN_GAP_MS, MAX_GAP_MS]，其间宠物保持当前姿势（不动不换）。

用法：
    python tools/patch_pet_cooldown.py            # 打补丁
    python tools/patch_pet_cooldown.py --revert   # 回滚
    python tools/patch_pet_cooldown.py --status   # 查看状态
升级插件后 lib/client.js 会被覆盖 → 重新跑一次本脚本即可。
"""
import argparse
import hashlib
import io
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLIENT = os.path.join(
    os.path.expanduser("~"), ".dsh", "profiles", "desktop",
    "node_modules", "dsh-pet", "lib", "client.js")
BACKUP = CLIENT + ".orig-cooldown"

MIN_GAP_MS = 10000
MAX_GAP_MS = 20000

MARK = "/* dsh-pet-cooldown-patch */"
# 注意：client.js 是构建产物，缩进用的是**制表符**（不是空格），锚点必须照抄。
ANCHOR = "\t\t\tpickNext();\n\t\t};"
INJECT = """\t\t\t/* dsh-pet-cooldown-patch */
\t\t\tschedulePickNext();
\t\t};"""


def sched_code(gap_min_ms, gap_max_ms):
    return """/* dsh-pet-cooldown-patch */
const COOLDOWN_MIN_MS = %d;
const COOLDOWN_MAX_MS = %d;
const schedulePickNext = () => {
  if (cooldownTimerRef.current !== null) window.clearTimeout(cooldownTimerRef.current);
  const wait = COOLDOWN_MIN_MS + Math.random() * (COOLDOWN_MAX_MS - COOLDOWN_MIN_MS);
  cooldownTimerRef.current = window.setTimeout(() => {
    cooldownTimerRef.current = null;
    pickNext();
  }, wait);
};
""" % (gap_min_ms, gap_max_ms)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def status():
    if not os.path.exists(CLIENT):
        print("找不到 client.js：%s" % CLIENT)
        return 1
    txt = io.open(CLIENT, encoding="utf-8").read()
    patched = MARK in txt
    print("client.js：%s" % CLIENT)
    print("  大小 %d 字节" % os.path.getsize(CLIENT))
    print("  补丁状态：%s" % ("已打（冷却 %d-%d ms）" % (MIN_GAP_MS, MAX_GAP_MS) if patched else "未打"))
    print("  备份：%s" % ("存在" if os.path.exists(BACKUP) else "不存在"))
    return 0


def patch(gap_min_ms=None, gap_max_ms=None):
    gap_min_ms = MIN_GAP_MS if gap_min_ms is None else gap_min_ms
    gap_max_ms = MAX_GAP_MS if gap_max_ms is None else gap_max_ms
    txt = io.open(CLIENT, encoding="utf-8").read()
    if MARK in txt:
        print("已经打过补丁，无需重复。要改间隔请先 --revert。")
        return 0

    # 断言锚点唯一，避免改错地方
    n = txt.count(ANCHOR)
    if n != 1:
        print("[XX] 锚点出现 %d 次（预期 1 次），拒绝修改以免误伤。" % n)
        return 1

    # 1) 备份
    if not os.path.exists(BACKUP):
        shutil.copy2(CLIENT, BACKUP)
        print("已备份 → %s" % os.path.basename(BACKUP))

    # 2) 注入 schedulePickNext 的实现（放在 pickNext 定义之前，用 var 提升避免顺序问题）
    pn = "const pickNext = () => {"
    if txt.count(pn) != 1:
        print("[XX] pickNext 定义锚点出现 %d 次，拒绝修改。" % txt.count(pn))
        return 1
    txt = txt.replace(pn, sched_code(gap_min_ms, gap_max_ms) + pn, 1)

    # 3) 把裸调用换成延迟调度
    txt = txt.replace(ANCHOR, INJECT, 1)

    # 4) 补一个 ref（避免定时器泄漏/重复）
    rf = "\t\tconst moveRef = useRef(null);"
    if txt.count(rf) != 1:
        print("[XX] ref 锚点出现 %d 次，拒绝修改。" % txt.count(rf))
        return 1
    txt = txt.replace(rf, "\t\tconst cooldownTimerRef = useRef(null);\n" + rf, 1)

    io.open(CLIENT, "w", encoding="utf-8", newline="").write(txt)
    print("[OK] 补丁已写入。动作间隔：播完停 %d-%d ms 再抽下一个。" % (gap_min_ms, gap_max_ms))
    print("    重启 DSH 或刷新页面后生效。回滚：--revert")
    return 0


def revert():
    if not os.path.exists(BACKUP):
        print("没有备份，无法回滚。")
        return 1
    shutil.copy2(BACKUP, CLIENT)
    print("[OK] 已回滚到原始 client.js")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--gap-min", type=float, help="冷却下限（秒）")
    ap.add_argument("--gap-max", type=float, help="冷却上限（秒）")
    a = ap.parse_args()
    if a.status:
        return status()
    if a.revert:
        return revert()
    return patch(int(a.gap_min * 1000) if a.gap_min else None,
                 int(a.gap_max * 1000) if a.gap_max else None)


if __name__ == "__main__":
    sys.exit(main())