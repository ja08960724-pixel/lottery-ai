"""California Fantasy 5 adapters. Dates are America/Los_Angeles calendar dates."""
import json,re,urllib.request,urllib.error,urllib.parse,socket
from html.parser import HTMLParser
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from core import draw,validate,now
OFFICIAL='https://www.calottery.com/en/draw-games/fantasy-5'
BIGA_ENTRY='https://biga.com.tw/99567/'
# This POST endpoint and F selector are used by the Biga query page itself.
BIGA_HISTORY='https://biga.com.tw/99567/ajax_history_F.php'
class Cancelled(Exception): pass

def get(url,cancel,archive=None,form=None):
    for attempt in range(2):
        if cancel.is_set():raise Cancelled('已取消')
        try:
            body=urllib.parse.urlencode(form).encode() if form else None
            req=urllib.request.Request(url,data=body,headers={'User-Agent':'Mozilla/5.0 Fantasy5Statistics/1.0','Accept':'text/html','Referer':BIGA_ENTRY if form else OFFICIAL})
            with urllib.request.urlopen(req,timeout=8) as f:data=f.read(4_000_001)
            if len(data)>4_000_000:raise ValueError('來源回應超過4MB限制')
            if cancel.is_set():raise Cancelled('已取消')
            text=data.decode('utf-8-sig')
            if archive is not None:
                archive.mkdir(parents=True,exist_ok=True)
                import hashlib
                key=hashlib.sha256((url+str(form)).encode()).hexdigest()[:12]
                (archive/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+key+'.txt')).write_text(text,encoding='utf-8')
            return text
        except urllib.error.HTTPError as e:
            if e.code in (403,404):raise RuntimeError(f'HTTP {e.code}：{url}') from e
            err=f'HTTP {e.code}：{url}'
        except (TimeoutError,socket.timeout):err=f'連線逾時：{url}'
        except urllib.error.URLError as e:err=f'網路連線失敗：{e.reason}；{url}'
        if attempt==0 and cancel.wait(.5):raise Cancelled('已取消')
    raise RuntimeError(err)

class TableParser(HTMLParser):
    # Biga omits most closing </tr> tags; flush on either the next <tr> or </table>.
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def flush(self):
        if self.cell is not None and self.row is not None:self.row.append(self.cell.strip())
        if self.row:self.rows.append(self.row)
        self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.flush();self.row=[]
        elif tag=='td' and self.row is not None:
            if self.cell is not None:self.row.append(self.cell.strip())
            self.cell=''
    def handle_data(self,data):
        if self.cell is not None:self.cell+=data
    def handle_endtag(self,tag):
        if tag=='td' and self.cell is not None:
            self.row.append(self.cell.strip());self.cell=None
        elif tag in ('tr','table'):self.flush()
    def close(self):super().close();self.flush()

def parse_biga(text):
    if '加州夢幻5' not in text and '加州天天' not in text:raise ValueError('Biga頁面不是加州Fantasy 5資料')
    parser=TableParser();parser.feed(text);parser.close();rows=[]
    for c in parser.rows:
        if len(c)>1 and re.fullmatch(r'\d{4}/\d{2}/\d{2}',c[1]):
            if len(c)!=17:raise ValueError('Biga加州資料格式變更：表列應有17欄')
            r=draw(c[3],c[1],c[7:12],'Biga：'+BIGA_HISTORY)
            if r['numbers']!=sorted(map(int,c[12:17])):raise ValueError(f'Biga落球與順牌不一致：{c[3]}')
            rows.append(r)
    if not rows:raise ValueError('Biga加州來源缺資料或格式變更')
    return validate(rows)

class VisibleText(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,s):
        if not self.hidden:self.parts.append(s)

def parse_official(text):
    p=VisibleText();p.feed(text);t=' '.join(' '.join(p.parts).split())
    if 'Fantasy 5' not in t:raise ValueError('加州官方頁面不是Fantasy 5')
    m=re.search(r'Winning Numbers:\s*(?:[A-Z]{3}/)?([A-Z]{3})\s+(\d{1,2}),\s*(\d{4})\s*Draw\s*#\s*(\d+)\s*(.*?)This Could Be',t,re.I)
    if not m:raise ValueError('加州官方資料格式變更或需動態載入；未能讀取最新期')
    month=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'].index(m[1].upper())+1
    numbers=re.findall(r'\b\d{1,2}\b',m[5])
    if len(numbers)!=5:raise ValueError('加州官方頁面無法確認恰好5個獎號')
    return [draw(m[4],f'{int(m[3]):04d}-{month:02d}-{int(m[2]):02d}',numbers,'加州彩券官方：'+OFFICIAL)]

def update(store,cancel,progress):
    messages=[];success=0
    current=datetime.now(ZoneInfo('America/Los_Angeles'));end=current.date();start=end-timedelta(days=420)
    progress('取得Biga加州Fantasy 5最近420日獎號')
    try:
        form=dict(lotto='F',datefrom=start.strftime('%Y/%m/%d'),dateto=end.strftime('%Y/%m/%d'),disporder='D')
        b=parse_biga(get(BIGA_HISTORY,cancel,store.root/'data'/'sources',form=form))
        conflicts=store.merge(b);success+=1;messages.append(f'Biga取得{len(b)}筆加州獎號；衝突{len(conflicts)}期')
    except Cancelled:raise
    except Exception as e:messages.append(f'Biga更新失敗：{e}')
    progress('核對加州彩券官方最新一期（官方可能回傳403）')
    try:
        official=parse_official(get(OFFICIAL,cancel,store.root/'data'/'sources'))
        conflicts=store.merge(official);success+=1;messages.append(f'加州官方最新期取得{len(official)}筆；衝突{len(conflicts)}期')
    except Cancelled:raise
    except Exception as e:messages.append(f'加州官方未能核對：{e}；其餘期保留單一來源標記')
    rows=store.rows()
    if not success:messages.append('更新失敗，原有有效資料保留')
    if len(rows)<300:messages.append(f'資料不足300期：目前{len(rows)}期；各窗口將分別標示是否足夠')
    if rows:
        messages.append(f'本機截止（美國加州日期）：{rows[-1]["date"]}，期別{rows[-1]["period"]}；不保證來源已發布最新一期')
        latest=datetime.fromisoformat(rows[-1]['date']).date()
        if (current.date()-latest).days>=2:messages.append('資料可能過期，請核對加州官方最新開獎；僅依截止日期分析')
    message='\n'.join(messages);store.log(message);return message
