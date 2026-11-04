#!/usr/bin/env python3
"""排程路線決定：罐仔只走 IG 官方 API（Instagram Login，不綁 FB）。

11/3 罐子決定不用 Metricool，所以路線只剩兩種：
  ig_api  有 IG token（環境變數 IG_TOKEN 或 數據部/.ig_token）→ 由 run_schedule.py（GitHub Actions 每 10 分鐘）發
  hold    沒有 token → 不排程，由 Claude 在討論串回報

用法：python3 route.py    # 印出路線；hold 時結束碼 3
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.environ.get("IG_TOKEN_FILE", os.path.join(os.path.dirname(os.path.dirname(HERE)), "數據部", ".ig_token"))


def decide():
    if os.environ.get("IG_TOKEN") or (os.path.exists(TOKEN_FILE) and os.path.getsize(TOKEN_FILE) > 20):
        return "ig_api", "IG 官方 API 已授權"
    return "hold", "IG 官方 API 還沒授權（沒有 IG_TOKEN），先不排程"


if __name__ == "__main__":
    route, why = decide()
    print(f"{route}：{why}")
    sys.exit(0 if route != "hold" else 3)
