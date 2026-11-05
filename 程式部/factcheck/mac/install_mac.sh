#!/bin/bash
# 在罐子的 Mac 上跑一次就好：bash install_mac.sh
# 做三件事：clone 快照分支到 ~/canzai-snapshots、放好抓取程式、設定 launchd 每天 00:30、11:30、17:30 自動跑。
# 需要：Mac 已經能用 git 推到 github.com/a0931771367-byte/canzai（GitHub Desktop 或 gh auth login 登入過就可以）。
set -e
REPO_URL="${1:-https://github.com/a0931771367-byte/canzai.git}"
DIR="$HOME/canzai-snapshots"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo /nonexistent)"
if [ ! -d "$DIR/.git" ]; then
  git clone -q "$REPO_URL" "$DIR"
  cd "$DIR"
  if git ls-remote --exit-code --heads origin snapshots >/dev/null 2>&1; then
    git checkout -q snapshots
  else
    git checkout -q --orphan snapshots && git rm -rfq . >/dev/null 2>&1 || true
    echo "# 官網快照（自動產生，給發文前重查用）" > README.md
    touch urls.txt && git add -A && git commit -qm "建立快照分支" && git push -q -u origin snapshots
  fi
fi
mkdir -p "$HOME/Library/Application Support/canzai"
if [ -f "$HERE/fetch_snapshots.py" ]; then
  cp "$HERE/fetch_snapshots.py" "$HOME/Library/Application Support/canzai/fetch_snapshots.py"
else  # 用 curl | bash 直接跑時，從 GitHub 下載
  curl -fsSL https://raw.githubusercontent.com/a0931771367-byte/canzai/main/tools/mac/fetch_snapshots.py \
    -o "$HOME/Library/Application Support/canzai/fetch_snapshots.py"
fi
PLIST="$HOME/Library/LaunchAgents/money.canzai.snapshots.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>money.canzai.snapshots</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>$HOME/Library/Application Support/canzai/fetch_snapshots.py</string>
  </array>
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/canzai-snapshots.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/canzai-snapshots.log</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "裝好了。現在先跑一次測試："
/usr/bin/python3 "$HOME/Library/Application Support/canzai/fetch_snapshots.py"
echo "之後每天 00:30、11:30、17:30 自動跑（Mac 睡眠時會在醒來後補跑），紀錄在 ~/Library/Logs/canzai-snapshots.log"
