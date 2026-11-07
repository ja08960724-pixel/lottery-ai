import unittest,tempfile,sys,json,csv
from pathlib import Path
from datetime import date,timedelta
from collections import Counter
from unittest.mock import patch
from threading import Event
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import *
from sources import parse_biga,update

def fixture(n=330):
    # Synthetic only: arbitrary draw intervals; period sequence resets annually.
    rows=[];year=None;seq=0
    for i in range(n):
        d=date(2023,1,1)+timedelta(days=i*3)
        if d.year!=year:year=d.year;seq=0
        seq+=1;ns=sorted({(i*5+j*7)%49+1 for j in range(6)});sp=next(x for x in range(1,50) if x not in ns)
        rows.append(draw(f'{year}/{seq}',d.isoformat(),ns,'TEST ONLY',special=sp))
    return rows
class MarkSix(unittest.TestCase):
    def test_period_normalization(self):
        self.assertEqual(draw('26/117','2026-11-05',[11,20,28,29,42,47],'test',special=46)['period'],'2026/117')
    def test_validation(self):
        for ns,sp in [([1,2,3,4,5],6),([1,2,3,4,5,5],6),([1,2,3,4,5,50],6),([1,2,3,4,5,6],6),([1,2,3,4,5,6],50),([1,2,3,4,5,6],None)]:
            with self.assertRaises(ValueError):draw('26/117','2026-11-05',ns,'test',special=sp)
    def test_wrong_year_or_california_period(self):
        for p in ['012053','25/117']:
            with self.assertRaises(ValueError):draw(p,'2026-11-05',[1,2,3,4,5,6],'test',special=7)
    def test_non_daily_adjacent(self):
        a=draw('26/116','2026-10-31',[1,2,3,4,5,6],'t',special=7);b=draw('26/117','2026-11-05',[1,2,3,4,5,6],'t',special=7)
        self.assertTrue(adjacent(a,b))
    def test_year_reset_excluded(self):
        a=draw('25/150','2025-12-30',[1,2,3,4,5,6],'t',special=7);b=draw('26/1','2026-01-03',[1,2,3,4,5,6],'t',special=7);self.assertFalse(adjacent(a,b))
    def test_four_windows_independent_counts(self):
        rows=fixture();r=analyze_many(rows)
        for w in r['windows']:
            a=w['analysis'];self.assertEqual(a['size'],w['size']);self.assertEqual(a['start'],rows[-w['size']]);self.assertEqual(len(a['results']),6)
            for s in a['results']:
                c=Counter();N=0
                for x,y in zip(rows[-w['size']:],rows[-w['size']+1:]):
                    if adjacent(x,y) and s['seed'] in x['numbers']:c.update(y['numbers']);N+=1
                self.assertEqual(s['N'],N);self.assertEqual(s['counts'],{n:c[n] for n in range(1,50)});self.assertEqual(sum(c.values()),6*N)
    def test_special_never_included(self):
        rows=fixture(110)
        for r in rows:r['numbers']=[1,2,3,4,5,6];r['special']=49
        a=analyze(rows,100)
        self.assertEqual([s['seed'] for s in a['results']],[1,2,3,4,5,6])
        for s in a['results']:self.assertEqual(s['counts'][49],0);self.assertEqual(s['N'],99)
    def test_gap_excluded(self):
        rows=fixture();rows.pop(-8);r=analyze(rows,100);self.assertFalse(r['complete'])
        for s in r['results']:self.assertTrue(all(adjacent(d['from'],d['to']) for d in s['details']))
    def test_zero_samples(self):
        rows=fixture(110)
        for r in rows:r['numbers']=[1,2,3,4,5,6];r['special']=49
        rows[-1]['numbers']=[40,41,42,43,44,45]
        for s in analyze(rows,100)['results']:self.assertEqual(s['N'],0);self.assertEqual(s['top'],[])
    def test_tie_order_and_self_follow(self):
        rows=fixture(110)
        for r in rows:r['numbers']=[1,2,3,4,5,6];r['special']=49
        for s in analyze(rows,100)['results']:
            self.assertEqual([t['number'] for t in s['top']],[1,2,3]);self.assertTrue(all(t['tied'] for t in s['top']));self.assertEqual(s['counts'][s['seed']],99)
    def test_insufficient_per_window(self):
        for n in (99,100,149,150,199,200,299,300):
            for w in analyze_many(fixture(n))['windows']:self.assertEqual(w['analysis'] is not None,n>=w['size'])
    def test_special_conflict_preserves_original(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(td);rows=fixture();st.merge(rows);bad=rows[-1].copy();bad['special']=next(n for n in range(1,50) if n not in bad['numbers'] and n!=bad['special']);bad['source']='other';st.merge([bad]);self.assertEqual(st.rows()[-1]['special'],rows[-1]['special']);self.assertIn('衝突',st.rows()[-1]['status'])
    def test_database_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(td)
            with st.db() as c:c.execute("UPDATE metadata SET value='CA_FANTASY5' WHERE key='game'")
            with self.assertRaises(ValueError):Store(td)
    def test_snapshot_reopen_export(self):
        with tempfile.TemporaryDirectory(prefix='中文 路徑 ') as td:
            st=Store(td);st.merge(fixture());r=analyze_many(st.rows());st.snapshot(r);saved=Store(td).latest_snapshot();cp,hp,jp=export_many(saved,Path(td)/'exports')
            self.assertTrue(cp.read_bytes().startswith(b'\xef\xbb\xbf'));self.assertIn('特別號',hp.read_text(encoding='utf-8'));self.assertEqual(json.loads(jp.read_text(encoding='utf-8'))['windows'][3]['size'],300)
    def test_csv(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'t.csv'
            with p.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f);w.writerow(['期別','日期']+[f'號碼{i}' for i in range(1,7)]+['特別號']);w.writerow(['26/117','2026-11-05',11,20,28,29,42,47,46])
            self.assertEqual(import_csv(p)[0]['special'],46)
    def test_biga_parser(self):
        cells=['1','2026/11/05','星期四','26/117','202644','1','癸未']+[11,20,28,29,42,47]+[47,28,20,42,29,11]+[46]
        text='六合彩<table><tr>'+''.join(f'<td>{x}</td>' for x in cells)+'</table>'
        self.assertEqual(parse_biga(text)[0]['special'],46)
    def test_wrong_game_rejected(self):
        with self.assertRaises(ValueError):parse_biga('加州夢幻5<table></table>')
    def test_failure_preserves(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(td);st.merge(fixture())
            with patch('sources.get',side_effect=RuntimeError('HTTP 403')):note=update(st,Event(),lambda x:None)
            self.assertIn('原有有效資料保留',note);self.assertEqual(len(st.rows()),330)
    def test_duplicate_rejected(self):
        rows=fixture(10)
        with self.assertRaises(ValueError):validate(rows+[rows[0]])
    def test_snapshot_json_counts_reexport(self):
        r=json.loads(json.dumps(analyze_many(fixture())))
        with tempfile.TemporaryDirectory() as td:self.assertTrue(all(p.exists() for p in export_many(r,td)))
if __name__=='__main__':unittest.main()
