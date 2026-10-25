# -*- coding: utf-8 -*-
"""动作冷却补丁（**桌面窗版**）—— 修的是 `runtime/electron-helper/sprite.js`。

背景（重要，之前踩过）：
  dsh-pet 有**两套渲染实现**：
    · 网页 overlay  → lib/client.js（`pickNext()` 在 handleEnded 末尾裸调用）
    · 桌面透明窗    → runtime/electron-helper/sprite.js（`this.playIdle()` 在 handleEnded 末尾裸调用）
  只打 client.js 的补丁，在 `display: "desktop"` 时**完全看不到效果**——用户只看到桌面窗那只。
  （这个坑实测踩过：打完补丁仍"动作之间几乎没间隔"。）

补丁内容（4 处，都很小）：
  1. 构造函数里初始化 `this.idleCooldownTimer = null`
  2. `switchTo()` 开头取消待触发的定时器（用户点了菜单/接口触发时不能等冷却）
  3. `playOnce()` 开头同样取消（任何新动画都作废待触发的随机链）
  4. `handleEnded()` 末尾的 `this.playIdle()` → `this.schedulePlayIdle()`（延迟 6~12 秒）
  5. 新增 `schedulePlayIdle()` 方法

用法：
    python tools/patch_pet_cooldown_desktop.py --status
    python tools/patch_pet_cooldown_desktop.py            # 打补丁
    python tools/patch_pet_cooldown_desktop.py --revert   # 回滚
改间隔：改下面 MIN_GAP_MS / MAX_GAP_MS，先 --revert 再重打。
插件升级后 lib/ 与 runtime/ 都会被覆盖 → 两个冷却补丁都要重打。
"""
import argparse
import io
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SPRITE = os.path.join(os.path.expanduser("~"), ".dsh", "profiles", "desktop",
                      "node_modules", "dsh-pet", "runtime", "electron-helper", "sprite.js")
BACKUP = SPRITE + ".orig-cooldown"

MIN_GAP_MS = 10000
MAX_GAP_MS = 20000
MARK = "/* dsh-pet-cooldown-desktop */"

A_CTOR = "  constructor(pet) {\n"
A_SWITCH = "  switchTo(next, nextOnce) {\n"
A_PLAYONCE = "  playOnce(name) {\n"
A_ENDED_CALL = "    this.playIdle();\n  }\n"

R_CTOR = A_CTOR + "    " + MARK + "\n    this.idleCooldownTimer = null;\n"
R_SWITCH = A_SWITCH + "    " + MARK + "\n    this.cancelIdleCooldown();\n"
R_PLAYONCE = A_PLAYONCE + "    " + MARK + "\n    this.cancelIdleCooldown();\n"
R_ENDED_CALL = "    this.schedulePlayIdle(); " + MARK + "\n  }\n"


def method_code(gap_min_ms, gap_max_ms):
    return """
  // ---- 动作冷却（补丁）----
  // 为什么需要：插件在动画播完的瞬间就抽下一个动作，素材一多就会"一个接一个停不下来"。
  // 配置里没有任何时间/间隔字段（animationWeights.idle 是概率不是时长），所以只能改代码。
  cancelIdleCooldown() {
    if (this.idleCooldownTimer !== null) {
      clearTimeout(this.idleCooldownTimer);
      this.idleCooldownTimer = null;
    }
  }

  schedulePlayIdle() {
    this.cancelIdleCooldown();
    const wait = %d + Math.random() * (%d - %d);
    this.idleCooldownTimer = setTimeout(() => {
      this.idleCooldownTimer = null;
      this.playIdle();
    }, wait);
  }
""" % (gap_min_ms, gap_max_ms, gap_min_ms)


def read(p):
    return io.open(p, encoding="utf-8").read()


def write(p, t):
    io.open(p, "w", encoding="utf-8", newline="").write(t)


def status():
    if not os.path.exists(SPRITE):
        print("找不到 sprite.js：%s" % SPRITE)
        return 1
    t = read(SPRITE)
    patched = MARK in t
    print("sprite.js（桌面窗）：%s" % SPRITE)
    print("  大小 %d 字节" % os.path.getsize(SPRITE))
    print("  补丁状态：%s" % ("已打（冷却 %d-%d ms）" % (MIN_GAP_MS, MAX_GAP_MS) if patched else "未打"))
    print("  备份：%s" % ("存在" if os.path.exists(BACKUP) else "不存在"))
    return 0


def patch(gap_min_ms=None, gap_max_ms=None):
    gap_min_ms = MIN_GAP_MS if gap_min_ms is None else gap_min_ms
    gap_max_ms = MAX_GAP_MS if gap_max_ms is None else gap_max_ms
    if not os.path.exists(SPRITE):
        print("找不到 sprite.js：%s" % SPRITE)
        return 1
    t = read(SPRITE)
    if MARK in t:
        print("已打过补丁，无需重复。要改间隔请先 --revert。")
        return 0

    for name, anchor in [("constructor", A_CTOR), ("switchTo", A_SWITCH),
                         ("playOnce", A_PLAYONCE), ("handleEnded 调用", A_ENDED_CALL)]:
        n = t.count(anchor)
        if n != 1:
            print("[XX] 锚点「%s」出现 %d 次（预期 1），拒绝修改以免误伤。" % (name, n))
            return 1

    if not os.path.exists(BACKUP):
        shutil.copy2(SPRITE, BACKUP)
        print("已备份 → %s" % os.path.basename(BACKUP))

    t = t.replace(A_CTOR, R_CTOR, 1)
    t = t.replace(A_SWITCH, R_SWITCH, 1)
    t = t.replace(A_PLAYONCE, R_PLAYONCE, 1)
    t = t.replace(A_ENDED_CALL, R_ENDED_CALL, 1)

    # 方法插到 handleEnded 之前（同类内，位置不影响调用）
    a_ended = "  handleEnded() {"
    if t.count(a_ended) != 1:
        print("[XX] handleEnded 定义锚点异常，拒绝写入")
        return 1
    t = t.replace(a_ended, method_code(gap_min_ms, gap_max_ms) + "\n" + a_ended, 1)

    write(SPRITE, t)
    print("[OK] 桌面窗冷却补丁已写入：动作播完停 %d-%d ms 再抽下一个。" % (gap_min_ms, gap_max_ms))
    print("    重启 DSH 后生效。回滚：--revert")
    return 0


def revert():
    if not os.path.exists(BACKUP):
        print("没有备份，无法回滚。")
        return 1
    shutil.copy2(BACKUP, SPRITE)
    print("[OK] 已还原 sprite.js")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--gap-min", type=float, help="冷却下限（秒）")
    ap.add_argument("--gap-max", type=float, help="冷却上限（秒）")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if a.status:
        return status()
    if a.revert:
        return revert()
    return patch(int(a.gap_min * 1000) if a.gap_min else None,
                 int(a.gap_max * 1000) if a.gap_max else None)


if __name__ == "__main__":
    sys.exit(main())