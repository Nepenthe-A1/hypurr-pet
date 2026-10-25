# -*- coding: utf-8 -*-
"""Hypurr 行情联动 —— 把 Hyperliquid 行情接到桌宠动画与气泡上。

原理：插件在 DSH 主端口上暴露了两个本机接口（无需鉴权、只监听 127.0.0.1）：
    POST /dsh-pet-7340/anim       {"name": "<动画名>"}   → 点播动画（名字必须在配置的池子里）
    POST /dsh-pet-7340/broadcast  {"text": "<文字>"}     → 弹气泡（第三方投喂，不限长度/频率）

本脚本轮询 Hyperliquid 公开行情（POST https://api.hyperliquid.xyz/info，无需 API key），
按规则触发动画 + 气泡。

用法：
    python tools/market_link.py                  # 前台运行
    python tools/market_link.py --once           # 只跑一轮（自检用）
    python tools/market_link.py --dry            # 只打印不真触发
    python tools/market_link.py --list-anim      # 列出可用动画名

配置：改下面的 CONFIG（币种、阈值、冷却时间、端口）。
"""
import argparse, json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except TypeError:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG = {
    # DSH 主端口：插件接口挂在它下面。
    # ⚠️ DSH 每次启动端口都会变，所以默认 auto = 自动探测（扫本机监听端口，
    #    逐个探 /dsh-pet-7340/state，谁返回带 pets 的 JSON 就是它）。
    #    探测失败时会自动重试，所以 DSH 重启后脚本能自己找回来。
    "port": "auto",
    "api_prefix": "/dsh-pet-7340",

    # ⚠️ 宠物 id 必须作为 **URL 查询参数** 传（?pet=hypurr），不是 JSON body 字段！
    # 源码：requested: String(url.searchParams.get("pet") ?? "")
    # 不传就会落到默认的 "main"（内置女仆），看起来返回 ok:true 但猫毫无反应——
    # 这个坑实测踩过，一定要带。
    "pet": "hypurr",

    # 行情源
    "hl_info_url": "https://api.hyperliquid.xyz/info",
    "poll_sec": 60,              # 轮询间隔（秒）。别太短，Hyperliquid 有速率限制

    # 关注的币种（用 Hyperliquid 的币名）
    "watch": ["HYPE", "BTC", "ETH"],

    # 涨跌阈值（百分比，1 分钟窗口内的变化）
    "up_pct": 1.5,
    "down_pct": -1.5,

    # 各事件播的动画（必须是 pet pack 里已装、且在配置池子里的名字）
    "anim_up": "工作状态-雀跃庆祝",
    "anim_down": "工作状态-垂头叹气冒汗",
    "anim_flat": "工作状态-原地踱步张望",

    # 同一事件的冷却（秒），防止刷屏
    "cooldown_sec": 300,
}


def http_json(url, payload=None, timeout=15):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"content-type": "application/json"},
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------- 端口自动探测 ----------
def listening_ports():
    """返回本机正在 LISTEN 的端口（只取本机/全地址绑定的）。"""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace").stdout
    except Exception:
        return []
    ports = set()
    for line in out.splitlines():
        m = re.search(r"TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\s+(\d+)", line)
        if not m:
            continue
        addr, port = m.group(1), int(m.group(2))
        if addr in ("127.0.0.1", "0.0.0.0", "[::]", "[::1]"):
            ports.add(port)
    return sorted(ports)


def detect_port(prefix=None, timeout=0.6, verbose=False):
    """扫本机监听端口，找出挂了 dsh-pet 接口的那个。找不到返回 None。"""
    prefix = prefix or CONFIG["api_prefix"]
    # 常见区间优先，避免每次都扫几百个端口
    ports = listening_ports()
    cand = [p for p in ports if 40000 <= p <= 70000] + [p for p in ports if not (40000 <= p <= 70000)]
    for port in cand:
        url = "http://127.0.0.1:%d%s/state" % (port, prefix)
        try:
            r = http_json(url, None, timeout=timeout)
        except Exception:
            continue
        if isinstance(r, dict) and "pets" in r:
            if verbose:
                print("[OK] 自动探测到 DSH 端口：%d（宠物：%s）" %
                      (port, ", ".join(r.get("pets", {}).keys())))
            return port
    return None


_RESOLVED = {"port": None}


def resolve_port(force=False):
    """把 CONFIG['port'] 解析成整数。'auto' 时自动探测并缓存；失败返回 None。"""
    p = CONFIG["port"]
    if isinstance(p, int):
        return p
    if _RESOLVED["port"] and not force:
        return _RESOLVED["port"]
    _RESOLVED["port"] = detect_port()
    return _RESOLVED["port"]


def pet_call(path, payload, retries=3):
    """调用宠物接口。端口是 auto 时，连不上就重新探测（DSH 重启后端口会变）。"""
    last = None
    for attempt in range(retries):
        port = resolve_port(force=(attempt > 0))
        if port is None:
            last = {"ok": False, "reason": "no-port",
                    "message": "没探测到 DSH 端口（DSH 没启动？）"}
            if attempt < retries - 1:
                time.sleep(1.5)
            continue
        url = "http://127.0.0.1:%d%s%s?pet=%s" % (
            port, CONFIG["api_prefix"], path, urllib.parse.quote(str(CONFIG["pet"])))
        try:
            return http_json(url, payload, timeout=8)
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode()[:200]
            except Exception:
                body = ""
            return {"ok": False, "reason": "http-%d" % e.code, "message": body}
        except Exception as e:
            last = {"ok": False, "reason": "unreachable", "message": str(e)[:200]}
            _RESOLVED["port"] = None          # 连接失败 → 下次重新探测
            if attempt < retries - 1:
                time.sleep(1.0)
    return last or {"ok": False, "reason": "unknown"}


def play_anim(name, dry=False):
    if dry:
        print("    [dry] 点播动画：%s" % name)
        return True
    r = pet_call("/anim", {"name": name})
    ok = r.get("ok")
    print("    点播动画 %s → %s%s" % (name, "成功" if ok else "失败",
                                     "" if ok else "  " + str(r)))
    return ok


def broadcast(text, dry=False):
    if dry:
        print("    [dry] 弹气泡：%s" % text)
        return True
    r = pet_call("/broadcast", {"text": text})
    ok = r.get("ok")
    print("    弹气泡「%s」→ %s%s" % (text, "成功" if ok else "失败",
                                    "" if ok else "  " + str(r)))
    return ok


def fetch_mids(url):
    """取全部币种中间价。"""
    return http_json(url, {"type": "allMids"})


def collect_anim_names(conf):
    """按插件 animationNames() 的口径，收集一个配置里所有可点播的动画名。"""
    out = set()
    a = conf.get("animations") if isinstance(conf, dict) else None
    if not isinstance(a, dict):
        return out
    for key in ("idle", "turn", "drag", "clicks"):
        v = a.get(key)
        if isinstance(v, list):
            out |= {x for x in v if isinstance(x, str)}
    mv = a.get("moves") or {}
    if isinstance(mv, dict) and isinstance(mv.get("actions"), list):
        for m in mv["actions"]:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                out.add(m["name"])
    cats = a.get("categories")
    if isinstance(cats, list):
        for c in cats:
            if isinstance(c, dict) and isinstance(c.get("actions"), list):
                out |= {x for x in c["actions"] if isinstance(x, str)}
    ev = a.get("events")
    if isinstance(ev, dict):
        for pool in ev.values():
            if isinstance(pool, list):
                for slot in pool:
                    if isinstance(slot, str):
                        out.add(slot)
                    elif isinstance(slot, list):
                        out |= {x for x in slot if isinstance(x, str)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    ap.add_argument("--dry", action="store_true", help="只打印，不真触发")
    ap.add_argument("--port", type=int, help="DSH 主端口")
    ap.add_argument("--poll", type=int, help="轮询秒数")
    ap.add_argument("--pet", help="宠物 id（作为 ?pet= 参数，默认 hypurr）")
    a = ap.parse_args()

    if a.port:
        CONFIG["port"] = a.port
    if a.poll:
        CONFIG["poll_sec"] = a.poll
    if a.pet:
        CONFIG["pet"] = a.pet

    print("Hypurr 行情联动")
    print("  行情源   %s" % CONFIG["hl_info_url"])
    print("  关注     %s   阈值 ±%.1f%%   轮询 %ds" % (", ".join(CONFIG["watch"]),
                                                    CONFIG["up_pct"], CONFIG["poll_sec"]))

    # 先自检接口（端口 auto 时这里就会自动探测）
    t0 = time.time()
    st = pet_call("/state", None)
    if not st or "pets" not in st:
        print("[XX] 连不上桌宠接口")
        print("     返回：%s" % str(st)[:200])
        print("     提示：确认 DSH 正开着；或用 --port 指定端口（浏览器地址栏里那个）")
        return 1
    used = resolve_port()
    print("  接口     http://127.0.0.1:%s%s  （%s，探测耗时 %.1fs）" % (
        used, CONFIG["api_prefix"],
        "自动探测" if CONFIG["port"] == "auto" else "手动指定", time.time() - t0))
    pets = list(st.get("pets", {}).keys())
    print("[OK] 接口连通，宠物：%s" % (", ".join(pets) if pets else "（暂无，桌面窗首帧后会注册）"))
    print("     目标宠物：%s（作为 ?pet= 参数）" % CONFIG["pet"])

    # 校验要用的动画名是否真的在这个宠物的池子里（不在就早报错，别等触发时静默失败）
    # GET /config 返回的是 { "<petId>": { ...该宠物配置... } } 的映射
    cfg_all = pet_call("/config", None)
    allowed = set()
    try:
        if isinstance(cfg_all, dict):
            mine = cfg_all.get(str(CONFIG["pet"]))
            if isinstance(mine, dict):
                allowed = collect_anim_names(mine)
            else:
                print("[!!] /config 里没有 %s，可用宠物：%s" % (
                    CONFIG["pet"], ", ".join(cfg_all.keys())))
    except Exception as e:
        print("[!!] 解析配置失败（继续跑，但动画名校验跳过）：%s" % str(e)[:100])
    if allowed:
        missing = [n for n in (CONFIG["anim_up"], CONFIG["anim_down"]) if n not in allowed]
        print("[OK] 动画名校验：%s 有 %d 个可点播动画%s" % (
            CONFIG["pet"], len(allowed),
            "" if not missing else "  ✗ 缺失：%s（会触发失败！）" % ", ".join(missing)))
    print()

    last = {}          # 上次价格
    last_fire = {}     # 上次触发时间（按事件名）
    while True:
        try:
            mids = fetch_mids(CONFIG["hl_info_url"])
        except Exception as e:
            print("[!!] 取行情失败：%s" % str(e)[:120])
            if a.once:
                return 1
            time.sleep(CONFIG["poll_sec"])
            continue

        now = time.time()
        stamp = time.strftime("%H:%M:%S")
        for sym in CONFIG["watch"]:
            p = mids.get(sym)
            if p is None:
                continue
            p = float(p)
            prev = last.get(sym)
            last[sym] = p
            if prev is None:
                print("[%s] %-5s %12.4f  （建立基准）" % (stamp, sym, p))
                continue

            chg = (p - prev) / prev * 100.0
            print("[%s] %-5s %12.4f  %+.2f%%" % (stamp, sym, p, chg))

            event = None
            if chg >= CONFIG["up_pct"]:
                event = ("up", CONFIG["anim_up"],
                         "%s +%.2f%% 喵！冲" % (sym, chg))
            elif chg <= CONFIG["down_pct"]:
                event = ("down", CONFIG["anim_down"],
                         "%s %.2f%% …猫粮缩水" % (sym, chg))
            if not event:
                continue

            key = sym + ":" + event[0]
            if now - last_fire.get(key, 0) < CONFIG["cooldown_sec"]:
                print("    （%s 冷却中，跳过）" % key)
                continue
            last_fire[key] = now
            print("    >>> 触发 %s" % event[0])
            play_anim(event[1], dry=a.dry)
            broadcast(event[2], dry=a.dry)
            sys.stdout.flush()

        if a.once:
            return 0
        time.sleep(CONFIG["poll_sec"])


if __name__ == "__main__":
    sys.exit(main())