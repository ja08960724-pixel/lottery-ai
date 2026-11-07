"""Hong Kong Mark Six adapters. Dates are Asia/Hong_Kong calendar dates."""
import json,re,urllib.request,urllib.error,urllib.parse,socket
from html.parser import HTMLParser
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from core import draw,validate,now
OFFICIAL='https://bet.hkjc.com/ch/marksix/results'
BIGA_ENTRY='https://biga.com.tw/99567/'
# This POST endpoint and C selector are used by the Biga query page itself.
BIGA_HISTORY='https://biga.com.tw/99567/ajax_history_C.php'
class Cancelled(Exception): pass

def get(url,cancel,archive=None,form=None):
    for attempt in range(2):
        if cancel.is_set():raise Cancelled('已取消')
        try:
            body=urllib.parse.urlencode(form).encode() if form else None
            req=urllib.request.Request(url,data=body,headers={'User-Agent':'Mozilla/5.0 MarkSixStatistics/1.0','Accept':'text/html','Referer':BIGA_ENTRY if form else OFFICIAL})
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
    if '六合彩' not in text:raise ValueError('Biga頁面不是香港六合彩')
    parser=TableParser();parser.feed(text);parser.close();rows=[]
    for c in parser.rows:
        if len(c)>1 and re.fullmatch(r'\d{4}/\d{2}/\d{2}',c[1]):
            if len(c)!=20:raise ValueError('Biga六合彩表列格式變更：應有20欄（6正選＋1特別號）')
            row=draw(c[3],c[1],c[7:13],'Biga：'+BIGA_HISTORY,special=c[19])
            if row['numbers']!=sorted(map(int,c[13:19])):raise ValueError('Biga六合彩落球與順牌不一致')
            rows.append(row)
    if not rows:raise ValueError('Biga六合彩來源缺資料或格式變更')
    return validate(rows)

def update(store,cancel,progress):
    messages=[];success=0
    current=datetime.now(ZoneInfo('Asia/Hong_Kong'));end=current.date();start=end-timedelta(days=1500)
    progress('取得Biga六合彩最近1500日真實獎號')
    try:
        form=dict(lotto='C',datefrom=start.strftime('%Y/%m/%d'),dateto=end.strftime('%Y/%m/%d'),disporder='D')
        rows=parse_biga(get(BIGA_HISTORY,cancel,store.root/'data'/'sources',form=form))
        conflicts=store.merge(rows);success=1;messages.append(f'Biga取得{len(rows)}期六合彩；衝突{len(conflicts)}期')
    except Cancelled:raise
    except Exception as e:messages.append(f'Biga更新失敗：{e}')
    messages.append('香港賽馬會結果頁為動態網頁，測試GraphQL回傳WHITELIST_ERROR；本版僅使用Biga並標示單一來源')
    rows=store.rows()
    if not success:messages.append('更新失敗，原有有效資料保留')
    if len(rows)<300:messages.append(f'資料不足300期：目前{len(rows)}期，窗口分別標示不足')
    if rows:
        messages.append(f'本機截止（香港日期）：{rows[-1]["date"]}；期別{rows[-1]["period"]}；不保證來源已發布最新一期')
        if (end-datetime.fromisoformat(rows[-1]['date']).date()).days>=7:messages.append('資料可能過期，請核對香港官方最新獎號')
    note='\n'.join(messages);store.log(note);return note
