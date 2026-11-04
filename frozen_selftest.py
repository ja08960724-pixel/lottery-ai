"""Developer smoke tests; synthetic data exists only inside TemporaryDirectory."""
import json, os, platform, sys, tempfile, time
from pathlib import Path
from datetime import date, timedelta
from collections import Counter
import tkinter as tk
from core import Store, draw, analyze, export_report

def run():
    from app import App
    report = {'platform': platform.platform(), 'frozen': bool(getattr(sys, 'frozen', False)),
              'executable': sys.executable, 'checks': [], 'limitations': [
              'Windows cloud runner is Windows Server, not a physical Windows 10/11 machine.',
              'DPI scaling and manual mouse interactions have not been verified.']}
    assert report['frozen'], 'Must run the packaged EXE'
    with tempfile.TemporaryDirectory(prefix='今彩539 測試 ') as td:
        st = Store(td)
        rows = [draw(114000001+i, (date(2025,1,1)+timedelta(days=i)).isoformat(),
                     [(i*3+j*7)%39+1 for j in range(5)], 'TEST ONLY') for i in range(60)]
        st.merge(rows); st.merge(rows)
        assert len(st.rows()) == 60
        r = analyze(st.rows()); st.snapshot(r)
        for s in r['results']:
            c = Counter(n for d in s['details'] for n in d['to']['numbers'])
            assert all(s['counts'][n] == c[n] for n in range(1,40))
        assert Store(td).latest_snapshot()['current']['period'] == r['current']['period']
        report['checks'].append('Unicode/space path SQLite persistence and independent recount passed')
        cp, hp = export_report(r, Path(td)/'exports')
        assert cp.read_bytes().startswith(b'\xef\xbb\xbf')
        assert '歷史拖出比例' in hp.read_text(encoding='utf-8')
        report['checks'].append('CSV BOM and HTML exports passed')
        root = tk.Tk()
        ui = App(root, st); ui.show_result(r); root.update()
        assert len(ui.tree.get_children()) == 5
        ui.history(); ui.details(); root.update()
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel): w.destroy()
        ui.analysis()
        deadline = time.monotonic()+30
        while ui.thread.is_alive() or not ui.events.empty():
            root.update()
            if time.monotonic()>deadline: raise TimeoutError('Background analysis timeout')
            time.sleep(.02)
        root.update(); assert ui.result is not None
        ui.close()
        assert not ui.thread.is_alive()
        # A second Tk instance exercises GUI shutdown/reopen without external Python.
        root2 = tk.Tk(); ui2 = App(root2, Store(td)); root2.update(); ui2.close()
        report['checks'].append('Frozen Tcl/Tk GUI/history/details/background analysis/close/reopen passed')
    assert not Path(td).exists()
    report['checks'].append('Test directory removed; no lingering SQLite/file handles')
    target = Path(sys.argv[2])
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0
