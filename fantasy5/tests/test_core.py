import unittest,tempfile,csv,json,sys
from pathlib import Path
from datetime import date,timedelta
from collections import Counter
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import *
from sources import parse_official,parse_biga,update
from threading import Event

def fixture(count=60):
    return [draw(11001+i,(date(2025,1,1)+timedelta(days=i)).isoformat(),sorted({(i*3+j*7)%39+1 for j in range(5)}),'TEST ONLY') for i in range(count)]
class Statistics(unittest.TestCase):
    def test_independent_recount_and_boundary(self):
        rows=fixture();r=analyze(rows);w=rows[-50:]
        self.assertEqual(r['start'],rows[10]);self.assertTrue(r['complete'])
        for s in r['results']:
            expected=Counter();N=0
            for i in range(49):
                if s['seed'] in w[i]['numbers']:expected.update(w[i+1]['numbers']);N+=1
            self.assertEqual(s['N'],N);self.assertEqual(s['counts'],{n:expected[n] for n in range(1,40)})
            self.assertEqual(sum(s['counts'].values()),5*N)
            for t in s['top']:self.assertEqual(t['count'],expected[t['number']])
    def test_gap_excluded(self):
        rows=fixture();rows.pop(30);r=analyze(rows)
        self.assertFalse(r['complete']);self.assertEqual(len(r['warnings']),1)
        for s in r['results']:
            self.assertFalse(any(int(d['to']['period'])-int(d['from']['period'])!=1 for d in s['details']))
    def test_self_follow_and_latest(self):
        rows=fixture(50)
        for r in rows:r['numbers']=[1,2,3,4,5]
        r=analyze(rows)
        for s in r['results']:
            self.assertEqual(s['N'],49);self.assertEqual([t['number'] for t in s['top']],[1,2,3]);self.assertEqual(s['counts'][s['seed']],49)
            self.assertTrue(all(t['ratio']==100 and t['tied'] for t in s['top']))
    def test_zero_samples(self):
        rows=fixture(50)
        for r in rows:r['numbers']=[1,2,3,4,5]
        rows[-1]['numbers']=[35,36,37,38,39]
        for s in analyze(rows)['results']:self.assertEqual(s['N'],0);self.assertEqual(s['top'],[])
    def test_tie_recent_then_number(self):
        rows=fixture(50)
        for r in rows:r['numbers']=[10,11,12,13,14]
        rows[0]['numbers']=[1,20,21,22,23];rows[1]['numbers']=[2,3,4,5,6]
        rows[20]['numbers']=[1,20,21,22,23];rows[21]['numbers']=[7,8,9,15,16]
        rows[-1]['numbers']=[1,30,31,32,33]
        s=analyze(rows)['results'][0]
        self.assertEqual(s['N'],2);self.assertEqual([t['number'] for t in s['top']],[7,8,9])
    def test_insufficient(self):
        with self.assertRaisesRegex(ValueError,'資料不足'):analyze(fixture(49))
    def test_validation(self):
        for ns in ([1,1,2,3,4],[0,1,2,3,4],[1,2,3,4,40],[1,2,3]):
            with self.assertRaises(ValueError):draw(11001,'2025-01-01',ns,'test')
        rows=fixture()
        with self.assertRaises(ValueError):validate(rows+[rows[0]])
        with self.assertRaises(ValueError):draw(11001,'2025-02-30',[1,2,3,4,5],'test')
    def test_year_boundary_continuous(self):
        self.assertTrue(adjacent(draw(11000,'2024-12-31',[1,2,3,4,5],'test'),draw(11001,'2025-01-01',[1,2,3,4,5],'test')))
    def test_conflict_pair_excluded(self):
        rows=fixture();rows[-2]['status']='來源衝突';r=analyze(rows)
        self.assertFalse(r['complete']);self.assertEqual(len(r['warnings']),2)

class Persistence(unittest.TestCase):
    def test_unicode_storage_reopen_snapshots_exports(self):
        with tempfile.TemporaryDirectory(prefix='中文 路徑 ') as td:
            st=Store(td);st.merge(fixture());st.merge(fixture());self.assertEqual(len(st.rows()),60)
            r=analyze(st.rows());st.snapshot(r)
            reopened=Store(td);self.assertEqual(reopened.latest_snapshot()['current']['period'],r['current']['period'])
            cp,hp=export_report(r,Path(td)/'exports');self.assertTrue(cp.read_bytes().startswith(b'\xef\xbb\xbf'));self.assertIn('完整拖牌',hp.read_text(encoding='utf-8'))
            self.assertIn('歷史拖出比例',hp.read_text(encoding='utf-8'))
    def test_conflict_preserved_and_observed(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(td);rows=fixture();st.merge(rows);bad=rows[-1].copy();bad['numbers']=[1,2,3,4,5];bad['source']='different'
            self.assertEqual(st.merge([bad]),[bad['period']]);self.assertEqual(st.rows()[-1]['numbers'],rows[-1]['numbers']);self.assertIn('衝突',st.rows()[-1]['status'])
    def test_cross_verified(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(td);rows=fixture();rows[0]['source']='加州彩券官方：url';st.merge(rows)
            r=rows[0].copy();r['source']='Biga：url';st.merge([r]);self.assertIn('交叉驗證一致',st.rows()[0]['status'])
    def test_csv_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'in.csv'
            with p.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f);w.writerow(['期別','日期','號碼1','號碼2','號碼3','號碼4','號碼5']);w.writerow(['012001','2025/01/01',1,2,3,4,5])
            rows=import_csv(p);self.assertEqual(rows[0]['period'],'012001')
            st=Store(td);st.merge(rows)
            with p.open('a',encoding='utf-8') as f:f.write('012002,2025/01/02,1,1,2,3,4\n')
            with self.assertRaises(ValueError):st.merge(import_csv(p))
            self.assertEqual(len(st.rows()),1)
    def test_network_failure_preserves(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(td);st.merge(fixture())
            with patch('sources.get',side_effect=RuntimeError('HTTP 403')):
                result=update(st,Event(),lambda x:None)
            self.assertIn('HTTP 403',result);self.assertIn('原有有效資料保留',result);self.assertEqual(len(st.rows()),60)
    def test_parsers_reject_changed_format(self):
        with self.assertRaises(ValueError):parse_official('{"rtCode":0,"content":{}}')
        with self.assertRaises(ValueError):parse_biga('<html>login</html>')
    def test_biga_unclosed_rows(self):
        cells=['1','2025/01/01','星期三','012001','202501','1','甲子',1,2,3,4,5,5,4,3,2,1]
        row='<tr>'+''.join(f'<td>{x}</td>' for x in cells)
        parsed=parse_biga('加州夢幻5<table>'+row+'</table>')
        self.assertEqual(len(parsed),1);self.assertEqual(parsed[0]['period'],'012001')
        self.assertEqual(parsed[0]['draw_timezone'],'America/Los_Angeles')
    def test_reject_taiwan_period(self):
        with self.assertRaises(ValueError):draw(115000266,'2026-11-03',[1,2,3,4,5],'test')
    def test_date_gap_even_when_id_continuous(self):
        self.assertFalse(adjacent(draw(12001,'2025-01-01',[1,2,3,4,5],'test'),draw(12002,'2025-01-03',[1,2,3,4,5],'test')))
    def test_los_angeles_future_guard(self):
        from datetime import datetime,timezone
        instant=datetime(2026,11,4,4,0,tzinfo=timezone.utc)
        with patch('core.datetime') as clock:
            clock.now.side_effect=lambda zone:instant.astimezone(zone)
            with self.assertRaisesRegex(ValueError,'加州開獎日期在未來'):
                draw(12051,'2026-11-04',[1,2,3,4,5],'test')
    def test_official_latest_parser(self):
        page='<h1>Fantasy 5</h1> Winning Numbers: TUE/NOV 3, 2026 Draw #12050 <ul>'+''.join(f'<li>{n}</li>' for n in [5,17,19,24,31])+'</ul> This Could Be Your Lucky Day!'
        rows=parse_official(page)
        self.assertEqual(rows[0]['numbers'],[5,17,19,24,31]);self.assertEqual(rows[0]['period'],'012050')
    def test_database_game_guard(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(td)
            with st.db() as c:c.execute("UPDATE metadata SET value='TW539' WHERE key='game'")
            with self.assertRaisesRegex(ValueError,'彩種不符'):Store(td)
if __name__=='__main__':unittest.main(verbosity=2)
