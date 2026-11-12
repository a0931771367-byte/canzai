#!/usr/bin/env python3
"""口白產生器：把規格裡每一幕的 vo（口白文字）變成音檔，回報每段秒數。

用法：python3 voiceover.py <post.json> <快取資料夾>
- 快取檔名 NN_<文字雜湊>.mp3／.wav：文字沒改就直接重用，不重複花錢或額度。
- 引擎（post.voice.engine）：
  - "azure"：Azure AI Speech 官方 API（每月 50 萬字免費額度），需環境變數 AZURE_SPEECH_KEY、AZURE_SPEECH_REGION。
  - "files"：不自動合成，只用快取資料夾裡已經放好的檔（Higgsfield 產出或罐子自己錄的）。
- 禁止：任何真人聲音擷取或克隆（2026-11-12 罐子規定）。只用合成預設聲或罐子本人錄音。
輸出（stdout JSON）：{"lines":[{"i":幕序,"file":路徑,"sec":秒數}], "missing":[{"i":幕序,"text":文字,"want":應存檔名}]}
"""
import hashlib, json, os, subprocess, sys, urllib.request
from xml.sax.saxutils import escape


def h(text, voice):
    return hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()[:10]


def dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def tidy(src, tempo=1.0):
    """tempo：整段加速（不變音高），合成聲偏慢時用 1.1～1.2。
    去掉頭尾靜音、把句中超過 0.25 秒的停頓縮成 0.15 秒（合成聲常前後各留 0.3～0.5 秒）。"""
    out = os.path.splitext(src)[0] + f".tidy{tempo:g}.wav"
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(src):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-af",
                        "silenceremove=start_periods=1:start_threshold=-40dB:stop_periods=-1:stop_duration=0.25:stop_threshold=-40dB:stop_silence=0.15" + (f",atempo={tempo}" if tempo != 1 else ""),
                        "-ar", "44100", out], check=True)
    return out


def azure(text, voice, rate, out):
    key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
    if not key or not region:
        return False
    ssml = (f'<speak version="1.0" xml:lang="zh-TW"><voice name="{voice}">'
            f'<prosody rate="{rate}">{escape(text)}</prosody></voice></speak>')
    req = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode(), method="POST",
        headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3", "User-Agent": "canzai-vo"})
    with urllib.request.urlopen(req, timeout=30) as r, open(out, "wb") as f:
        f.write(r.read())
    return True


def main():
    post = json.load(open(sys.argv[1], encoding="utf-8"))
    cache = sys.argv[2]
    os.makedirs(cache, exist_ok=True)
    v = post.get("voice", {})
    engine, voice, rate = v.get("engine", "files"), v.get("name", "zh-TW-HsiaoChenNeural"), v.get("rate", "+8%")
    lines, missing = [], []
    for i, s in enumerate(post["slides"]):
        text = s.get("vo")
        if not text:
            continue
        stem = f"{i + 1:02d}_{h(text, voice)}"
        hit = next((os.path.join(cache, stem + ext) for ext in (".mp3", ".wav", ".m4a") if os.path.exists(os.path.join(cache, stem + ext))), None)
        if not hit and engine == "azure" and azure(text, voice, rate, os.path.join(cache, stem + ".mp3")):
            hit = os.path.join(cache, stem + ".mp3")
        if hit:
            hit = tidy(hit, float(v.get("tempo", 1.0)))
            lines.append({"i": i, "file": hit, "sec": round(dur(hit), 2)})
        else:
            missing.append({"i": i, "text": text, "want": os.path.join(cache, stem + ".mp3")})
    print(json.dumps({"lines": lines, "missing": missing}, ensure_ascii=False))


if __name__ == "__main__":
    main()
