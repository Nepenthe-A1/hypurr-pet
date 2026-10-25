# -*- coding: utf-8 -*-
"""补丁 4/4：**文字不镜像**（桌面窗渲染器 sprite.js）。

【问题】
桌宠朝右站立时，渲染器把**整帧**做 scaleX(-1) 镜像。角色本身左右对称没问题，
但带文字的动画（如「工作状态-思考冒泡」头顶的问号/气泡字形）会被镜像 → 字反了。

【上游为什么没兜住】
插件内置的 `isNoMirrorAnimation()` 只看 `categories[].noMirror` 标记，
而**宿主推送的 workStatus 动作**（思考/执行/出错…）走的是另一条路径，
拿不到这个豁免 → 文字照样镜像。

【修法】
在 `playOnce(name)` 入口处：如果 `name` 命中配置里的 `animations.noMirrorNames`，
就把 `facing` 强制置为 `'left'`（朝左不镜像），再继续原本逻辑。
配置键由宿主原样透传到 helper（已实测），加名字即可扩展，不必改代码。

【适用】
桌面窗（runtime/electron-helper/sprite.js）。
浏览器形态的文字在 DOM 里绘制，不受 scaleX 影响，无需处理。

用法：
    python tools/patch_pet_nomirror.py           # 打补丁（自动定位插件）
    python tools/patch_pet_nomirror.py --check    # 只检查
"""
import argparse
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
DSH_PET = os.path.join(HOME, ".dsh", "profiles", "desktop", "node_modules", "dsh-pet")
TARGET = os.path.join(DSH_PET, "runtime", "electron-helper", "sprite.js")

MARKER = "dsh-pet-nomirror-patch"
ANCHOR = "  playOnce(name) {"

PATCH = """  playOnce(name) {
    /* %s */
    // 文本/字形类动作（noMirrorNames）：朝右时整帧被 scaleX(-1) 镜像，问号等字形会变反。
    // 这里在播放前强制转朝左；宿主推送的 workStatus 动作也走这条入口，所以能覆盖。
    if (Array.isArray(this.animations.noMirrorNames)
        && this.animations.noMirrorNames.includes(name) && this.facing === 'right') {
      this.facing = 'left';
    }
""" % MARKER


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查是否已打")
    ap.add_argument("--target", default=TARGET)
    a = ap.parse_args()

    path = a.target
    if not os.path.isfile(path):
        print("[XX] 找不到 %s" % path)
        return 1

    with open(path, encoding="utf-8") as f:
        src = f.read()

    if MARKER in src:
        print("已打过补丁（%s）" % MARKER)
        return 0
    if a.check:
        print("未打补丁：%s" % path)
        return 1

    if ANCHOR not in src:
        print("[XX] 找不到锚点 %r —— 插件版本可能变了，需人工确认" % ANCHOR)
        return 1

    # 备份（带时间戳，便于回滚）
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.orig-nomirror.%s" % (path, stamp)
    shutil.copy2(path, bak)

    out = src.replace(ANCHOR, PATCH.rstrip("\n"), 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(out)

    ok = MARKER in open(path, encoding="utf-8").read()
    print("%s  备份=%s" % ("OK 补丁已写入" if ok else "[XX] 写入失败", os.path.basename(bak)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())