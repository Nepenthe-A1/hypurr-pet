"""定位 ffmpeg / ffprobe —— 让工具链在不同机器上都能跑。

解析顺序（先命中先用）：
  1. 环境变量 FFMPEG / FFPROBE（显式指定，最高优先）
  2. 系统 PATH（通常装了 ffmpeg 就有）
  3. 几个常见的 Windows 安装位置（含 winget / chocolatey / scoop 默认路径）

原先各脚本里写死的绝对路径（C:\\Users\\<某人>\\AppData\\...）会泄露作者用户名，
也会让别的机器一跑就报 FileNotFoundError。统一走这里。

用法：
    from ffmpeg_path import FFMPEG, FFPROBE
"""
import os
import shutil

_ENV_FFMPEG = "FFMPEG"
_ENV_FFPROBE = "FFPROBE"


def _candidates(name):
    """给出该可执行文件的所有候选路径（按优先级）。"""
    exe = name + ".exe" if os.name == "nt" else name
    out = []

    # 1) 环境变量
    env_val = os.environ.get(name.upper())
    if env_val:
        out.append(env_val)

    # 2) PATH
    found = shutil.which(name) or shutil.which(exe)
    if found:
        out.append(found)

    # 3) 常见安装位置
    local = os.environ.get("LOCALAPPDATA", "")
    progfiles = os.environ.get("ProgramFiles", "")
    progfiles86 = os.environ.get("ProgramFiles(x86)", "")
    userprofile = os.path.expanduser("~")

    roots = [
        os.path.join(local, "Programs", "ffmpeg"),
        os.path.join(local, "Microsoft", "WinGet", "Links"),
        os.path.join(progfiles, "ffmpeg"),
        os.path.join(progfiles86, "ffmpeg"),
        r"C:\ffmpeg",
        r"C:\ProgramData\chocolatey\bin",
        os.path.join(userprofile, "scoop", "shims"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        # 直接放在该目录下
        direct = os.path.join(root, exe)
        if os.path.isfile(direct):
            out.append(direct)
        # 或者藏在子目录里（如 ffmpeg-9.0.2-essentials_build/bin/）
        try:
            for sub in os.listdir(root):
                for tail in (os.path.join("bin", exe), exe):
                    cand = os.path.join(root, sub, tail)
                    if os.path.isfile(cand):
                        out.append(cand)
        except OSError:
            pass

    return out


def find(name):
    """找到可执行文件则返回路径，否则返回 None。"""
    for cand in _candidates(name):
        if cand and os.path.isfile(cand):
            return cand
    return None


def find_or_die(name):
    """找到则返回路径；找不到给出可操作的报错而不是让脚本崩在 subprocess。"""
    path = find(name)
    if path:
        return path
    raise SystemExit(
        "[XX] 找不到 {0}。\n"
        "     三种解决办法（任选其一）：\n"
        "       1. 装到 PATH 里：winget install Gyan.FFmpeg\n"
        "       2. 设置环境变量：set {1}=D:\\path\\to\\{0}.exe\n"
        "       3. 把 ffmpeg 解压到常见位置（如 %LOCALAPPDATA%\\Programs\\ffmpeg）".format(
            name, name.upper()
        )
    )


FFMPEG = find_or_die("ffmpeg")
FFPROBE = find_or_die("ffprobe")

__all__ = ["FFMPEG", "FFPROBE", "find", "find_or_die"]