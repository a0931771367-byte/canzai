// 貼文產生器：讀一週的貼文規格（posts.json），產出圖卡 PNG、Reel MP4、文案 md、總覽。
// 用法：node make_posts.js <規格檔.json> <輸出資料夾> [只做某篇id]
const fs = require('fs');
const path = require('path');
const os = require('os');
const { canzai, PALETTE: P } = require('./canzai');
const R = require('./render');
const CONFIG = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
// CIS v2：封面底色由 config.cover_theme 決定（teal＝現行薄荷綠；navy＝信任藍，搭配大頭貼 A/B）。罐子選定方向前維持 teal。
const COVER_BG = CONFIG.cover_theme === 'navy' ? P.line : P.body;
const COVER_INK = CONFIG.cover_theme === 'navy' ? P.band : P.line;

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
// *重點* → 螢光筆底線；**強調** → 珊瑚橘粗體；\n → 換行
// v2：「」內 8 字以內不斷行，避免「免／息」這種被拆開的孤字
const keep = h => h.replace(/「([^」<]{1,8})」/g, '<span style="white-space:nowrap">「$1」</span>');
const fmt = s => keep(esc(s)).replace(/\*\*(.+?)\*\*/g, '<b class="em">$1</b>').replace(/\*(.+?)\*/g, '<span class="hl">$1</span>').replace(/\n/g, '<br>').replace(/&lt;kw>/g, `<span class="kw">${esc(CONFIG.comment_keywords[0])}</span>`);

const BASE_CSS = `
body{background:${P.band};font-family:'Noto Sans TC';color:${P.line};position:relative}
.hl{background:linear-gradient(transparent 58%, ${P.lid} 58%, ${P.lid} 92%, transparent 92%);padding:0 4px}
.em{color:${P.accentText};font-weight:900}
.slide{position:absolute;inset:0;overflow:hidden}
.top{position:absolute;left:96px;right:96px;top:84px;display:flex;justify-content:space-between;align-items:center}
.chip{background:${P.line};color:${P.band};font-weight:900;font-size:30px;padding:10px 26px;border-radius:40px}
.chip.alt{background:${P.accentText}}
.pg{font-weight:900;font-size:30px;color:${P.muted}}
.foot{position:absolute;left:96px;bottom:64px;font-size:28px;font-weight:500;color:${P.muted}}
.note{position:absolute;left:96px;bottom:112px;font-size:26px;font-weight:500;color:${P.muted}}
.label{display:inline-block;font-weight:900;font-size:40px;letter-spacing:2px;color:${P.tealText};margin-bottom:14px}
h1{font-weight:900;line-height:1.25;letter-spacing:1px;text-wrap:balance}
p{text-wrap:pretty}
.body{font-weight:500;line-height:1.6}
.char{position:absolute}
.bubble{position:absolute;background:#fff;border:5px solid ${P.line};border-radius:36px;padding:18px 28px;font-family:Huninn;font-size:36px;line-height:1.35;max-width:520px}
.bubble:after{content:'';position:absolute;right:70px;bottom:-26px;border:14px solid transparent;border-top:18px solid ${P.line}}
.panel{background:#fff;border:5px solid ${P.line};border-radius:36px;box-shadow:10px 10px 0 ${P.line}}
.row{display:flex;justify-content:space-between;align-items:baseline;padding:18px 0;border-bottom:3px dashed #D9D2C3;font-weight:500}
.row:last-child{border-bottom:none}
.row .v{font-weight:900}
.result{margin-top:24px;background:${P.accentText};color:#fff;border-radius:24px;padding:22px 30px;display:flex;flex-wrap:wrap;gap:6px 24px;justify-content:space-between;font-weight:900}
.result span{white-space:nowrap}
.item{display:flex;gap:22px;align-items:flex-start;margin:0 0 26px;font-weight:500;line-height:1.45}
.box{flex:none;width:52px;height:52px;border:5px solid ${P.line};border-radius:14px;background:#fff;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:30px}
.box.n{background:${P.lid}}
.box.ok:after{content:'';width:22px;height:12px;border-left:7px solid ${P.tealText};border-bottom:7px solid ${P.tealText};transform:rotate(-45deg) translate(2px,-3px)}
.kw{display:inline-block;background:${P.lid};border:5px solid ${P.line};border-radius:20px;padding:4px 26px;font-weight:900;margin:0 6px}
.cover{background:${COVER_BG}}
.cover .pg{color:${COVER_INK};opacity:.75}
.cover .panel{position:absolute;left:96px;right:96px}
.cover h1{color:${P.line}}
.sub{font-weight:500;color:${P.line};opacity:.85}
.prog{position:absolute;left:96px;right:96px;top:150px;height:10px;border-radius:5px;background:#E9E1D0}
.prog i{display:block;height:100%;border-radius:5px;background:${P.accent}}
`;

// 依最長一行的字數自動縮字，避免標題被折成孤字
function fit(title, width, max) {
  const lines = String(title).replace(/\*/g, '').split('\n');
  const w = Math.max(...lines.map(l => [...l].reduce((a, c) => a + (/[\x00-\x7F]/.test(c) ? 0.56 : 1), 0)));
  return Math.floor(Math.min(max, width / Math.max(w, 1)));
}

function charHTML(s, x, y, size, def = {}) {
  return `<div class="char a-char" style="left:${x}px;top:${y}px">${canzai({ face: s.face || def.face || 'happy', pose: s.pose || def.pose || 'fly', size })}</div>`;
}

// ---------- 版面：每種 slide kind 在 4:5 (W=1080,H=1350) 或 9:16 (H=1920) 下的 HTML ----------
function slideHTML(s, i, n, post, H) {
  const tall = H > 1500;
  const top0 = tall ? 400 : 200;           // 內容起始 y（Reel 避開上方 UI）
  const charY = tall ? 1160 : H - 520;
  const brand = `<div class="foot">${esc(CONFIG.brand)}</div>`;
  const note = s.note ? `<div class="note">${esc(s.note)}</div>` : (post.note && s.kind !== 'cover' && s.kind !== 'cta' ? `<div class="note">${esc(post.note)}</div>` : '');
  const top = `<div class="top" style="${tall ? 'top:250px;right:230px' : ''}"><span style="display:flex;gap:14px"><span class="chip ${s.kind === 'cover' ? 'alt' : ''}">${esc(post.kicker)}</span>${post.picked && i === 0 ? `<span class="chip" style="background:${P.lid};color:${P.line}">你選的：${esc(post.picked)}</span>` : ''}${post.sponsored && i === 0 ? `<span class="chip" style="background:#fff;color:${P.line};border:4px solid ${P.line}">廣告</span>` : ''}</span>${post.type === 'carousel' ? `<span class="pg">${i + 1}/${n}</span>` : ''}</div>`;
  const bubble = s.bubble ? `<div class="bubble a" data-in="1.0" style="right:${tall ? 470 : 360}px;top:${charY - (tall ? 10 : 60)}px;${tall ? "font-size:46px" : ""}">${fmt(s.bubble)}</div>` : '';

  switch (s.kind) {
    case 'cover': {
      const ty = tall ? 360 : 230;
      return `<div class="slide cover">${top}
        <div class="panel a" data-in="0.1" style="top:${ty}px;padding:${tall ? '50px 48px 44px' : '50px 56px 46px'};${tall ? 'right:200px' : ''}">
          <h1 style="font-size:${s.size || fit(s.title, tall ? 620 : 660, tall ? 140 : 108)}px">${fmt(s.title)}</h1>
          ${s.sub ? `<p class="sub a" data-in="${tall ? 0.3 : 0.6}" style="font-size:${tall ? 50 : 42}px;margin-top:22px">${fmt(s.sub)}</p>` : ''}
        </div>
        ${charHTML(s, tall ? 270 : 300, tall ? 1050 : 790, tall ? 560 : 500, { face: 'love', pose: 'cheer' })}
        <div class="foot" style="color:${COVER_INK};opacity:.85">${esc(CONFIG.brand)}</div></div>`;
    }
    case 'text':
      return `<div class="slide">${top}
        <div style="position:absolute;left:96px;right:${tall ? 230 : 96}px;top:${top0 + 40}px">
          ${s.label ? `<span class="label a" data-in="0">${esc(s.label)}</span>` : ''}
          <h1 class="a" data-in="0.15" style="font-size:${s.size || fit(s.title, tall ? 720 : 820, tall ? 124 : 96)}px">${fmt(s.title)}</h1>
          ${s.body ? `<p class="body a" data-in="0.7" style="font-size:${tall ? 62 : 50}px;margin-top:40px">${fmt(s.body)}</p>` : ''}
        </div>${bubble}${charHTML(s, tall ? 520 : 620, tall ? charY : charY - 40, tall ? 500 : 420)}${brand}${note}</div>`;
    case 'calc':
      return `<div class="slide">${top}
        <div style="position:absolute;left:96px;right:${tall ? 230 : 96}px;top:${top0 + 30}px">
          ${s.label ? `<span class="label a" data-in="0">${esc(s.label)}</span>` : ''}
          <h1 class="a" data-in="0.15" style="font-size:${s.size || fit(s.title, tall ? 720 : 820, tall ? 110 : 80)}px">${fmt(s.title)}</h1>
          <div class="panel a" data-in="0.5" style="margin-top:36px;padding:22px 40px;font-size:${tall ? 54 : 40}px">
            ${s.rows.map((r, k) => `<div class="row a" data-in="${0.9 + k * 0.6}"><span>${fmt(r[0])}</span><span class="v">${fmt(r[1])}</span></div>`).join('')}
            ${s.result ? `<div class="result a" data-in="${0.9 + s.rows.length * 0.6 + 0.3}"><span>${fmt(s.result[0])}</span><span>${fmt(s.result[1])}</span></div>` : ''}
          </div>
          ${s.body ? `<p class="body a" data-in="${1.6 + s.rows.length * 0.6}" style="font-size:${tall ? 54 : 38}px;margin-top:30px">${fmt(s.body)}</p>` : ''}
        </div>${s.noChar ? '' : charHTML(s, tall ? 560 : 720, tall ? 1220 : H - 400, tall ? 440 : 300, { face: 'smug', pose: 'calc' })}${brand}${note}</div>`;
    case 'list': {
      const numbered = s.numbered;
      return `<div class="slide">${top}
        <div style="position:absolute;left:96px;right:${tall ? 230 : 96}px;top:${top0 + 20}px">
          ${s.label ? `<span class="label a" data-in="0">${esc(s.label)}</span>` : ''}
          <h1 class="a" data-in="0.1" style="font-size:${s.size || fit(s.title, tall ? 720 : 820, tall ? 110 : 84)}px;margin-bottom:48px">${fmt(s.title)}</h1>
          ${s.items.map((t, k) => `<div class="item a" data-in="${0.6 + k * 0.7}" style="font-size:${s.fs || (tall ? 64 : 48)}px"><span class="box ${numbered ? 'n' : 'ok'}">${numbered ? k + 1 : ''}</span><span>${fmt(t)}</span></div>`).join('')}
        </div>${s.noChar ? '' : charHTML(s, tall ? 560 : 700, tall ? 1220 : H - 400, tall ? 440 : 330, { face: 'wink', pose: 'point' })}${brand}${note}</div>`;
    }
    case 'cta':
      return `<div class="slide" style="background:${P.lid}">${top}
        <div style="position:absolute;left:96px;right:${tall ? 230 : 96}px;top:${top0 + 60}px;text-align:center">
          <h1 class="a" data-in="0.1" style="font-size:${s.size || fit(s.title, tall ? 720 : 820, tall ? 110 : 90)}px">${fmt(s.title)}</h1>
          ${s.body ? `<p class="body a" data-in="0.7" style="font-size:${tall ? 54 : 44}px;margin-top:36px">${fmt(s.body)}</p>` : ''}
          <p class="a" data-in="1.0" style="display:inline-block;margin-top:34px;background:${P.line};color:${P.band};font-weight:900;font-size:34px;padding:12px 30px;border-radius:40px">＋追蹤罐仔｜${esc(CONFIG.follow_reason || '每週一個刷卡答案')}</p>
        </div>${charHTML(s, tall ? 270 : 300, tall ? 1040 : H - 600, tall ? 540 : 480, { face: 'joy', pose: 'wave' })}
        <div class="foot" style="opacity:.85">${esc(CONFIG.brand)}</div></div>`;
    case 'stat': {
      // 研究型 Reel（2026-11-05 學 dudefishing_tw）：一個官方／研究大數字，數字會從 0 跳到目標值，下方固定標出處
      const big = s.num != null ? `<span class="cnt" data-to="${s.num}" data-dec="${s.dec || 0}">${tall ? '0' : Number(s.num).toLocaleString('en-US', { minimumFractionDigits: s.dec || 0 })}</span>` : '';
      return `<div class="slide">${top}
        <div style="position:absolute;left:96px;right:${tall ? 230 : 96}px;top:${top0 + 30}px">
          ${s.label ? `<span class="label a" data-in="0">${esc(s.label)}</span>` : ''}
          <div class="a" data-in="0.1" style="font-weight:900;color:${P.line};line-height:1.05;font-size:${s.size || (tall ? 190 : 150)}px;letter-spacing:-2px;white-space:nowrap">${big}<span style="font-size:.42em;margin-left:10px">${fmt(s.unit || '')}</span></div>
          ${s.title ? `<h1 class="a" data-in="0.5" style="font-size:${fit(s.title, tall ? 720 : 820, tall ? 84 : 70)}px;margin-top:26px">${fmt(s.title)}</h1>` : ''}
          ${s.body ? `<p class="body a" data-in="0.9" style="font-size:${tall ? 52 : 40}px;margin-top:26px">${fmt(s.body)}</p>` : ''}
        </div>${s.noChar ? '' : charHTML(s, tall ? 560 : 720, tall ? 1220 : H - 400, tall ? 420 : 300, { face: 'shock', pose: 'think' })}${brand}${note}</div>`;
    }
    case 'bars': {
      // 長條比較：rows=[[名稱, 數值, 顯示文字]]，長條依最大值等比例長出來；result 是一句結論
      const max = Math.max(...s.rows.map(r => +r[1]));
      const bar = (r, k) => `<div class="a" data-in="${0.4 + k * 0.5}" style="margin-top:34px">
          <div style="display:flex;justify-content:space-between;font-weight:900;font-size:${tall ? 50 : 40}px"><span>${fmt(r[0])}</span><span>${fmt(r[2] ?? r[1])}</span></div>
          <div style="margin-top:12px;height:${tall ? 64 : 52}px;border:5px solid ${P.line};border-radius:18px;background:#fff;overflow:hidden">
            <i class="bar" data-w="${(+r[1] / max * 100).toFixed(1)}" data-in="${0.6 + k * 0.5}" style="display:block;height:100%;width:${tall ? 0 : (+r[1] / max * 100).toFixed(1)}%;background:${k === 0 ? P.line : P.lid}"></i></div></div>`;
      return `<div class="slide">${top}
        <div style="position:absolute;left:96px;right:${tall ? 230 : 96}px;top:${top0 + 30}px">
          ${s.label ? `<span class="label a" data-in="0">${esc(s.label)}</span>` : ''}
          <h1 class="a" data-in="0.1" style="font-size:${s.size || fit(s.title, tall ? 720 : 820, tall ? 100 : 80)}px">${fmt(s.title)}</h1>
          ${s.rows.map(bar).join('')}
          ${s.result ? `<div class="result a" data-in="${0.8 + s.rows.length * 0.5}" style="font-size:${tall ? 52 : 40}px;margin-top:40px"><span>${fmt(s.result[0])}</span><span>${fmt(s.result[1])}</span></div>` : ''}
        </div>${s.noChar ? '' : charHTML(s, tall ? 560 : 720, tall ? 1240 : H - 380, tall ? 400 : 280, { face: 'think', pose: 'calc' })}${brand}${note}</div>`;
    }
    case 'vote': {
      // 片尾固定卡：追蹤罐仔＋A/B 投票選下期題目（被被專案驗證過的格式）
      const opt = (k, t) => `<div class="panel a" data-in="${k === 'A' ? 0.4 : 0.7}" style="display:flex;align-items:center;gap:26px;padding:26px 34px;margin-top:28px;font-size:${tall ? 50 : 44}px;font-weight:900"><span class="box n" style="width:76px;height:76px;font-size:44px;border-radius:20px">${k}</span><span>${fmt(t)}</span></div>`;
      return `<div class="slide" style="background:${P.body}">${top}
        <div style="position:absolute;left:96px;right:${tall ? 230 : 96}px;top:${top0}px">
          <h1 class="a" data-in="0" style="font-size:${tall ? 92 : 80}px;color:${P.line}">${fmt(s.title || '下週想看哪個？\n*你來選*')}</h1>
          ${opt('A', s.options[0])}${opt('B', s.options[1])}
          <p class="body a" data-in="1.0" style="font-size:${tall ? 48 : 42}px;margin-top:36px;font-weight:900">${fmt(s.body || '留言 **A** 或 **B**・追蹤罐仔看結果')}</p>
        </div>${charHTML(s, tall ? 520 : 640, tall ? 1180 : H - 430, tall ? 420 : 360, { face: 'joy', pose: 'cheer' })}
        <div class="foot" style="opacity:.8">${esc(CONFIG.brand)}</div></div>`;
    }
  }
  throw new Error('unknown kind ' + s.kind);
}

// ---------- 動畫腳本：window.setT(t) 依時間控制每個場景與元素 ----------
const ANIM_JS = `
const scenes=[...document.querySelectorAll('.scene')];
const starts=[];let acc=0;scenes.forEach(s=>{starts.push(acc);acc+=+s.dataset.dur});
const TOTAL=acc;
const ease=x=>1-Math.pow(1-Math.min(Math.max(x,0),1),3);
window.setT=function(t){
  scenes.forEach((s,i)=>{
    const st=starts[i],en=st+(+s.dataset.dur),lt=t-st;
    const on=t>=st&&t<en; s.style.display=on?'block':'none'; if(!on)return;
    const out=Math.min(Math.max((en-t)/0.25,0),1);const first=i===0;
    // 2026-11-10 數據部：開頭不用靜態封面，第一幕直接上答案，內容 0.35 倍速快速進場
    const fast=first&&!(s.classList.contains('cover')||s.querySelector('.cover'));const k=fast?0.35:1;
    s.style.opacity=i===scenes.length-1?1:out;
    s.querySelectorAll('.a').forEach(e=>{const d=(+(e.dataset.in||0))*k;const p=(first&&d<(fast?0.2:0.5))?1:ease((lt-d)/(fast?0.25:0.4));e.style.opacity=p;e.style.transform='translateY('+(1-p)*40+'px)'});
    s.querySelectorAll('.a-char').forEach(e=>{const p=first?1:ease(lt/0.45);const sc=0.6+0.4*p;e.style.opacity=first?1:Math.min(1,lt/0.2);
      e.style.transform='translateY('+(Math.sin(t*3.2)*14)+'px) scale('+sc+')';});
    s.querySelectorAll('.cnt').forEach(e=>{const p=first?1:ease((lt-0.3)/1.0);const v=(+e.dataset.to)*p;e.textContent=v.toLocaleString('en-US',{minimumFractionDigits:+e.dataset.dec,maximumFractionDigits:+e.dataset.dec})});
    s.querySelectorAll('.bar').forEach(e=>{const p=ease((lt-(+e.dataset.in)*k)/(fast?0.5:0.8));e.style.width=(+e.dataset.w*p)+'%'});
    s.querySelectorAll('.flapL,.flapR').forEach(w=>{w.setAttribute('transform','rotate('+(Math.sin(t*14)*14)+')')});
  });
  const bar=document.querySelector('.prog i'); if(bar) bar.style.width=(Math.min(t/TOTAL,1)*100)+'%';
};
window.TOTAL=TOTAL; setT(0);`;

async function renderCarousel(post, dir) {
  const n = post.slides.length;
  const files = [];
  for (let i = 0; i < n; i++) {
    const html = R.wrap(slideHTML(post.slides[i], i, n, post, 1350), 1080, 1350, BASE_CSS + '.a{opacity:1}');
    const f = path.join(dir, `${String(i + 1).padStart(2, '0')}.png`);
    await R.png(html, 1080, 1350, f);
    files.push(f);
  }
  return files;
}

// ---------- 聲音：程式合成音效（sfx_synth.py）＋Artlist 會員背景音樂，響度 -16 LUFS ----------
// IG API 自動發 Reel 不能選 IG 音樂庫，所以聲音要先混進 mp4（2026-11-08 起）
const BGM = ['Out The Window - Under the Sun.mp3', 'Mansij - Macchiato.mp3'];
function sfxEvents(post) {
  const ev = []; let st = 0;
  post.slides.forEach((s, i) => {
    const d = s.dur || 5;
    const k = (i === 0 && s.kind !== 'cover') ? 0.35 : 1; // 第一幕快速進場，音效跟著提早
    const push0 = ev.push.bind(ev); const evp = ([n, t]) => push0([n, st + (t - st) * k]);
    if (i === 0) { ev.push(['pop', 0.0]); if (k === 1) ev.push(['ding', 0.5]); }
    else ev.push(['whoosh', st]);
    ev.push = (x) => evp(x);
    if (s.kind === 'list') s.items.forEach((_, k) => ev.push(['pop', st + 0.6 + k * 0.7]));
    if (s.kind === 'calc') { s.rows.forEach((_, k) => ev.push(['tick', st + 0.9 + k * 0.6])); if (s.result) ev.push(['stamp', st + 0.9 + s.rows.length * 0.6 + 0.3]); }
    if (s.kind === 'stat' && i > 0) { for (let k = 0; k < 6; k++) ev.push(['tick', st + 0.3 + k * 0.17]); ev.push(['ding', st + 1.3]); }
    if (s.kind === 'bars') { s.rows.forEach((_, k) => ev.push(['rise', st + 0.6 + k * 0.5])); }
    if (s.kind === 'text' && s.bubble) ev.push(['pop', st + 1.0]);
    if (s.kind === 'vote') { ev.push(['pop', st + 0.4]); ev.push(['pop', st + 0.7]); }
    ev.push = push0;
    st += d;
  });
  return ev.filter(e => e[1] < st - 0.2);
}
// ---------- 口白（2026-11-12）：每幕 vo 欄位 → voiceover.py 產音檔 → 幕長自動拉到「口白＋0.6 秒」 ----------
// 規定：不擷取、不克隆任何真人聲音（含學習對象帳號）；只用合成預設聲或罐子本人錄音。
function prepareVO(post) {
  if (!post.slides.some(s => s.vo)) return null;
  const { execFileSync } = require('child_process');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'canzai_vo_'));
  const pj = path.join(tmp, 'post.json'); fs.writeFileSync(pj, JSON.stringify(post));
  const cache = path.join(__dirname, '..', '口白', String(post.id));
  const res = JSON.parse(execFileSync('python3', [path.join(__dirname, 'voiceover.py'), pj, cache], { encoding: 'utf8' }));
  if (res.missing.length) {
    console.error(`✗ ${post.id} 缺口白音檔（${res.missing.length} 段），請先產生後放到：`);
    res.missing.forEach(m => console.error(`  ${m.want}  ←「${m.text}」`));
    throw new Error('缺口白音檔');
  }
  const lead = 0.15;
  res.lines.forEach(l => { const s = post.slides[l.i]; s.dur = Math.max(s.dur || 0, +(l.sec + lead + 0.45).toFixed(2)); });
  let st = 0; const starts = post.slides.map(s => { const v = st; st += s.dur || 5; return v; });
  return res.lines.map(l => ({ file: l.file, at: starts[l.i] + lead }));
}

function addAudio(post, silent, out, total) {
  const { execFileSync } = require('child_process');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'canzai_sfx_'));
  fs.writeFileSync(path.join(tmp, '_sfx.json'), JSON.stringify({ dur: total, events: sfxEvents(post) }));
  execFileSync('python3', [path.join(__dirname, 'sfx_synth.py'), tmp]);
  const idx = post.bgm != null ? post.bgm : [...String(post.id)].reduce((a, c) => a + c.charCodeAt(0), 0) % BGM.length;
  const bgm = path.join(__dirname, '..', '音樂', 'artlist', BGM[idx]);
  const T = total.toFixed(2), fo = Math.max(0, total - 1.2).toFixed(2);
  const hasBgm = fs.existsSync(bgm) && post.bgm !== false;
  const vo = post._vo || [];
  const args = ['-loglevel', 'error', '-y', '-i', silent, '-i', path.join(tmp, '_sfx.wav')];
  if (hasBgm) args.push('-i', bgm);
  vo.forEach(v => args.push('-i', v.file));
  const v0 = hasBgm ? 3 : 2;
  // 有口白：背景音樂壓低到 0.10、音效 0.55，口白放最前面
  const sfxVol = vo.length ? 0.55 : 1, bgmVol = vo.length ? 0.10 : 0.32;
  let fc = `[1:a]volume=${sfxVol}[s];`;
  const mix = ['[s]'];
  if (hasBgm) { fc += `[2:a]atrim=0:${T},asetpts=N/SR/TB,afade=t=in:d=0.3,afade=t=out:st=${fo}:d=1.2,volume=${bgmVol}[b];`; mix.push('[b]'); }
  vo.forEach((v, k) => { const ms = Math.round(v.at * 1000); fc += `[${v0 + k}:a]aresample=44100,aformat=channel_layouts=stereo,adelay=${ms}|${ms},volume=1.6[v${k}];`; mix.push(`[v${k}]`); });
  fc += mix.length > 1 ? `${mix.join('')}amix=inputs=${mix.length}:normalize=0:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11[a]` : `[s]loudnorm=I=-16:TP=-1.5:LRA=11[a]`;
  args.push('-filter_complex', fc, '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '44100', '-t', T, '-movflags', '+faststart', out);
  execFileSync('ffmpeg', args);
  post._bgm = (hasBgm ? BGM[idx].replace('.mp3', '') : '只有音效') + (vo.length ? '＋口白' : '');
}

async function renderReel(post, dir) {
  const W = 1080, H = 1920;
  post._vo = prepareVO(post);
  const n = post.slides.length;
  const scenes = post.slides.map((s, i) => `<div class="scene" data-dur="${s.dur || 5}" style="position:absolute;inset:0">${slideHTML(s, i, n, post, H)}</div>`).join('');
  const html = R.wrap(`${scenes}<div class="prog" style="top:236px;right:230px"><i style="width:0"></i></div><script>${ANIM_JS}</script>`, W, H, BASE_CSS);
  const total = post.slides.reduce((a, s) => a + (s.dur || 5), 0);
  const silent = path.join(os.tmpdir(), `canzai_${post.id}_silent.mp4`);
  await R.mp4(html, W, H, total, silent);
  addAudio(post, silent, path.join(dir, 'reel.mp4'), total);
  // 封面（9:16，IG 格狀會裁成 4:5 中段，主要字在中間）
  const cov = post.cover || post.slides[0];
  await R.png(R.wrap(slideHTML({ ...cov, kind: 'cover' }, 0, 1, post, H), W, H, BASE_CSS), W, H, path.join(dir, 'cover.png'));
  require('child_process').execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-i', path.join(dir, 'cover.png'), '-q:v', '2', path.join(dir, 'reel_cover.jpg')]);
  return total;
}

function postMD(post, info) {
  const lines = [`# ${post.id}｜${post.title}`, '',
    `- **預定發文**：${post.date}`, `- **格式**：${post.type === 'reel' ? `圖文動畫 Reel（9:16，約 ${info.total} 秒，reel.mp4＋reel_cover.jpg；聲音已混進影片：${post._bgm || '只有音效'}＋程式合成音效，自動發文不用再配樂）` : `輪播圖卡 ${post.slides.length} 張（1080×1350）`}`,
    `- **欄目**：${post.pillar}`, `- **為什麼這週發**：${post.why}`, '',
    '## 腳本／每張內容', ''];
  post.slides.forEach((s, i) => {
    const strip = t => String(t || '').replace(/<kw>/g, `「${CONFIG.comment_keywords[0]}」`).replace(/\*/g, '').replace(/\n/g, ' ');
    let d = `${i + 1}. 【${s.kind}${s.dur ? ` ${s.dur}秒` : ''}】${strip(s.label ? s.label + '｜' : '')}${strip(s.title)}`;
    if (s.sub) d += ` — ${strip(s.sub)}`;
    if (s.body) d += ` — ${strip(s.body)}`;
    if (s.num != null) d += ` — 大數字 ${s.num}${strip(s.unit)}`;
    if (s.rows) d += ' — ' + s.rows.map(r => `${strip(r[0])} ${strip(r[2] ?? r[1])}`).join('；') + (s.result ? `；${strip(s.result[0])} ${strip(s.result[1])}` : '');
    if (s.items) d += ' — ' + s.items.map(strip).join('／');
    if (s.options) d += ' — A：' + strip(s.options[0]) + '／B：' + strip(s.options[1]);
    if (s.bubble) d += `（罐仔：${strip(s.bubble)}）`;
    if (s.vo) d += `\n   🎙 口白：${s.vo}`;
    lines.push(d);
  });
  lines.push('', '## IG 文案（直接複製）', '', '```', post.caption.trim(), '', post.hashtags.join(' '), '```', '',
    `**封面替代文字（Alt text）**：${post.alt}`, '');
  if (post.music && post.type !== 'reel') lines.push(`**配樂建議**：${post.music}`, '');
  if (post.prereq?.length) lines.push('## 發文前提（罐子或社群部確認）', '', ...post.prereq.map(f => `- [ ] ${f}`), '');
  lines.push('## 發文前查證', '', ...(typeof post.factcheck === 'string' ? [post.factcheck] : post.factcheck?.length ? post.factcheck.map(f => /^- \[[ x]\]/.test(f) ? f : `- [ ] ${f}`) : ['- 本篇沒有引用特定銀行數字，範例數字已在圖上標示「示意」。']), '');
  return lines.join('\n');
}

(async () => {
  const [specFile, outRaw, only] = process.argv.slice(2); const outDir = path.resolve(outRaw);
  const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
  fs.mkdirSync(outDir, { recursive: true });
  const summary = [`# ${spec.week}｜貼文總覽`, '', `> 由內容部自動產生於 ${new Date().toISOString().slice(0, 10)}。罐子只要看這頁和「封面一覽.png」，沒問題回覆「核准」即可。`, '',
    '| # | 預定發文 | 格式 | 標題 | 檔案 |', '|---|---|---|---|---|'];
  const covers = [];
  for (const post of spec.posts) {
    const folder = `${post.id}_${post.slug}`;
    const dir = path.join(outDir, folder);
    if (!only || only === post.id) {
      fs.rmSync(dir, { recursive: true, force: true });
      fs.mkdirSync(dir, { recursive: true });
      const info = {};
      if (post.type === 'reel') info.total = await renderReel(post, dir); else await renderCarousel(post, dir);
      fs.writeFileSync(path.join(dir, '貼文.md'), postMD(post, info));
      console.log('✓', folder);
    }
    covers.push(path.join(dir, post.type === 'reel' ? 'cover.png' : '01.png'));
    summary.push(`| ${post.id} | ${post.date} | ${post.type === 'reel' ? '🎬 Reel' : `🖼️ 輪播 ${post.slides.length} 張`} | ${post.title} | [${folder}/貼文.md](${folder}/貼文.md) |`);
  }
  fs.writeFileSync(path.join(outDir, '總覽.md'), summary.join('\n') + '\n');
  await R.close();
  // 封面一覽（給罐子一眼核准）
  const { execFileSync } = require('child_process');
  execFileSync('montage', [...covers, '-resize', '360x480', '-gravity', 'center', '-extent', '360x480', '-background', P.band, '-tile', '5x', '-geometry', '+12+12', path.join(outDir, '封面一覽.png')]);
  console.log('done');
})();
