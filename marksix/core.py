"""Exact, deterministic MarkSix follower statistics. No network or GUI dependencies."""
from __future__ import annotations
import csv, json, sqlite3, html, re
from pathlib import Path
from datetime import date, datetime
from collections import Counter
from contextlib import contextmanager
from zoneinfo import ZoneInfo

def now():
    return datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')

def draw(period, day, numbers, source, status='單一來源，尚未交叉驗證',special=None):
    d=date.fromisoformat(str(day)[:10].replace('/','-'))
    m=re.fullmatch(r'(\d{2}|\d{4})/(\d{1,3})',str(period).strip())
    if not m:raise ValueError(f'六合彩期別須為26/117或2026/117：{period}')
    year=int(m[1]);year=year+2000 if year<100 else year;seq=int(m[2])
    if year!=d.year or not 1<=seq<=999:raise ValueError('六合彩期別年度或序號與日期不符')
    p=f'{year:04d}/{seq:03d}'
    if d>datetime.now(ZoneInfo('Asia/Hong_Kong')).date():raise ValueError('香港開獎日期在未來')
    n=sorted(int(x) for x in numbers)
    if len(n)!=6 or len(set(n))!=6 or not all(1<=x<=49 for x in n):raise ValueError('六合彩正選須為01～49的6個不重複號碼')
    if special is None:raise ValueError('缺少特別號，不接受不完整的六合彩資料')
    special=int(special)
    if not 1<=special<=49 or special in n:raise ValueError('特別號須為01～49且不與正選重複')
    return dict(period=p,date=d.isoformat(),numbers=n,special=special,source=source,status=status,draw_timezone='Asia/Hong_Kong')

def validate(rows):
    out={}; days={}
    for r in rows:
        r=draw(r['period'],r['date'],r['numbers'],r['source'],r.get('status','單一來源，尚未交叉驗證'),special=r.get('special'))
        p=r['period']
        if p in out: raise ValueError(f'重複期別：{p}')
        if r['date'] in days: raise ValueError(f'同日多個期別：{r["date"]}')
        out[p]=r;days[r['date']]=p
    result=sorted(out.values(),key=lambda r:r['period'])
    if any(a['date']>=b['date'] for a,b in zip(result,result[1:])): raise ValueError('日期與期別順序衝突')
    return result

def adjacent(a,b):
    # Dates need not be consecutive: Mark Six is not a daily draw.
    # Without a certified year-end draw ID, conservatively exclude the year reset.
    return (a['period'][:4]==b['period'][:4]
            and int(b['period'][5:])==int(a['period'][5:])+1
            and a['date']<b['date'] and '衝突' not in a['status']+b['status'])

def analyze(rows,window=50):
    if window not in (50,100,150,200,300): raise ValueError('不支援的統計期數')
    rows=validate(rows)
    if len(rows)<window: raise ValueError(f'資料不足：僅{len(rows)}期，至少需要{window}期')
    w=rows[-window:]; gaps=[]; pairs=[]
    for a,b in zip(w,w[1:]):
        if adjacent(a,b): pairs.append((a,b))
        else: gaps.append(f'{a["period"]} → {b["period"]}：缺期、跨年邊界未證實或來源衝突，排除配對')
    result=[]; merged=Counter()
    for pos,seed in enumerate(w[-1]['numbers'],1):
        counts={n:0 for n in range(1,50)}; last={n:'' for n in range(1,50)}; details=[]
        for a,b in pairs:
            if seed in a['numbers']:
                details.append({'from':a,'to':b})
                for n in b['numbers']: counts[n]+=1;last[n]=b['date']
        N=len(details)
        if any(c>N for c in counts.values()) or sum(counts.values())!=6*N: raise ArithmeticError('統計恆等式檢查失敗')
        ranked=sorted((n for n in counts if counts[n]),key=lambda n:(-counts[n],-date.fromisoformat(last[n]).toordinal(),n))
        top=[]
        for n in ranked[:3]:
            top.append(dict(number=n,count=counts[n],ratio=100*counts[n]/N,last=last[n],tied=sum(c==counts[n] for c in counts.values())>1))
            merged[n]+=1
        result.append(dict(position=pos,seed=seed,N=N,counts=counts,last=last,top=top,details=details))
    return dict(created=now(),current=w[-1],start=w[0],end=w[-1],size=window,valid_pairs=len(pairs),complete=not gaps,
                warnings=gaps,results=result,merged=dict(sorted(merged.items())),window=w,
                note='歷史拖出比例不是下期中獎機率。同次數排序不代表預測能力差異。資料截止日期不代表已確認最新開獎。只統計六個正選，特別號不參與起拖或拖出。開獎日期為Asia/Hong_Kong；報告時間為Asia/Taipei。')

def import_csv(path):
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        required=['期別','日期']+[f'號碼{i}' for i in range(1,7)]+['特別號']
        if not reader.fieldnames or not all(k in reader.fieldnames for k in required): raise ValueError('CSV欄位必須包含：'+ '、'.join(required))
        rows=[]
        for line,r in enumerate(reader,2):
            try: rows.append(draw(r['期別'],r['日期'],[r[f'號碼{i}'] for i in range(1,7)],'CSV匯入：'+Path(path).name,special=r['特別號']))
            except Exception as e: raise ValueError(f'CSV第{line}行：{e}') from e
    if not rows: raise ValueError('CSV沒有資料')
    return validate(rows)

class Store:
    def __init__(self,root): self.root=Path(root); self.path=self.root/'data'/'history.sqlite3';self.init()
    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path,timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()
    def init(self):
        for n in ('data','exports','logs'): (self.root/n).mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS draws(period TEXT PRIMARY KEY,day TEXT UNIQUE,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations(period TEXT,source TEXT,payload TEXT,seen TEXT,PRIMARY KEY(period,source));
CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY,stamp TEXT,detail TEXT);
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,stamp TEXT,period TEXT,payload TEXT);''')
            game=c.execute("SELECT value FROM metadata WHERE key='game'").fetchone()
            if game and game[0]!='HK_MARKSIX': raise ValueError('資料庫彩種不符，請選擇六合彩獨立資料位置')
            if not game and c.execute('SELECT COUNT(*) FROM draws').fetchone()[0]:
                raise ValueError('舊資料庫未標示六合彩彩種，請另選空白資料位置，避免混入其他彩種')
            c.execute("INSERT OR IGNORE INTO metadata VALUES('game','HK_MARKSIX')")
    def rows(self):
        with self.db() as c: return [json.loads(r[0]) for r in c.execute('SELECT payload FROM draws ORDER BY period')]
    def log(self,message):
        with self.db() as c:c.execute('INSERT INTO updates(stamp,detail) VALUES(?,?)',(now(),message))
    def merge(self,rows):
        rows=validate(rows); conflicts=[]
        with self.db() as c:
            existing={r['period']:r for r in self.rows()}
            combined=existing.copy()
            for incoming in rows:
                p=incoming['period'];old=existing.get(p)
                c.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?)',(p,incoming['source'],json.dumps(incoming,ensure_ascii=False),now()))
                r=incoming.copy()
                if old:
                    if old['date']!=r['date'] or old['numbers']!=r['numbers'] or old.get('special')!=r.get('special'):
                        conflicts.append(p);r=old.copy();r['status']='來源衝突，已保留原值並排除涉及配對'
                    else:
                        sources=set(old['source'].split(' | '))|set(r['source'].split(' | '));r['source']=' | '.join(sorted(sources))
                        if '衝突' in old['status']: r['status']=old['status']
                        elif '香港賽馬會官方' in r['source'] and 'Biga' in r['source']:r['status']='官方與Biga交叉驗證一致'
                        else:r['status']=old['status']
                combined[p]=r
            # Reject entire transaction for date collisions/order anomalies.
            validate(list(combined.values()))
            for r in combined.values(): c.execute('INSERT OR REPLACE INTO draws VALUES(?,?,?)',(r['period'],r['date'],json.dumps(r,ensure_ascii=False)))
            c.execute('INSERT INTO updates(stamp,detail) VALUES(?,?)',(now(),f'合併{len(rows)}筆；來源衝突：'+('、'.join(conflicts) or '無')))
        return conflicts
    def snapshot(self,r):
        with self.db() as c:c.execute('INSERT INTO snapshots(stamp,period,payload) VALUES(?,?,?)',(r['created'],r['current']['period'],json.dumps(r,ensure_ascii=False)))
    def latest_snapshot(self):
        with self.db() as c:
            row=c.execute('SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None
    def last_update(self):
        with self.db() as c:r=c.execute('SELECT stamp,detail FROM updates ORDER BY id DESC LIMIT 1').fetchone()
        return '；'.join(r) if r else '尚未更新'

def nums(xs): return '、'.join(f'{int(n):02d}' for n in xs)
def summary_rows(r):
    result=[]
    for s in r['results']:
        t=[f'{v["number"]:02d}／{v["count"]}次／{v["ratio"]:.2f}%'+('（同次數）' if v['tied'] else '') for v in s['top']]
        result.append([f'第{s["position"]}碼',f'{s["seed"]:02d}',s['N']]+t+['無有效樣本' if not s['N'] else '—']*(3-len(t)))
    return result

def export_report(r,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    stem=f'MarkSix_{r["size"]}期_'+r['current']['period'].replace('/','-')+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    headers=['順牌位置','起拖碼','有效起拖次數','第1名號碼／次數／歷史拖出比例','第2名號碼／次數／歷史拖出比例','第3名號碼／次數／歷史拖出比例']
    meta=[['產生時間',r['created']],['當期',r['current']['period'],r['current']['date'],nums(r['current']['numbers'])],['分析範圍',r['start']['period'],r['start']['date'],r['end']['period'],r['end']['date']],['完整性',f'完整{r["size"]}期' if r['complete'] else f'{r["size"]}筆有異常，非完整{r["size"]}期分析'],['合併去重',nums(r['merged'])],['提醒',r['note']]]
    details=[]
    for s in r['results']:
        for d in s['details']:
            a,b=d['from'],d['to'];details.append([f'{s["seed"]:02d}',a['period'],a['date'],nums(a['numbers']),b['period'],b['date'],nums(b['numbers'])])
    dh=['起拖碼','起拖期別','起拖日期','起拖獎號','下一期期別','下一期日期','下一期獎號']
    provenance=[['期別','日期','獎號','來源','驗證狀態']]+[[x['period'],x['date'],nums(x['numbers']),f'{x["special"]:02d}',x['source'],x['status']] for x in r['window']]
    common=[['候選號碼','列入前三名的起拖碼數']]+[[f'{int(n):02d}',c] for n,c in r['merged'].items()]
    fullcounts=[['起拖碼','候選號碼','拖出次數','歷史拖出比例','最近拖出日期']]
    for s in r['results']:
        for n in range(1,50):
            c=s['counts'].get(n,s['counts'].get(str(n),0));last=s['last'].get(n,s['last'].get(str(n),''))
            fullcounts.append([f'{s["seed"]:02d}',f'{n:02d}',c,f'{100*c/s["N"]:.2f}%' if s['N'] else '無有效樣本',last])
    tables=[meta,[headers]+summary_rows(r),common,[['完整拖牌明細']],[dh]+details,fullcounts,provenance,[['異常']]+[[x] for x in r['warnings']]]
    cp=folder/(stem+'.csv');hp=folder/(stem+'.html')
    with cp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        for table in tables:w.writerows(table);w.writerow([])
    def table(rows):
        return '<table>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    hp.write_text('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>香港六合彩拖牌分析</title><style>body{font:18px "Microsoft JhengHei",sans-serif;margin:32px;color:#17334a;background:#f7fcff}table{border-collapse:collapse;margin:20px 0;width:100%}td{border:1px solid #b5cddd;padding:10px}tr:first-child{background:#dcefff}h1{color:#006f92}</style><h1>香港六合彩・多期數拖牌前三名分析</h1>'+''.join(table(t) for t in tables)+'</html>',encoding='utf-8')
    return cp,hp


WINDOWS=(100,150,200,300)
def analyze_many(rows):
    rows=validate(rows)
    if not rows: raise ValueError('尚無歷史獎號，請先更新或匯入CSV')
    windows=[]
    for size in WINDOWS:
        if len(rows)<size:
            windows.append(dict(size=size,status='insufficient',available=len(rows),analysis=None))
        else:
            r=analyze(rows,size)
            windows.append(dict(size=size,status='ok',available=len(rows),analysis=r))
    counts=Counter(n for w in windows if w['analysis'] for n in w['analysis']['merged'])
    return dict(kind='marksix_multi_v1',created=now(),current=rows[-1],windows=windows,
                agreement={str(n):counts[n] for n in sorted(counts)},
                note='四種期數高度重疊；共同候選是跨窗口統計，不代表獨立證據或下期中獎機率。')

def export_many(result,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    slug=result['current']['period'].replace('/','-')
    base=folder/f'MarkSix_四期數_{slug}_{stamp}'
    cp=base.with_suffix('.csv');hp=base.with_suffix('.html');jp=base.with_suffix('.json')
    rows=[['六合彩多期數拖牌分析'],['產生時間',result['created']],['當期（香港日期）',result['current']['period'],result['current']['date'],nums(result['current']['numbers']),f'特別號：{result["current"]["special"]:02d}'],['提醒',result['note']]]
    for w in result['windows']:
        rows.append([]);rows.append([f'{w["size"]}期分析'])
        if not w['analysis']:
            rows.append(['資料不足',f'目前{w["available"]}期，至少需要{w["size"]}期']);continue
        r=w['analysis'];rows += [['分析範圍',r['start']['period'],r['start']['date'],r['end']['period'],r['end']['date']],['完整性','完整' if r['complete'] else '跨年未證實／缺期／衝突配對已排除'],['順牌位置','起拖碼','有效起拖次數','第1名／次數／歷史拖出比例','第2名／次數／歷史拖出比例','第3名／次數／歷史拖出比例']]+summary_rows(r)+[['合併去重',nums(r['merged'])],['共同候選（同一窗口的起拖碼組數）']]+[[f'{int(n):02d}',c] for n,c in r['merged'].items()]
        rows += [['完整拖牌明細','起拖期別','日期','獎號','下一期期別','日期','獎號']]
        for s in r['results']:
            for d in s['details']:
                a,b=d['from'],d['to'];rows.append([f'{s["seed"]:02d}',a['period'],a['date'],nums(a['numbers']),b['period'],b['date'],nums(b['numbers'])])
        rows += [['完整49碼正選計數','候選號碼','拖出次數','歷史拖出比例','最近拖出日期']]
        for s in r['results']:
            for n in range(1,50):
                count=s['counts'].get(n,s['counts'].get(str(n),0));last=s['last'].get(n,s['last'].get(str(n),''))
                rows.append([f'{s["seed"]:02d}',f'{n:02d}',count,f'{100*count/s["N"]:.2f}%' if s['N'] else '無有效樣本',last])
        rows += [['來源與驗證','香港日期','正選獎號','特別號','來源','驗證狀態']]+[[x['period'],x['date'],nums(x['numbers']),f'{x["special"]:02d}',x['source'],x['status']] for x in r['window']]
        rows += [['異常',warning] for warning in r['warnings']]
    rows += [[],['跨期數共同候選（納入幾個窗口）']]+[[f'{int(n):02d}',c] for n,c in result['agreement'].items()]
    with cp.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerows(rows)
    body=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' if row else '<tr><td colspan="7">　</td></tr>' for row in rows)
    hp.write_text('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>六合彩四期數拖牌報告</title><style>body{font:18px "Microsoft JhengHei",sans-serif;background:#f1f8ff;color:#17334a;margin:24px}table{border-collapse:collapse;width:100%}td{border:1px solid #bdd3e3;padding:8px;vertical-align:top}tr:has(td:only-child){background:#d8efff;font-weight:bold}</style><h1>六合彩100／150／200／300期拖牌報告</h1><table>'+body+'</table></html>',encoding='utf-8')
    jp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return cp,hp,jp
