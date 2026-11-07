import unittest,tempfile,json,sys
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import *
from test_core import fixture

class MultiWindow(unittest.TestCase):
    def test_three_windows_independent_recount_boundaries(self):
        rows=fixture(370);bundle=analyze_many(rows)
        for w in bundle['windows']:
            size=w['size'];r=w['analysis'];self.assertEqual(r['size'],size);self.assertEqual(r['start'],rows[-size]);self.assertEqual(r['current'],rows[-1]);self.assertTrue(r['complete'])
            for s in r['results']:
                c=Counter();N=0
                for i in range(len(rows)-size,len(rows)-1):
                    if s['seed'] in rows[i]['numbers']:c.update(rows[i+1]['numbers']);N+=1
                self.assertEqual(s['N'],N);self.assertEqual(s['counts'],{n:c[n] for n in range(1,40)})
                self.assertEqual(sum(c.values()),5*N)
    def test_insufficient_per_window(self):
        for count in (19,20,49,50,99,100):
            r=analyze_many(fixture(count))
            for w in r['windows']:self.assertEqual(w['analysis'] is not None,count>=w['size'])
    def test_gap_outside_20_but_inside_50_100(self):
        rows=fixture(370);rows.pop(-25);r=analyze_many(rows)
        for w in r['windows']:
            a=w['analysis'];self.assertEqual(a['complete'],w['size']==20)
            for s in a['results']:
                self.assertTrue(all(adjacent(d['from'],d['to']) for d in s['details']))
    def test_latest_not_a_seed_and_self_follow(self):
        rows=fixture(330)
        for row in rows:row['numbers']=[1,2,3,4,5]
        for w in analyze_many(rows)['windows']:
            for s in w['analysis']['results']:
                self.assertEqual(s['N'],w['size']-1);self.assertEqual(s['counts'][s['seed']],w['size']-1)
    def test_snapshot_old_and_new_and_export_reloaded(self):
        with tempfile.TemporaryDirectory(prefix='中文 多期 ') as td:
            st=Store(td);st.merge(fixture(330));st.snapshot(analyze(st.rows(),100));r=analyze_many(st.rows());st.snapshot(r)
            reopened=Store(td);saved=reopened.latest_snapshot();self.assertEqual(saved['kind'],'multi_window_20_50_100_v3')
            with reopened.db() as c:self.assertEqual(c.execute('select count(*) from snapshots').fetchone()[0],2)
            cp,hp,jp=export_many(saved,Path(td)/'exports');self.assertTrue(cp.read_bytes().startswith(b'\xef\xbb\xbf'))
            text=hp.read_text(encoding="utf-8")
            for size in WINDOWS:self.assertIn(f'{size}期分析',text)
            self.assertEqual(json.loads(jp.read_text(encoding="utf-8"))['windows'][2]['analysis']['size'],100)
    def test_overlap_agreement(self):
        r=analyze_many(fixture(330));expected=Counter(n for w in r['windows'] for n in w['analysis']['merged'])
        self.assertEqual(r['agreement'],{str(n):expected[n] for n in sorted(expected)})
    def test_unknown_window_rejected(self):
        with self.assertRaises(ValueError):analyze(fixture(330),250)
