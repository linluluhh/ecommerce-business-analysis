"""Read-only acceptance summary for a completed real-browser run."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
import streamlit
from v2.rules import ROOT, VERSION
from v2.service import Store


def main(directory):
    evidence = ROOT/'v2/evidence'
    browser = json.loads((evidence/'browser-results.json').read_text(encoding='utf-8'))
    assert browser['passed']
    suite = ET.parse(evidence/'pytest-results.xml').getroot().find('testsuite')
    assert suite.attrib['failures']=='0' and suite.attrib['errors']=='0'
    store = Store(directory)
    with store.connect() as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        batches = con.execute('SELECT * FROM batches').fetchall()
        assert len(batches)==5
        for batch in batches:
            assert hashlib.sha256((store.root/batch['raw_path']).read_bytes()).hexdigest()==batch['sha256']
        reviews = con.execute('SELECT * FROM reviews').fetchall()
        assert len(reviews)==2
        assert {r['to_status'] for r in reviews}=={'驳回','确认'}
    assert store.metrics('demo')['sales']==365
    assert store.metrics('business')['sales']==35
    git = ['git','-c',f'safe.directory={ROOT.as_posix()}']
    changed = subprocess.check_output(git+['diff','HEAD','--name-only'],cwd=ROOT,text=True).splitlines()
    assert all(name.startswith('v2/') for name in changed), changed
    baseline = subprocess.check_output(git+['rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    v1_hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                 for folder in ('data/raw','reports') for p in (ROOT/folder).rglob('*') if p.is_file()}
    result = {'python':platform.python_version(),'streamlit':streamlit.__version__,
              'pytest':suite.attrib,'browser_checks':browser['checks'],
              'database_integrity':'ok','all_original_files_sha256_verified':True,
              'batches':len(batches),'reviews':len(reviews),
              'demo_sales':'365','business_sales':'35',
              'v1_base_commit':baseline,'v1_rule_sha256':VERSION,
              'tracked_changes_outside_v2':[],'v1_data_report_sha256':v1_hashes}
    (evidence/'delivery-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='v1_data_report_sha256'},ensure_ascii=True,indent=2))


if __name__=='__main__':
    main(sys.argv[1])
