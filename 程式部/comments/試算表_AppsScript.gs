/**
 * 罐仔私訊試算表：選卡自動回覆（dm_bot.py）只透過這支程式讀寫試算表。
 * 安裝：試算表 → 擴充功能 → Apps Script → 整段貼上取代 → 存檔 → 上方選 setup → 執行 → 允許權限。
 *       再按「部署 → 新增部署作業 → 類型：網頁應用程式 → 執行身分：我 → 存取權：所有人 → 部署」，複製網址。
 * 隱私（法務部 11/5 審查）：帳號名稱和訊息只存在這份試算表；每天凌晨自動刪掉 90 天前的列。
 */
const TABS = ['選卡待回覆', '私訊待處理'];
const HEAD = ['收到時間', '帳號', '對方編號', '訊息（卡號身分證已遮蔽）', '有遮蔽', '罐仔回覆草稿', '核准', '送出狀態'];
const KEEP_DAYS = 90;

function setup() {
  const ss = SpreadsheetApp.getActive();
  TABS.forEach(name => {
    const sh = ss.getSheetByName(name) || ss.insertSheet(name);
    sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]).setFontWeight('bold');
    sh.setFrozenRows(1);
    sh.getRange('A:A').setNumberFormat('@');
    sh.getRange('C:C').setNumberFormat('@');
    sh.getRange('G2:G1000').insertCheckboxes();
  });
  const props = PropertiesService.getScriptProperties();
  let key = props.getProperty('BOT_KEY');
  if (!key) {
    key = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
    props.setProperty('BOT_KEY', key);
  }
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('purge90').timeBased().everyDays(1).atHour(3).create();
  const msg = '把下面這串貼到 GitHub repo 的 secret，名稱 CANZAI_BOT_KEY：\n\n' + key;
  Logger.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch (e) {}
}

function doPost(e) {
  let b;
  try { b = JSON.parse(e.postData.contents); } catch (err) { return out({ok: false, error: 'bad json'}); }
  if (!b.key || b.key !== PropertiesService.getScriptProperties().getProperty('BOT_KEY')) return out({ok: false, error: 'key'});
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const ss = SpreadsheetApp.getActive();
    if (b.action === 'append') {
      if (TABS.indexOf(b.tab) < 0) return out({ok: false, error: 'tab'});
      const sh = ss.getSheetByName(b.tab);
      const row = (b.row || []).slice(0, 5).map(String);
      sh.appendRow(row.concat(['', false, '']));
      sh.getRange(sh.getLastRow(), 7).insertCheckboxes();
      return out({ok: true});
    }
    if (b.action === 'outbox') {
      const items = []; let late = 0; const now = Date.now();
      TABS.forEach(name => {
        const v = ss.getSheetByName(name).getDataRange().getValues();
        for (let i = 1; i < v.length; i++) {
          const [time, , igsid, , , draft, ok, sent] = v[i];
          if (sent) continue;
          if (ok === true && String(draft).trim()) items.push({tab: name, row: i + 1, igsid: String(igsid), text: String(draft), time: String(time)});
          else if (name === '選卡待回覆' && now - parse(time) > 20 * 3600e3 && now - parse(time) < 24 * 3600e3) late++;
        }
      });
      return out({ok: true, items: items, late: late});
    }
    if (b.action === 'mark') {
      if (TABS.indexOf(b.tab) < 0 || !(b.row > 1)) return out({ok: false, error: 'row'});
      ss.getSheetByName(b.tab).getRange(b.row, 8).setValue(String(b.value));
      return out({ok: true});
    }
    return out({ok: false, error: 'action'});
  } finally { lock.releaseLock(); }
}

function purge90() {
  const cut = Date.now() - KEEP_DAYS * 86400e3;
  TABS.forEach(name => {
    const sh = SpreadsheetApp.getActive().getSheetByName(name);
    const v = sh.getDataRange().getValues();
    for (let i = v.length - 1; i >= 1; i--) if (parse(v[i][0]) < cut) sh.deleteRow(i + 1);
  });
}

function parse(t) {
  const s = String(t).replace(/([+-]\d\d)(\d\d)$/, '$1:$2');
  const ms = Date.parse(s);
  return isNaN(ms) ? Date.now() : ms;  // 認不得的時間先留著，不誤刪
}

function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
