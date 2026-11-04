"""Exact, deterministic Fantasy5 follower statistics. No network or GUI dependencies."""
from __future__ import annotations
import csv, json, sqlite3, html
from pathlib import Path
from datetime import date, datetime
from collections import Counter
from contextlib import contextmanager
from zoneinfo import ZoneInfo

def now():
    return datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')

def draw(period, day, numbers, source, status='單一來源，尚未交叉驗證'):
    p=str(period).strip()
    if not p.isdigit() or not 1<=int(p)<=999999: raise ValueError(f'加州期別須為1～999999的整數：{period}')
    p=f'{int(p):06d}'
    d=date.fromisoformat(str(day)[:10].replace('/','-'))
    if d>datetime.now(ZoneInfo('America/Los_Angeles')).date(): raise ValueError(f'加州開獎日期在未來：{d}')
    n=sorted(int(x) for x in numbers)
    if len(n)!=5 or len(set(n))!=5 or not all(1<=x<=39 for x in n):
        raise ValueError(f'{p}：須為01～39的5個不重複號碼')
    return dict(period=p,date=d.isoformat(),numbers=n,source=source,status=status,draw_timezone='America/Los_Angeles')

def validate(rows):
    out={}; days={}
    for r in rows:
        r=draw(r['period'],r['date'],r['numbers'],r['source'],r.get('status','單一來源，尚未交叉驗證'))
        p=r['period']
        if p in out: raise ValueError(f'重複期別：{p}')
        if r['date'] in days: raise ValueError(f'同日多個期別：{r["date"]}')
        out[p]=r;days[r['date']]=p
    result=sorted(out.values(),key=lambda r:r['period'])
    if any(a['date']>=b['date'] for a,b in zip(result,result[1:])): raise ValueError('日期與期別順序衝突')
    return result

def adjacent(a,b):
    return (int(b['period'])==int(a['period'])+1
            and (date.fromisoformat(b['date'])-date.fromisoformat(a['date'])).days==1
            and '衝突' not in a['status']+b['status'])

def analyze(rows):
    rows=validate(rows)
    if len(rows)<50: raise ValueError(f'資料不足：僅{len(rows)}期，至少需要50期')
    w=rows[-50:]; gaps=[]; pairs=[]
    for a,b in zip(w,w[1:]):
        if adjacent(a,b): pairs.append((a,b))
        else: gaps.append(f'{a["period"]} → {b["period"]}：缺期、日期不連續或來源衝突，排除配對')
    result=[]; merged=Counter()
    for pos,seed in enumerate(w[-1]['numbers'],1):
        counts={n:0 for n in range(1,40)}; last={n:'' for n in range(1,40)}; details=[]
        for a,b in pairs:
            if seed in a['numbers']:
                details.append({'from':a,'to':b})
                for n in b['numbers']: counts[n]+=1;last[n]=b['date']
        N=len(details)
        if any(c>N for c in counts.values()) or sum(counts.values())!=5*N: raise ArithmeticError('統計恆等式檢查失敗')
        ranked=sorted((n for n in counts if counts[n]),key=lambda n:(-counts[n],-date.fromisoformat(last[n]).toordinal(),n))
        top=[]
        for n in ranked[:3]:
            top.append(dict(number=n,count=counts[n],ratio=100*counts[n]/N,last=last[n],tied=sum(c==counts[n] for c in counts.values())>1))
            merged[n]+=1
        result.append(dict(position=pos,seed=seed,N=N,counts=counts,last=last,top=top,details=details))
    return dict(created=now(),current=w[-1],start=w[0],end=w[-1],size=50,complete=not gaps,
                warnings=gaps,results=result,merged=dict(sorted(merged.items())),window=w,
                note='歷史拖出比例不是下期中獎機率。同次數排序不代表預測能力差異。資料截止日期不代表已確認最新開獎。開獎日期為America/Los_Angeles；報告時間為Asia/Taipei。')

def import_csv(path):
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        required=['期別','日期']+[f'號碼{i}' for i in range(1,6)]
        if not reader.fieldnames or not all(k in reader.fieldnames for k in required): raise ValueError('CSV欄位必須包含：'+ '、'.join(required))
        rows=[]
        for line,r in enumerate(reader,2):
            try: rows.append(draw(r['期別'],r['日期'],[r[f'號碼{i}'] for i in range(1,6)],'CSV匯入：'+Path(path).name))
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
            if game and game[0]!='CA_FANTASY5': raise ValueError('資料庫彩種不符，請選擇加州天天樂獨立資料位置')
            if not game and c.execute('SELECT COUNT(*) FROM draws').fetchone()[0]:
                raise ValueError('舊資料庫未標示加州彩種，請另選空白資料位置，避免混入今彩539')
            c.execute("INSERT OR IGNORE INTO metadata VALUES('game','CA_FANTASY5')")
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
                    if old['date']!=r['date'] or old['numbers']!=r['numbers']:
                        conflicts.append(p);r=old.copy();r['status']='來源衝突，已保留原值並排除涉及配對'
                    else:
                        sources=set(old['source'].split(' | '))|set(r['source'].split(' | '));r['source']=' | '.join(sorted(sources))
                        if '衝突' in old['status']: r['status']=old['status']
                        elif '加州彩券官方' in r['source'] and 'Biga' in r['source']:r['status']='官方與Biga交叉驗證一致'
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
    stem='Fantasy5_'+r['current']['period']+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    headers=['順牌位置','起拖碼','有效起拖次數','第1名號碼／次數／歷史拖出比例','第2名號碼／次數／歷史拖出比例','第3名號碼／次數／歷史拖出比例']
    meta=[['產生時間',r['created']],['當期',r['current']['period'],r['current']['date'],nums(r['current']['numbers'])],['分析範圍',r['start']['period'],r['start']['date'],r['end']['period'],r['end']['date']],['完整性','完整50期' if r['complete'] else '50筆有異常，非完整50期分析'],['合併去重',nums(r['merged'])],['提醒',r['note']]]
    details=[]
    for s in r['results']:
        for d in s['details']:
            a,b=d['from'],d['to'];details.append([f'{s["seed"]:02d}',a['period'],a['date'],nums(a['numbers']),b['period'],b['date'],nums(b['numbers'])])
    dh=['起拖碼','起拖期別','起拖日期','起拖獎號','下一期期別','下一期日期','下一期獎號']
    provenance=[['期別','日期','獎號','來源','驗證狀態']]+[[x['period'],x['date'],nums(x['numbers']),x['source'],x['status']] for x in r['window']]
    common=[['候選號碼','列入前三名的起拖碼數']]+[[f'{int(n):02d}',c] for n,c in r['merged'].items()]
    fullcounts=[['起拖碼','候選號碼','拖出次數','歷史拖出比例','最近拖出日期']]
    for s in r['results']:
        for n in range(1,40):
            c=s['counts'].get(n,s['counts'].get(str(n),0));last=s['last'].get(n,s['last'].get(str(n),''))
            fullcounts.append([f'{s["seed"]:02d}',f'{n:02d}',c,f'{100*c/s["N"]:.2f}%' if s['N'] else '無有效樣本',last])
    tables=[meta,[headers]+summary_rows(r),common,[['完整拖牌明細']],[dh]+details,fullcounts,provenance,[['異常']]+[[x] for x in r['warnings']]]
    cp=folder/(stem+'.csv');hp=folder/(stem+'.html')
    with cp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        for table in tables:w.writerows(table);w.writerow([])
    def table(rows):
        return '<table>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    hp.write_text('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>加州天天樂 Fantasy 5拖牌分析</title><style>body{font:18px "Microsoft JhengHei",sans-serif;margin:32px;color:#17334a;background:#f7fcff}table{border-collapse:collapse;margin:20px 0;width:100%}td{border:1px solid #b5cddd;padding:10px}tr:first-child{background:#dcefff}h1{color:#006f92}</style><h1>加州天天樂 Fantasy 5・順牌50期拖牌前三名分析</h1>'+''.join(table(t) for t in tables)+'</html>',encoding='utf-8')
    return cp,hp
