import os,sys,json,logging,queue,threading,traceback,tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from tkinter.font import Font
from core import Store,analyze,import_csv,export_report,summary_rows,nums
from sources import update,Cancelled
TITLE='今彩539・順牌50期拖牌前三名分析系統'
BASE=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent

def writable(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryFile(dir=root):pass
    for name in ('data','exports','logs'):
        p=root/name;p.mkdir(exist_ok=True)
        with tempfile.TemporaryFile(dir=p):pass
    return root

def location(root):
    config=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Lottery539Follower'/'location.json'
    target=BASE
    try:
        if config.exists():target=Path(json.loads(config.read_text(encoding='utf-8'))['path'])
    except Exception:pass
    while True:
        try:return writable(target)
        except OSError as e:
            messagebox.showwarning('資料位置無法寫入',f'{target}\n原因：{e}\n請選擇可寫入資料夾。',parent=root)
            chosen=filedialog.askdirectory(title='選擇資料儲存位置',parent=root)
            if not chosen:raise SystemExit(1)
            target=Path(chosen)
            try:
                writable(target);config.parent.mkdir(parents=True,exist_ok=True);config.write_text(json.dumps({'path':str(target)},ensure_ascii=False),encoding='utf-8')
            except OSError as e:messagebox.showwarning('設定無法儲存',str(e),parent=root)

class App:
    def __init__(self,root,store):
        self.root=root;self.store=store;self.result=None;self.thread=None;self.events=queue.Queue();self.cancel=threading.Event();self.closing=False
        root.title(TITLE);root.geometry('1300x830');root.minsize(740,560);root.configure(bg='#eef8ff')
        style=ttk.Style(root);style.theme_use('clam');style.configure('.',font=('Microsoft JhengHei',12));style.configure('Treeview',rowheight=38,font=('Microsoft JhengHei',12));style.configure('Treeview.Heading',font=('Microsoft JhengHei',12,'bold'));style.configure('TButton',padding=10);style.configure('TFrame',background='#eef8ff');style.configure('TLabel',background='#eef8ff')
        root.option_add('*Font',('Microsoft JhengHei',12))
        shell=ttk.Frame(root);shell.pack(fill='both',expand=True)
        canvas=tk.Canvas(shell,bg='#eef8ff',highlightthickness=0);scroll=ttk.Scrollbar(shell,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        outer=ttk.Frame(canvas,padding=15);item=canvas.create_window((0,0),window=outer,anchor='nw')
        outer.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        ttk.Label(outer,text=TITLE,font=('Microsoft JhengHei',22,'bold')).pack(anchor='w')
        self.info=tk.StringVar();self.label=ttk.Label(outer,textvariable=self.info,justify='left',wraplength=1200);self.label.pack(fill='x',pady=10)
        bar=ttk.Frame(outer);bar.pack(fill='x');self.buttons=[]
        actions=[('一鍵更新獎號',self.sync),('一鍵分析',self.analysis),('查看歷史獎號',self.history),('查看拖牌明細',self.details),('匯入CSV',self.csv),('匯出分析結果',self.export),('開啟日誌資料夾',self.logs)]
        for i,(text,fn) in enumerate(actions):
            b=ttk.Button(bar,text=text,command=fn);b.grid(row=i//4,column=i%4,sticky='ew',padx=3,pady=3);self.buttons.append(b)
        for col in range(4):bar.columnconfigure(col,weight=1)
        self.status=tk.StringVar(value='就緒。請更新獎號或匯入CSV。');ttk.Label(outer,textvariable=self.status,wraplength=1200).pack(fill='x',pady=8)
        self.status_label=outer.winfo_children()[-1]
        self.progress=ttk.Progressbar(outer,mode='indeterminate');self.progress.pack(fill='x')
        self.tree=self.table(outer,['順牌位置','起拖碼','有效起拖次數','第1名號碼／次數／比例','第2名號碼／次數／比例','第3名號碼／次數／比例'],height=5)
        self.merged=tk.StringVar(value='合併去重：尚未分析');self.merged_label=ttk.Label(outer,textvariable=self.merged,wraplength=1200,justify='left',font=('Microsoft JhengHei',14,'bold'));self.merged_label.pack(fill='x',pady=12)
        ttk.Label(outer,text='比例為「歷史拖出比例」，不是下期中獎機率。同次數排序不代表預測能力差異。\n跨年相鄰性未證實時採保守排除，報告會明示異常。',wraplength=1200).pack(fill='x')
        root.bind('<Configure>',self.resize);root.protocol('WM_DELETE_WINDOW',self.close);self.refresh();root.after(100,self.poll)
        root.report_callback_exception=self.callback_error
    def resize(self,event):
        if event.widget==self.root:
            width=max(500,event.width-45)
            self.label.configure(wraplength=width)
            self.status_label.configure(wraplength=width)
            self.merged_label.configure(wraplength=width)
    def callback_error(self,typ,value,tb):
        logging.error('介面錯誤',exc_info=(typ,value,tb));messagebox.showerror('操作失敗',f'{value}\n詳細原因請查看logs。')
    def table(self,parent,heads,rows=(),height=12):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,pady=8);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        t=ttk.Treeview(frame,columns=list(range(len(heads))),show='headings',height=height)
        for i,h in enumerate(heads): t.heading(i,text=h);t.column(i,width=310 if '比例' in h else 170,minwidth=110,stretch=False)
        ys=ttk.Scrollbar(frame,orient='vertical',command=t.yview);xs=ttk.Scrollbar(frame,orient='horizontal',command=t.xview);t.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
        t.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew')
        rows=list(rows);font=Font(family='Microsoft JhengHei',size=12)
        for i,h in enumerate(heads):
            content=max([font.measure(str(row[i])) for row in rows]+[font.measure(h)])+36
            t.column(i,width=max(140,content))
        for r in rows:t.insert('',tk.END,values=r)
        return t
    def refresh(self):
        rows=self.store.rows()
        if not rows:self.info.set('尚無歷史資料。未提供模擬獎號。');return
        r=rows[-1];statuses={x['status'] for x in rows[-50:]};sources=sorted(set(x['source'] for x in rows[-50:]))
        self.info.set(f'本機當期：{r["period"]}　日期：{r["date"]}　順牌：{nums(r["numbers"])}\n共{len(rows)}期；資料截止：{r["date"]}（是否最新須依更新結果核對）\n來源：'+ '；'.join(sources)+'\n驗證狀態：'+'；'.join(sorted(statuses))+'\n最後更新紀錄：'+self.store.last_update()+f'\n資料位置：{self.store.root}')
    def run(self,task,fn):
        if self.thread and self.thread.is_alive():return
        self.cancel.clear()
        for b in self.buttons:b.state(['disabled'])
        self.status.set(task);self.progress.start()
        def worker():
            try:self.events.put(('done',task,fn()))
            except Cancelled:self.events.put(('error',task,'已取消'))
            except Exception as e:
                logging.exception(task);self.events.put(('error',task,str(e)))
        self.thread=threading.Thread(target=worker,name='539-worker',daemon=False);self.thread.start()
    def poll(self):
        try:
            while True:
                kind,task,value=self.events.get_nowait()
                if kind=='progress':self.status.set(value);continue
                self.progress.stop()
                for b in self.buttons:b.state(['!disabled'])
                if self.closing:continue
                if kind=='error':
                    self.status.set(task+'失敗：'+value);messagebox.showerror(task+'失敗',value+'\n原有資料保留；請查看日誌。')
                else:
                    self.refresh()
                    if task=='分析':self.show_result(value)
                    else:
                        self.result=None;self.tree.delete(*self.tree.get_children());self.merged.set('資料已更新，請重新分析。')
                        self.status.set(task+'完成');messagebox.showinfo(task,value)
        except queue.Empty:pass
        if self.closing:
            if not self.thread or not self.thread.is_alive():self.root.destroy();return
            self.status.set('正在安全結束背景工作，請稍候…')
        self.root.after(100,self.poll)
    def sync(self):
        self.run('更新獎號',lambda:update(self.store,self.cancel,lambda text:self.events.put(('progress','',text))))
    def analysis(self):
        def work():
            r=analyze(self.store.rows());self.store.snapshot(r);return r
        self.run('分析',work)
    def show_result(self,r):
        self.result=r;self.tree.delete(*self.tree.get_children())
        for row in summary_rows(r):self.tree.insert('',tk.END,values=row)
        common='、'.join(f'{int(n):02d}（{c}組）' for n,c in r['merged'].items())
        self.merged.set('合併去重：'+nums(r['merged'])+'\n共同候選：'+common)
        self.status.set(f'完成：{r["created"]}；範圍{r["start"]["period"]}（{r["start"]["date"]}）～{r["end"]["period"]}（{r["end"]["date"]}）；'+('完整50期／49組相鄰期' if r['complete'] else '異常：50筆資料非完整50期分析；已排除不確定配對'))
        if r['warnings']:messagebox.showwarning('配對異常','\n'.join(r['warnings']))
    def window(self,title):
        w=tk.Toplevel(self.root);w.title(title);w.geometry('1100x650');return w
    def history(self):
        rows=self.store.rows();w=self.window('歷史獎號（截止本機資料）')
        self.table(w,['期別','日期','順牌獎號','來源','驗證狀態'],[[r['period'],r['date'],nums(r['numbers']),r['source'],r['status']] for r in reversed(rows)])
    def details(self):
        if not self.result:messagebox.showinfo('尚未分析','請先執行一鍵分析。');return
        w=self.window('完整拖牌明細與01～39計數');book=ttk.Notebook(w);book.pack(fill='both',expand=True)
        for s in self.result['results']:
            f=ttk.Frame(book);book.add(f,text=f'{s["seed"]:02d}（{s["N"]}次）')
            rows=[]
            for d in s['details']:
                a,b=d['from'],d['to'];rows.append([a['period'],a['date'],nums(a['numbers']),b['period'],b['date'],nums(b['numbers'])])
            self.table(f,['起拖期別','起拖日期','起拖獎號','下一期期別','下一期日期','下一期獎號'],rows,height=8)
            self.table(f,['候選號碼','拖出次數','歷史拖出比例','最近拖出日期'],[[f'{n:02d}',s['counts'][n],f'{100*s["counts"][n]/s["N"]:.2f}%' if s['N'] else '無有效樣本',s['last'][n]] for n in range(1,40)],height=4)
    def csv(self):
        p=filedialog.askopenfilename(filetypes=[('CSV','*.csv')])
        if p:
            def work():
                rows=import_csv(p);conflicts=self.store.merge(rows);return f'已匯入{len(rows)}筆；衝突{len(conflicts)}期。請重新分析。'
            self.run('匯入CSV',work)
    def export(self):
        if not self.result:messagebox.showinfo('尚未分析','請先執行分析。');return
        paths=export_report(self.result,self.store.root/'exports');messagebox.showinfo('匯出完成','\n'.join(map(str,paths)))
    def logs(self):
        path=str(self.store.root/'logs')
        if sys.platform=='win32':os.startfile(path)
        else:messagebox.showinfo('日誌位置',path)
    def close(self):
        self.closing=True;self.cancel.set()
        for b in self.buttons:b.state(['disabled'])
        if not self.thread or not self.thread.is_alive():self.root.destroy()

def main():
    root=tk.Tk();root.withdraw()
    try:
        data_root=location(root)
        logging.basicConfig(filename=data_root/'logs'/'app.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')
        logging.info('啟動；資料位置%s',data_root)
        app=App(root,Store(data_root));root.deiconify();root.mainloop();logging.info('正常結束，背景工作與SQLite連線已釋放')
    except Exception as e:
        logging.exception('啟動失敗')
        messagebox.showerror('啟動失敗',str(e)+'\n請查看logs/app.log或START.cmd顯示的錯誤。');raise
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--self-test':
        from frozen_selftest import run
        raise SystemExit(run())
    main()
