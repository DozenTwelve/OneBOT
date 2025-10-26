#!/usr/bin/env python3
import os
import sys

import psutil


def main() -> int:
    current_pid = os.getpid()
    for proc in psutil.process_iter(attrs=["pid", "cmdline"]):
        if proc.info["pid"] == current_pid:
            continue
        cmdline = proc.info.get("cmdline") or []
        if any("bot.py" in segment for segment in cmdline):
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
