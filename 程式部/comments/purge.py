#!/usr/bin/env python3
"""留言資料 90 天自動清除（法務部要求：個資最小保存）。

清掉超過 N 天的留言紀錄（帳號、留言內容）。處理資料夾內的 .json 與 .csv：
  - 留言陣列 JSON（ig_comments.py fetch 產出，欄位 timestamp）
  - 待審表 JSON／CSV（classify.py 產出，欄位「時間」）
Google 試算表「留言回覆待審」由每日排程的 Claude 依同樣規則刪除超過 90 天的列。

用法：
    python3 purge.py output/ --days 90
    python3 purge.py output/ --days 90 --dry-run
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os


def old(ts, cutoff):
    if not ts:
        return False
    try:
        t = dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        try:
            t = dt.datetime.strptime(ts[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return False
    return t < cutoff


def ts_of(r):
    return r.get("timestamp") or r.get("時間") or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.days)
    total = 0
    for p in glob.glob(os.path.join(a.folder, "**", "*.json"), recursive=True):
        try:
            rows = json.load(open(p, encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict) or not ts_of(rows[0]) and "留言" not in rows[0] and "text" not in rows[0]:
            continue
        keep = [r for r in rows if not old(ts_of(r), cutoff)]
        n = len(rows) - len(keep)
        if n:
            total += n
            print(f"{p}：刪除 {n} 則")
            if not a.dry_run:
                json.dump(keep, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for p in glob.glob(os.path.join(a.folder, "**", "*.csv"), recursive=True):
        with open(p, encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            fields, rows = rd.fieldnames, list(rd)
        if not fields or "時間" not in fields:
            continue
        keep = [r for r in rows if not old(r["時間"], cutoff)]
        n = len(rows) - len(keep)
        if n:
            total += n
            print(f"{p}：刪除 {n} 則")
            if not a.dry_run:
                with open(p, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=fields)
                    w.writeheader(); w.writerows(keep)
    print(f"{'[dry-run] ' if a.dry_run else ''}共清除 {total} 則超過 {a.days} 天的留言紀錄")


if __name__ == "__main__":
    main()
