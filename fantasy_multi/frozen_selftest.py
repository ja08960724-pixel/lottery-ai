import json,platform,sys,tempfile,time
from pathlib import Path
from datetime import date,timedelta
from collections import Counter
import tkinter as tk
from core import Store,draw,analyze_many,export_many,WINDOWS

def run():
    from app import App
    assert getattr(sys,'frozen',False),'Packaged EXE required'
    seed=json.loads((Path(sys._MEIPASS)/'seed_history.json').read_text(encoding='utf-8'))
    r=analyze_many(seed)
    assert all(w['analysis'] and w['analysis']['complete'] for w in r['windows'])
    report={'platform':platform.platform(),'frozen':True,'seed_rows':len(seed),'latest':seed[-1],'checks':[],'limitations':['Windows Server cloud test; Windows 10/11 physical machines and DPI scaling not manually verified.']}
    for w in r['windows']:
        for s in w['analysis']['results']:
            c=Counter(n for d in s['details'] for n in d['to']['numbers'])
            assert all(c[n]==s['counts'][n] for n in range(1,40))
    report['checks'].append('Four real-data windows independently recounted')
    with tempfile.TemporaryDirectory(prefix='加州 四期數 ') as td:
        st=Store(td);st.merge(seed);st.snapshot(r);saved=Store(td).latest_snapshot()
        paths=export_many(saved,Path(td)/'exports');assert paths[0].read_bytes().startswith(b'\xef\xbb\xbf')
        root=tk.Tk();ui=App(root,st);root.update();assert len(ui.book.tabs())==4
        for i,size in enumerate(WINDOWS):
            ui.book.select(i);root.update();assert len(ui.tables[size].get_children())==5
            ui.details();root.update()
            for w in root.winfo_children():
                if isinstance(w,tk.Toplevel):w.destroy()
        ui.history();root.update()
        for w in root.winfo_children():
            if isinstance(w,tk.Toplevel):w.destroy()
        ui.analysis();deadline=time.monotonic()+30
        while ui.thread.is_alive() or not ui.events.empty():
            root.update();time.sleep(.02)
            if time.monotonic()>deadline:raise TimeoutError('Background analysis timeout')
        root.update();ui.close();assert not ui.thread.is_alive()
        root2=tk.Tk();ui2=App(root2,Store(td));root2.update();assert ui2.result['kind']=='multi_window_v2';ui2.close()
        # Incomplete windows display no rows instead of pretending to be complete.
    assert not Path(td).exists()
    report['checks'] += ['Four tabs and all drag detail windows opened','Chinese/space path SQLite snapshots restore and CSV/HTML/JSON export','Background analysis, shutdown/reopen, file handles released']
    Path(sys.argv[2]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return 0

def run_live():
    from threading import Event
    from sources import update
    report={'platform':platform.platform(),'frozen':True,'download_succeeded':False}
    try:
        with tempfile.TemporaryDirectory(prefix='Fantasy5 Live ') as td:
            st=Store(td);report['messages']=update(st,Event(),lambda message:None);rows=st.rows();report['downloaded_rows']=len(rows)
            if len(rows)>=300:
                r=analyze_many(rows);report['download_succeeded']=True;report['latest']=rows[-1]
                report['windows']=[{'size':w['size'],'complete':w['analysis']['complete']} for w in r['windows']]
    except Exception as e:report['error']=str(e)
    Path(sys.argv[2]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return 0
