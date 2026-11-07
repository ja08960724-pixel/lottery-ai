import os,sys,json,logging,queue,threading,tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from core import Store,analyze_many,import_csv,export_many,summary_rows,nums,WINDOWS
from sources import update,Cancelled
VERSION='1.0.0-HK-MULTI'
TITLE='六合彩・100／150／200／300期拖牌分析 V1.0'
BASE=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent

def writable(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    for name in ('data','exports','logs'):
        p=root/name;p.mkdir(exist_ok=True)
        with tempfile.TemporaryFile(dir=p):pass
    return root

def location(root):
    config=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'HongKongMarkSixFollower'/'location.json'
    target=BASE
    try:
        if config.exists():target=Path(json.loads(config.read_text(encoding='utf-8'))['path'])
    except Exception:pass
    while True:
        try:return writable(target)
        except OSError as e:
            messagebox.showwarning('資料位置無法寫入',f'{target}\n{e}\n請選擇可寫入資料夾。',parent=root)
            chosen=filedialog.askdirectory(title='選擇資料位置',parent=root)
            if not chosen:raise SystemExit(1)
            target=Path(chosen)
            try:
                writable(target);config.parent.mkdir(parents=True,exist_ok=True);config.write_text(json.dumps({'path':str(target)},ensure_ascii=False),encoding='utf-8')
            except OSError as e:messagebox.showwarning('設定無法儲存',str(e),parent=root)

class App:
    def __init__(self,root,store):
        self.root=root;self.store=store;self.result=None;self.thread=None;self.events=queue.Queue();self.cancel=threading.Event();self.closing=False
        root.title(TITLE);root.geometry('1320x900');root.minsize(850,640)
        style=ttk.Style(root);style.theme_use('clam');style.configure('.',font=('Microsoft JhengHei',12));style.configure('Treeview',rowheight=37,font=('Microsoft JhengHei',12));style.configure('Treeview.Heading',font=('Microsoft JhengHei',12,'bold'));style.configure('TButton',padding=8);style.configure('TFrame',background='#eff8ff');style.configure('TLabel',background='#eff8ff');style.configure('TNotebook.Tab',padding=(18,10),font=('Microsoft JhengHei',13,'bold'))
        shell=ttk.Frame(root);shell.pack(fill='both',expand=True)
        canvas=tk.Canvas(shell,bg='#eff8ff',highlightthickness=0);ys=ttk.Scrollbar(shell,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=ys.set);ys.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        outer=ttk.Frame(canvas,padding=12);item=canvas.create_window((0,0),window=outer,anchor='nw')
        outer.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        self.wrap_labels=[]
        ttk.Label(outer,text=TITLE,font=('Microsoft JhengHei',20,'bold')).pack(anchor='w')
        self.info=tk.StringVar();self.info_label=ttk.Label(outer,textvariable=self.info,wraplength=1250,justify='left');self.info_label.pack(fill='x',pady=7)
        bar=ttk.Frame(outer);bar.pack(fill='x');self.buttons=[]
        actions=[('更新獎號＋四組分析',self.sync),('一鍵四組分析',self.analysis),('查看歷史獎號',self.history),('目前頁籤拖牌明細',self.details),('匯入CSV',self.csv),('匯出全部四組',self.export),('開啟日誌資料夾',self.logs)]
        for i,(text,fn) in enumerate(actions):
            b=ttk.Button(bar,text=text,command=fn);b.grid(row=i//4,column=i%4,sticky='ew',padx=3,pady=3);self.buttons.append(b)
        for c in range(4):bar.columnconfigure(c,weight=1)
        self.status=tk.StringVar(value='就緒；四組期數將各自獨立計算。');self.status_label=ttk.Label(outer,textvariable=self.status,wraplength=1250);self.status_label.pack(fill='x',pady=6)
        self.progress=ttk.Progressbar(outer,mode='indeterminate');self.progress.pack(fill='x')
        self.book=ttk.Notebook(outer);self.book.pack(fill='both',expand=True,pady=8)
        self.tables={};self.ranges={};self.merged={}
        heads=['順牌位置','起拖碼','有效起拖次數','第1名／次數／歷史拖出比例','第2名／次數／歷史拖出比例','第3名／次數／歷史拖出比例']
        for size in WINDOWS:
            page=ttk.Frame(self.book,padding=10);self.book.add(page,text=f'{size}期分析')
            self.ranges[size]=tk.StringVar(value='尚未分析');ttk.Label(page,textvariable=self.ranges[size],wraplength=1200,justify='left').pack(fill='x')
            self.wrap_labels.append(page.winfo_children()[-1])
            self.tables[size]=self.table(page,heads,height=6)
            self.merged[size]=tk.StringVar(value='合併去重：尚未分析');ttk.Label(page,textvariable=self.merged[size],wraplength=1200,justify='left',font=('Microsoft JhengHei',14,'bold')).pack(fill='x',pady=6)
            self.wrap_labels.append(page.winfo_children()[-1])
        self.agreement=tk.StringVar(value='跨期數共同候選：尚未分析');self.agreement_label=ttk.Label(outer,textvariable=self.agreement,wraplength=1250,justify='left');self.agreement_label.pack(fill='x',pady=6)
        ttk.Label(outer,text='歷史拖出比例不是下期中獎機率；同次數排序不代表預測優勢。四個窗口高度重疊，並非四份獨立證據；只統計六個正選，特別號不參與拖牌。\n開獎日期採香港時間；缺期／衝突配對不跨接。資料不足的窗口不產生假結果。',wraplength=1250).pack(fill='x')
        root.report_callback_exception=self.callback_error;root.protocol('WM_DELETE_WINDOW',self.close);root.bind('<Configure>',self.resize)
        self.refresh()
        old=self.store.latest_snapshot();rows=self.store.rows()
        if old and old.get('kind')=='marksix_multi_v1' and rows and old['current']==rows[-1]:self.show_result(old)
        root.after(100,self.poll)
    def resize(self,event):
        if event.widget==self.root:
            for label in (self.info_label,self.status_label,self.agreement_label,*self.wrap_labels):label.configure(wraplength=max(700,event.width-65))
    def callback_error(self,typ,value,tb):
        logging.error('介面錯誤',exc_info=(typ,value,tb));messagebox.showerror('操作失敗',f'{value}\n請查看logs/app.log')
    def table(self,parent,heads,rows=(),height=12):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,pady=8);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        t=ttk.Treeview(frame,columns=list(range(len(heads))),show='headings',height=height)
        for i,h in enumerate(heads):t.heading(i,text=h);t.column(i,width=310 if ('比例' in h or '獎號' in h) else 160,minwidth=100,stretch=False)
        ys=ttk.Scrollbar(frame,orient='vertical',command=t.yview);xs=ttk.Scrollbar(frame,orient='horizontal',command=t.xview);t.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
        t.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew')
        for row in rows:t.insert('',tk.END,values=row)
        return t
    def refresh(self):
        rows=self.store.rows()
        if not rows:self.info.set('尚無歷史資料，請更新或匯入CSV。');return
        r=rows[-1];statuses=sorted({x['status'] for x in rows[-300:]});sources=sorted({part.split('：')[0] for row in rows[-300:] for part in row['source'].split(' | ')})
        self.info.set(f'本機當期：{r["period"]}｜香港日期：{r["date"]}｜正選順牌：{nums(r["numbers"])}｜特別號：{r["special"]:02d}｜歷史共{len(rows)}期\n來源：'+ '、'.join(sources)+'｜驗證：'+ '；'.join(statuses)+'\n最後更新：'+self.store.last_update()+f'\n資料位置：{self.store.root}')
    def run(self,task,fn):
        if self.closing or (self.thread and self.thread.is_alive()):return
        self.cancel.clear()
        for b in self.buttons:b.state(['disabled'])
        self.status.set(task+'中…');self.progress.start()
        def worker():
            try:self.events.put(('done',task,fn()))
            except Cancelled:self.events.put(('error',task,'已取消'))
            except Exception as e:logging.exception(task);self.events.put(('error',task,str(e)))
        self.thread=threading.Thread(target=worker,name='MarkSix-worker',daemon=False);self.thread.start()
    def poll(self):
        try:
            while True:
                kind,task,value=self.events.get_nowait()
                if kind=='progress':self.status.set(value);continue
                self.progress.stop()
                for b in self.buttons:b.state(['!disabled'])
                if self.closing:continue
                if kind=='error':self.status.set(task+'失敗：'+value);messagebox.showerror(task+'失敗',value+'\n原有有效資料保留。');continue
                self.refresh()
                if isinstance(value,dict):
                    self.show_result(value)
                    if value.get('update_message'):
                        note=value['update_message'];self.status.set(note+'\n四組分析完成：'+value['created'])
                        if '更新失敗，原有有效資料保留' in note:messagebox.showwarning('更新失敗，使用本機截止資料',note)
                else:self.status.set(str(value));messagebox.showinfo(task,str(value))
        except queue.Empty:pass
        if self.closing:
            if not self.thread or not self.thread.is_alive():self.root.destroy();return
            self.status.set('正在安全結束背景工作，請稍候…')
        self.root.after(100,self.poll)
    def calculate(self):
        r=analyze_many(self.store.rows());self.store.snapshot(r);return r
    def analysis(self):self.run('四組分析',self.calculate)
    def sync(self):
        def work():
            note=update(self.store,self.cancel,lambda text:self.events.put(('progress','',text)))
            if self.cancel.is_set():raise Cancelled()
            if not self.store.rows():raise RuntimeError(note)
            r=analyze_many(self.store.rows());r['update_message']=note;self.store.snapshot(r);return r
        self.run('更新與四組分析',work)
    def show_result(self,r):
        self.result=r
        for w in r['windows']:
            size=w['size'];table=self.tables[size];table.delete(*table.get_children());a=w['analysis']
            if not a:
                self.ranges[size].set(f'資料不足：目前{w["available"]}期，至少需要{size}期。');self.merged[size].set('資料不足，不輸出此窗口候選。');continue
            for row in summary_rows(a):table.insert('',tk.END,values=row)
            self.ranges[size].set(f'範圍：{a["start"]["period"]}（{a["start"]["date"]}）～{a["end"]["period"]}（{a["end"]["date"]}）\n'+(f'完整{size}期，{size-1}組相鄰配對' if a['complete'] else f'{size}期紀錄；有效相鄰配對{a["valid_pairs"]}/{size-1}；排除{len(a["warnings"])}組跨年未證實／缺期／衝突配對')+f'｜分析時間：{r["created"]}')
            self.merged[size].set('合併去重：'+nums(a['merged'])+'\n共同候選：'+'、'.join(f'{int(n):02d}（{c}組起拖碼）' for n,c in a['merged'].items()))
        self.agreement.set('跨期數共同候選（納入幾個窗口）：'+'、'.join(f'{int(n):02d}（{c}/4）' for n,c in r['agreement'].items()))
        self.status.set('四組分析完成並自動保存：'+r['created'])
    def window(self,title):
        w=tk.Toplevel(self.root);w.title(title);w.geometry('1200x720');return w
    def history(self):
        w=self.window('香港歷史獎號');self.table(w,['期別','香港日期','正選順牌','特別號','資料來源','驗證狀態'],[[r['period'],r['date'],nums(r['numbers']),f'{r["special"]:02d}',r['source'],r['status']] for r in reversed(self.store.rows())])
    def details(self):
        if not self.result:messagebox.showinfo('尚未分析','請先執行四組分析。');return
        entry=self.result['windows'][self.book.index(self.book.select())];r=entry['analysis']
        if not r:messagebox.showinfo('資料不足',f'尚無完整{entry["size"]}期資料。');return
        w=self.window(f'{entry["size"]}期拖牌明細');book=ttk.Notebook(w);book.pack(fill='both',expand=True)
        for s in r['results']:
            f=ttk.Frame(book);book.add(f,text=f'{s["seed"]:02d}（{s["N"]}次）')
            rows=[]
            for d in s['details']:
                a,b=d['from'],d['to'];rows.append([a['period'],a['date'],nums(a['numbers']),b['period'],b['date'],nums(b['numbers'])])
            self.table(f,['起拖期別','香港日期','起拖獎號','下一期期別','香港日期','下一期獎號'],rows,height=8)
            self.table(f,['號碼','拖出次數','歷史拖出比例','最近拖出日期'],[[f'{n:02d}',s['counts'].get(n,s['counts'].get(str(n),0)),f'{100*s["counts"].get(n,s["counts"].get(str(n),0))/s["N"]:.2f}%' if s['N'] else '無有效樣本',s['last'].get(n,s['last'].get(str(n),''))] for n in range(1,50)],height=5)
    def csv(self):
        path=filedialog.askopenfilename(filetypes=[('CSV','*.csv')])
        if path:
            def work():
                rows=import_csv(path);self.store.merge(rows);return self.calculate()
            self.run('匯入CSV與分析',work)
    def export(self):
        if not self.result:messagebox.showinfo('尚未分析','請先執行四組分析。');return
        r=self.result
        self.run('匯出全部四組',lambda:'已匯出四組摘要、49碼正選計數、明細與來源：\n'+'\n'.join(map(str,export_many(r,self.store.root/'exports'))))
    def logs(self):os.startfile(str(self.store.root/'logs')) if sys.platform=='win32' else messagebox.showinfo('日誌位置',str(self.store.root/'logs'))
    def close(self):
        self.closing=True;self.cancel.set()
        for b in self.buttons:b.state(['disabled'])
        if not self.thread or not self.thread.is_alive():self.root.destroy()

def main():
    root=tk.Tk();root.withdraw()
    try:
        data_root=location(root);logging.basicConfig(filename=data_root/'logs'/'app.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')
        store=Store(data_root);seed=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'seed_history.json'
        if seed.exists():
            known={r['period'] for r in store.rows()}
            missing=[r for r in json.loads(seed.read_text(encoding='utf-8')) if r['period'] not in known]
            if missing:store.merge(missing)
        app=App(root,store);root.deiconify();root.mainloop();logging.info('安全結束背景工作與資料庫連線')
    except Exception as e:logging.exception('啟動失敗');messagebox.showerror('啟動失敗',str(e)+'\n請查看logs/app.log');raise
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--self-test':
        from frozen_selftest import run
        raise SystemExit(run())
    if len(sys.argv)>1 and sys.argv[1]=='--live-test':
        from frozen_selftest import run_live
        raise SystemExit(run_live())
    main()
