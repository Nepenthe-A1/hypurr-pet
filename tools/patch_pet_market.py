# -*- coding: utf-8 -*-
"""给 dsh-pet 打两个补丁：
  1) 【菜单】把「碎碎念」分组从右键动作列表里隐藏（键仍保留，否则 say 气泡会失效）。
  2) 【行情】把 HYPE 行情联动内嵌进插件宿主进程（不再需要外部 Python 脚本）。

为什么行情要内嵌：
  外部脚本需要常驻一个进程、还要自己探测 DSH 端口，分享给别人时基本等于不可用。
  插件宿主进程跑在 Node 里，本来就常驻、有网络、能直接写宠物状态（state.writePet），
  所以把它作为 ctx.effect 的一个定时器挂进去，就是"桌宠自带行情"。

  实测前提：Hyperliquid 的 /info 返回 `access-control-allow-origin: *`，
  但宿主进程是 Node，本来也不受 CORS 限制。

改动点（都是最小侵入 + 断言）：
  lib/client.js  buildMenuTree 的 events 循环加一行 skip
  lib/index.js   balance poll 那个 ctx.effect 之后，插入 market link 的 ctx.effect

用法：
    python tools/patch_pet_market.py --status
    python tools/patch_pet_market.py                     # 打补丁（默认 60s / ±1.5% / 冷却 300s）
    python tools/patch_pet_market.py --pet hypurr --poll 60 --up 1.5 --cooldown 300
    python tools/patch_pet_market.py --revert
插件升级会覆盖 lib/*.js → 升级后重跑一次本脚本。
"""
import argparse
import io
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PKG = os.path.join(os.path.expanduser("~"), ".dsh", "profiles", "desktop",
                   "node_modules", "dsh-pet", "lib")
CLIENT = os.path.join(PKG, "client.js")
HOST = os.path.join(PKG, "index.js")

MARK_MENU = "/* dsh-pet-menu-hide-whisper */"
MARK_MARKET = "/* dsh-pet-market-patch */"

# --- 菜单：让 buildMenuTree 跳过 whisper 键 ---
MENU_ANCHOR = "\tfor (const key of Object.keys(events)) {\n"
MENU_REPLACE = ("\t" + MARK_MENU + "\n"
                "\tfor (const key of Object.keys(events)) {\n"
                "\t\tif (key === \"whisper\") continue;\n")

# --- 行情：挂在 balance poll 之后 ---
MARKET_ANCHOR = '\t}, "dsh-pet: balance poll");\n'

MARKET_TMPL = """\t%s
\tctx.effect(() => {
\t\tconst MARKET_PET = %s;
\t\tconst MARKET_SYMBOL = %s;
\t\tconst MARKET_POLL_MS = %d;
\t\tconst MARKET_UP_PCT = %s;
\t\tconst MARKET_UP_ANIM = %s;
\t\tconst MARKET_DOWN_ANIM = %s;
\t\tconst MARKET_COOLDOWN_MS = %d;
\t\tlet last = null;
\t\tlet lastFire = 0;
\t\tlet timer = null;
\t\tlet disposed = false;
\t\tconst fire = (name, text) => {
\t\t\ttry {
\t\t\t\tstate.writePet(MARKET_PET, "anim", { name });
\t\t\t\tstate.writePet(MARKET_PET, "say", { text });
\t\t\t\tconsole.log("[dsh-pet] market " + (/* now */ new Date()).toTimeString().slice(0, 8) + " " + text + " -> " + name);
\t\t\t} catch (e) {}
\t\t};
\t\tconst tick = async () => {
\t\t\tif (disposed) return;
\t\t\ttry {
\t\t\t\tconst r = await fetch("https://api.hyperliquid.xyz/info", {
\t\t\t\t\tmethod: "POST",
\t\t\t\t\theaders: { "content-type": "application/json" },
\t\t\t\t\tbody: JSON.stringify({ type: "allMids" })
\t\t\t\t});
\t\t\t\tif (r.ok) {
\t\t\t\t\tconst j = await r.json();
\t\t\t\t\tconst p = Number(j && j[MARKET_SYMBOL]);
\t\t\t\t\tif (Number.isFinite(p) && p > 0) {
\t\t\t\t\t\tif (last !== null) {
\t\t\t\t\t\t\tconst chg = (p - last) / last * 100;
\t\t\t\t\t\t\tconst now = Date.now();
\t\t\t\t\t\t\tif (now - lastFire >= MARKET_COOLDOWN_MS) {
\t\t\t\t\t\t\t\tif (chg >= MARKET_UP_PCT) {
\t\t\t\t\t\t\t\t\tlastFire = now;
\t\t\t\t\t\t\t\t\tfire(MARKET_UP_ANIM, MARKET_SYMBOL + " +" + chg.toFixed(2) + "%% 喵！冲");
\t\t\t\t\t\t\t\t} else if (chg <= -MARKET_UP_PCT) {
\t\t\t\t\t\t\t\t\tlastFire = now;
\t\t\t\t\t\t\t\t\tfire(MARKET_DOWN_ANIM, MARKET_SYMBOL + " " + chg.toFixed(2) + "%% …猫粮缩水");
\t\t\t\t\t\t\t\t}
\t\t\t\t\t\t\t}
\t\t\t\t\t\t}
\t\t\t\t\t\tlast = p;
\t\t\t\t\t}
\t\t\t\t}
\t\t\t} catch (e) {}
\t\t\tif (!disposed) timer = setTimeout(() => void tick(), MARKET_POLL_MS);
\t\t};
\t\tvoid tick();
\t\treturn () => {
\t\t\tdisposed = true;
\t\t\tif (timer !== null) clearTimeout(timer);
\t\t};
\t}, "dsh-pet: market link");
"""


def read(p):
    return io.open(p, encoding="utf-8").read()


def write(p, t):
    io.open(p, "w", encoding="utf-8", newline="").write(t)


def backup(p):
    b = p + ".orig-market"
    if not os.path.exists(b):
        shutil.copy2(p, b)
        print("  已备份 → %s" % os.path.basename(b))


def status():
    ct, ht = read(CLIENT), read(HOST)
    print("client.js  菜单隐藏补丁：%s" % ("已打" if MARK_MENU in ct else "未打"))
    print("index.js   行情内嵌补丁：%s" % ("已打" if MARK_MARKET in ht else "未打"))
    m = "hypurr"
    if MARK_MARKET in ht:
        i = ht.find(MARK_MARKET)
        seg = ht[i:i + 700]
        for k in ("MARKET_PET", "MARKET_SYMBOL", "MARKET_POLL_MS", "MARKET_UP_PCT", "MARKET_COOLDOWN_MS"):
            j = seg.find(k + " = ")
            if j >= 0:
                print("  %-20s %s" % (k, seg[j + len(k) + 3:seg.find(";", j)]))
    return 0


def patch(args):
    ct, ht = read(CLIENT), read(HOST)

    # 1) 菜单隐藏
    if MARK_MENU in ct:
        print("菜单隐藏补丁已存在，跳过")
    else:
        if ct.count(MENU_ANCHOR) != 1:
            print("[XX] 菜单锚点出现 %d 次，拒绝修改" % ct.count(MENU_ANCHOR))
            return 1
        backup(CLIENT)
        ct = ct.replace(MENU_ANCHOR, MENU_REPLACE, 1)
        write(CLIENT, ct)
        print("[OK] 菜单补丁：右键「动作」里不再出现「碎碎念」")

    # 2) 行情内嵌
    if MARK_MARKET in ht:
        print("行情补丁已存在，跳过（要改参数先 --revert）")
    else:
        if ht.count(MARKET_ANCHOR) != 1:
            print("[XX] 行情锚点出现 %d 次，拒绝修改" % ht.count(MARKET_ANCHOR))
            return 1
        backup(HOST)
        block = MARKET_TMPL % (
            MARK_MARKET,
            '"%s"' % args.pet,
            '"%s"' % args.symbol,
            int(args.poll * 1000),
            repr(float(args.up)),
            '"%s"' % args.up_anim,
            '"%s"' % args.down_anim,
            int(args.cooldown * 1000),
        )
        ht = ht.replace(MARKET_ANCHOR, MARKET_ANCHOR + block, 1)
        write(HOST, ht)
        print("[OK] 行情补丁：%s 每 %ds 轮询，±%.2f%% 触发，冷却 %ds，宠物 %s" % (
            args.symbol, args.poll, args.up, args.cooldown, args.pet))

    print("\n重启 DSH（或刷新页面）后生效。回滚：--revert")
    return 0


def revert():
    for p in (CLIENT, HOST):
        b = p + ".orig-market"
        if os.path.exists(b):
            shutil.copy2(b, p)
            print("[OK] 已还原 %s" % os.path.basename(p))
        else:
            print("  %s 无备份，跳过" % os.path.basename(p))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--pet", default="hypurr")
    ap.add_argument("--symbol", default="HYPE")
    ap.add_argument("--poll", type=float, default=60, help="轮询秒数")
    ap.add_argument("--up", type=float, default=1.5, help="涨跌阈值百分比")
    ap.add_argument("--cooldown", type=float, default=300, help="同事件冷却秒数")
    ap.add_argument("--up-anim", default="工作状态-雀跃庆祝")
    ap.add_argument("--down-anim", default="工作状态-垂头叹气冒汗")
    a = ap.parse_args()
    if a.status:
        return status()
    if a.revert:
        return revert()
    return patch(a)


if __name__ == "__main__":
    sys.exit(main())