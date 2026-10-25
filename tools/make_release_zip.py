# -*- coding: utf-8 -*-
"""把便携版目录打成可直接分发的 zip（Windows 版）。

为什么要写脚本而不是右键压缩：
  1. 必须保证 zip 内部路径用**正斜杠**（Windows 的 os.path.join 给反斜杠，
     在某些解压器上会被当成字面反斜杠）。
  2. 必须检查**顶层只有一个目录**（历史上出现过
     `HypurrPet-Portable\\HypurrPet-Portable\\` 的嵌套副本，
     导致 zip 体积翻倍、动画重复 36 条）。
  3. 打包前做体检：文件数、体积、动画条数、许可文件是否在。

用法：
    python tools/make_release_zip.py <包目录> <输出.zip> [--name HypurrPet-Portable]
"""
import argparse
import os
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OK, WARN, BAD = "[OK]", "[!!]", "[XX]"

# 这些必须存在，否则不算一个可用的包
REQUIRED = [
    "app",
    "dsh-home",
    "electron",
    "app/LICENSE-dsh-pet",
    "app/NOTICE.md",
    "dsh-home/dsh-pet/pet/hypurr-config.json",
    "启动 Hypurr.vbs",
    "停止 Hypurr.bat",
]


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="便携版目录")
    ap.add_argument("out", help="输出 zip 路径")
    ap.add_argument("--name", default="HypurrPet-Portable", help="zip 内顶层目录名")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        raise SystemExit("%s 目录不存在: %s" % (BAD, src))

    # ---- 体检 1：顶层不能有嵌套的同名副本 ----
    top = [e for e in os.listdir(src)]
    nested = os.path.join(src, os.path.basename(src))
    if os.path.isdir(nested):
        raise SystemExit(
            "%s 发现嵌套副本 %s —— 打包会让 zip 体积翻倍。先删掉再打。" % (BAD, nested)
        )

    # ---- 体检 2：必需文件 ----
    missing = []
    for rel in REQUIRED:
        if not os.path.exists(os.path.join(src, *rel.split("/"))):
            missing.append(rel)
    if missing:
        print("%s 缺少必需文件：" % WARN)
        for m in missing:
            print("     - %s" % m)
    else:
        print("%s 必需文件齐全（含 app/LICENSE-dsh-pet 与 NOTICE.md）" % OK)

    # ---- 统计 ----
    files = []
    total = 0
    for root, _dirs, names in os.walk(src):
        for n in names:
            fp = os.path.join(root, n)
            rel = os.path.relpath(fp, src)
            files.append(rel)
            total += os.path.getsize(fp)

    webm = [f for f in files if f.lower().endswith(".webm")]
    pet_webm = [f for f in webm if "hypurr-animation" in f.replace("\\", "/")]

    print("文件数：%d    未压缩体积：%s" % (len(files), human(total)))
    print("动画：hypurr-animation 下 %d 条（全包共 %d 条 webm）" % (len(pet_webm), len(webm)))
    if len(pet_webm) != 18:
        print("%s 预期 18 条 Hypurr 动画，实际 %d 条 —— 请确认" % (WARN, len(pet_webm)))

    # ---- 写 zip ----
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)

    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, names in os.walk(src):
            for name in names:
                fp = os.path.join(root, name)
                rel = os.path.relpath(fp, src)
                # 关键：正斜杠
                arc = args.name + "/" + rel.replace("\\", "/")
                z.write(fp, arc)
                n += 1

    zsize = os.path.getsize(out)
    print("%s 已写出：%s" % (OK, out))
    print("     条目 %d 个，压缩后 %s（压缩率 %.0f%%）" % (n, human(zsize), 100.0 * zsize / max(total, 1)))

    # ---- 回读校验 ----
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit("%s zip 校验失败，首个坏条目: %s" % (BAD, bad))
        names = z.namelist()
        tops = {nm.split("/")[0] for nm in names}
        if tops != {args.name}:
            raise SystemExit("%s zip 顶层目录不是唯一的一个：%s" % (BAD, tops))
        has_lic = any(nm.endswith("app/LICENSE-dsh-pet") for nm in names)
        print("%s 回读校验通过（顶层唯一、无损坏、许可文件在内=%s）" % (OK, has_lic))


if __name__ == "__main__":
    main()