"""Verified source adapters. Official internal endpoint has no stability guarantee."""
import json, re, urllib.request, urllib.error, socket
from html.parser import HTMLParser
from datetime import datetime
from zoneinfo import ZoneInfo
from core import draw,validate,now
OFFICIAL='https://api.taiwanlottery.com/TLCAPIWeB/Lottery/Daily539Result'
BIGA_ENTRY='https://biga.com.tw/99567/'
BIGA_HISTORY='https://2019.biga.com.tw/ARCHIVE/DRAWDATA/PAGINATION/ZP/tw539resultlist?page=1'
class Cancelled(Exception): pass

def get(url,cancel,archive=None):
    for attempt in range(2):
        if cancel.is_set():raise Cancelled('已取消')
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 Lottery539Statistics/1.0','Accept':'application/json,text/html'})
            with urllib.request.urlopen(req,timeout=8) as f:
                data=f.read(4_000_001)
            if len(data)>4_000_000:raise ValueError('來源回應超過4MB限制')
            if cancel.is_set():raise Cancelled('已取消')
            text=data.decode('utf-8-sig')
            if archive is not None:
                archive.mkdir(parents=True,exist_ok=True)
                import hashlib
                key=hashlib.sha256(url.encode()).hexdigest()[:12]
                (archive/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+key+'.txt')).write_text(text,encoding='utf-8')
            return text
        except urllib.error.HTTPError as e:
            if e.code in (403,404):raise RuntimeError(f'HTTP {e.code}：{url}') from e
            err=f'HTTP {e.code}：{url}'
        except (TimeoutError,socket.timeout) as e: err=f'連線逾時：{url}'
        except urllib.error.URLError as e:err=f'網路連線失敗：{e.reason}；{url}'
        if attempt==0 and cancel.wait(.5):raise Cancelled('已取消')
    raise RuntimeError(err)

def parse_official(text):
    j=json.loads(text)
    if j.get('rtCode')!=0:raise ValueError('官方回傳錯誤：'+str(j.get('rtMsg')))
    content=j.get('content')
    if not isinstance(content,dict) or not isinstance(content.get('daily539Res'),list):raise ValueError('官方資料格式變更：缺少content.daily539Res')
    rows=[]
    for r in content['daily539Res']:
        rows.append(draw(r['period'],r['lotteryDate'],r['drawNumberSize'],'台灣彩券官方：'+OFFICIAL))
    return validate(rows)

class TableParser(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag=='td' and self.row is not None:self.cell=''
    def handle_data(self,data):
        if self.cell is not None:self.cell+=data
    def handle_endtag(self,tag):
        if tag=='td' and self.cell is not None:
            self.row.append(self.cell.strip());self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None

def parse_biga(text):
    if '今彩539' not in text and '今彩開獎號碼' not in text:raise ValueError('Biga頁面不是今彩539歷史資料')
    parser=TableParser();parser.feed(text);rows=[]
    for c in parser.rows:
        if c and re.fullmatch(r'\d{4}/\d{2}/\d{2}',c[0]):
            if len(c)!=16:raise ValueError('Biga資料格式變更：歷史表列應有16欄')
            r=draw(c[2],c[0],c[6:11],'Biga：'+BIGA_HISTORY)
            if r['numbers']!=sorted(map(int,c[11:16])):raise ValueError(f'Biga落球與順牌不一致：{c[2]}')
            rows.append(r)
    if not rows:raise ValueError('Biga來源缺資料或資料格式變更')
    return validate(rows)

def update(store,cancel,progress):
    messages=[];success=0
    current=datetime.now(ZoneInfo('Asia/Taipei'))
    official_rows=[]
    for offset in range(4):
        if cancel.is_set():raise Cancelled('已取消')
        k=current.year*12+current.month-1-offset;y,m=divmod(k,12)
        month=f'{y:04d}-{m+1:02d}'
        progress(f'取得官方 {month}（{offset+1}/4）')
        try:
            text=get(OFFICIAL+f'?month={month}&pageNum=1&pageSize=50',cancel,store.root/'data'/'sources')
            official_rows.extend(parse_official(text))
        except Cancelled:raise
        except Exception as e:messages.append(str(e))
    if official_rows:
        try:
            store.merge(official_rows);success+=1;messages.append(f'官方取得{len(official_rows)}筆')
        except Exception as e:messages.append(f'官方資料驗證失敗，未合併：{e}')
    progress('取得Biga備援歷史資料並交叉核對')
    try:
        b=parse_biga(get(BIGA_HISTORY,cancel,store.root/'data'/'sources'))
        conflicts=store.merge(b);success+=1;messages.append(f'Biga取得{len(b)}筆；衝突{len(conflicts)}期')
    except Cancelled:raise
    except Exception as e:messages.append(f'Biga更新失敗：{e}')
    rows=store.rows()
    if not success: messages.append('更新失敗，原有有效資料保留')
    if rows:
        messages.append(f'本機截止：{rows[-1]["date"]}，期別{rows[-1]["period"]}；不保證來源已發布最新一期')
        latest_date=datetime.fromisoformat(rows[-1]['date']).date()
        if (current.date()-latest_date).days>=2:messages.append('資料可能過期，請核對官方最新開獎；僅能依截止日期分析')
    message='\n'.join(messages);store.log(message)
    return message
