"""复验 dsh-pet 的配置落地结果：解析用户主配置 + 种类文件，算出"最终会显示哪些宠物"。

用法:
    python tools/verify_dsh_config.py [--dsh-home <路径>]

它按插件自己 readJsonc 的规则剥注释（带字符串保护），所以带 // 注释的配置也能解析。
注意：这只是**轻量模拟**——插件真正的合并逻辑在 src/host/config.ts 的 mergeEntry/mergePets，
本脚本复刻了与本项目相关的语义（用户层 pets 替换列表、缺字段继承内置 pets[0]、display 判定）。
"""
import argparse, json, os, sys

OK, WARN, BAD = "[OK]", "[!!]", "[XX]"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SHOW = ("web", "desktop", "both")


def strip_jsonc(t):
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c == '"':
            j = i + 1
            while j < n:
                if t[j] == "\\":
                    j += 2
                    continue
                if t[j] == '"':
                    break
                j += 1
            out.append(t[i:j + 1])
            i = j + 1
            continue
        if t.startswith("//", i):
            j = t.find("\n", i)
            i = n if j < 0 else j
            continue
        if t.startswith("/*", i):
            j = t.find("*/", i)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def load_jsonc(p):
    with open(p, encoding="utf-8") as f:
        return json.loads(strip_jsonc(f.read()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsh-home", default=os.path.join(os.path.expanduser("~"), ".dsh"))
    a = ap.parse_args()
    d = os.path.join(a.dsh_home, "dsh-pet")
    print("dsh-pet 用户目录: %s" % d)
    if not os.path.isdir(d):
        print(BAD + " 目录不存在（插件还没跑过？）")
        return 1

    entries = []   # (来源, pets[])
    for name, path in (("用户主配置 main-config.jsonc", os.path.join(d, "main-config.jsonc")),
                       ("用户主配置（旧）main-config.json", os.path.join(d, "main-config.json"))):
        if not os.path.exists(path):
            continue
        try:
            j = load_jsonc(path)
            entries.append((name, j.get("pets") or [], path))
            print("%s %s 解析成功，pets=%d" % (OK, name, len(j.get("pets") or [])))
        except Exception as e:
            print("%s %s 解析失败: %s" % (BAD, name, e))
        break

    petdir = os.path.join(d, "pet")
    if os.path.isdir(petdir):
        for f in sorted(os.listdir(petdir)):
            if not f.endswith((".json", ".jsonc")):
                continue
            path = os.path.join(petdir, f)
            try:
                j = load_jsonc(path)
                prefix = f.rsplit("-config.", 1)[0]
                anim = os.path.join(petdir, prefix + "-animation")
                n_anim = len([x for x in os.listdir(anim)]) if os.path.isdir(anim) else 0
                entries.append(("种类文件 " + f + "（素材根=%s，素材 %d 个）" % (prefix, n_anim), j.get("pets") or [], path))
            except Exception as e:
                print("%s %s 解析失败: %s" % (BAD, f, e))

    print("\n--- 各条目里的宠物实例 ---")
    visible = []
    for src, pets, path in entries:
        print("  【%s】" % src)
        for p in pets:
            disp = str(p.get("display", "(未写→默认 both)"))
            flags = "balance=%s whisper=%s workStatus=%s" % (
                p.get("balanceEnabled"), p.get("whisperEnabled"), p.get("workStatusEnabled"))
            mark = "显示" if disp in SHOW else "不显示"
            print("     id=%-10s name=%-12s display=%-8s → %s   %s" % (
                p.get("id"), p.get("name"), disp, mark, flags))
            if disp in SHOW:
                visible.append(p.get("id"))

    print("\n--- 结论 ---")
    print("  最终可见宠物: %s" % (", ".join(visible) if visible else "（无）"))
    if visible == ["hypurr"]:
        print("%s 只剩 Hypurr，女仆已静默 —— 符合预期" % OK)
    elif not visible:
        print(BAD + " 一只都不显示，检查 display 取值")
    else:
        print(WARN + " 还有其它宠物在显示: %s" % ", ".join(x for x in visible if x != "hypurr"))
    return 0


if __name__ == "__main__":
    sys.exit(main())