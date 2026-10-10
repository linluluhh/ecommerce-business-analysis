"""检查实际Git暂存/历史内容，不凭gitignore宣称安全。不创建远程或上传。

输入Git索引、发布测试证据和README；输出候选清单、检查JSON与Markdown。
"""
from pathlib import Path
import io
import json
import re
import subprocess
import zipfile
from urllib.parse import unquote
import nbformat

ROOT=Path(__file__).resolve().parents[1]


def git(*args,check=True):
    # 仅对当前项目定向声明安全目录，不改全局配置，不执行网络操作。
    r=subprocess.run(['git','-c','safe.directory='+str(ROOT),*args],cwd=ROOT,capture_output=True)
    if check and r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace'))
    return r


def decoded_strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,list):
        for item in value:yield from decoded_strings(item)
    elif isinstance(value,dict):
        for item in value.values():yield from decoded_strings(item)


def scan_blob(name,data):
    issues=[]
    protected=['.venv','.acceptance-work','.github-release-work','.dashboard-browser','node_modules','__pycache__']
    if any(part in protected for part in Path(name).parts) or name in ['notebooks/01_data_quality.ipynb','data/processed/orders.xlsx','scripts/generate_data.py']:
        issues.append('protected_local_artifact')
    if len(data)>25*1024*1024:issues.append('file_over_25MiB')
    suffix=Path(name).suffix
    if suffix in ['.py','.md','.txt','.json','.ipynb','.sql','.html','.mjs','.csv']:
        text=data.decode('utf-8-sig',errors='replace')
        if suffix in ['.json','.ipynb']:
            text='\n'.join(decoded_strings(json.loads(text)))
        secrets=[r'sk-[A-Za-z0-9]{24,}',r'gh[pousr]_[A-Za-z0-9]{24,}',r'AKIA[A-Z0-9]{16}',r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----']
        if any(re.search(p,text) for p in secrets):issues.append('possible_secret')
        if name=='dashboard/index.html':
            # 仅剥离与锁定安装包逐字一致的公开Plotly JS，不笼统豁免HTML。
            # vendor内的版权邮箱/示例URL不属于用户隐私；其余页面仍完整扫描。
            from plotly.offline import get_plotlyjs
            vendor=get_plotlyjs().replace('\r\n','\n')
            text=text.replace('\r\n','\n')
            if vendor not in text:issues.append('embedded_vendor_does_not_match_installed_package')
            else:text=text.replace(vendor,'VERIFIED_PLOTLY_VENDOR_BUNDLE',1)
        # 驱动器路径要求后续目录字符，避免正则/JSON lambda示例误报。
        if name not in ['scripts/check_github_release.py','scripts/audit_acceptance_v1.py'] and re.search(r'(?<![A-Za-z])[A-Za-z]:[\\/](?:Users|Program|Windows|跨境|[^\s\\]+[\\/])',text):issues.append('absolute_local_path')
        emails=re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',text)
        private=[x for x in emails if not x.endswith(('users.noreply.github.com','example.com','example.invalid')) and not name.startswith('docs/third_party/')]
        if private:issues.append('email_requires_review')
    if suffix=='.xlsx':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if 'docProps/core.xml' in z.namelist():
                text=z.read('docProps/core.xml').decode('utf-8',errors='replace')
                if re.search(r'<(?:dc:creator|cp:lastModifiedBy)>[^<]+',text):issues.append('author_metadata_requires_review')
            if any('externalLink' in n for n in z.namelist()):issues.append('external_workbook_link')
    return issues


def main():
    staged=git('ls-files','--stage','-z').stdout.decode('utf-8')
    candidates=[];findings=[]
    for row in staged.split('\0'):
        if not row:continue
        mode,oid,rest=row.split(' ',2);stage,name=rest.split('\t',1)
        data=git('cat-file','blob',oid).stdout
        if mode=='120000':findings.append({'file':name,'issues':['symlink_requires_review']})
        bad=scan_blob(name,data)
        if bad:findings.append({'file':name,'issues':bad})
        candidates.append({'file':name,'bytes':len(data),'blob':oid})
    assert candidates,'Git索引为空，不能声称检查已完成'
    # 检查所有已有历史对象；本项目初始无历史，提交后可重新扫描。
    history=[];rev=git('rev-list','--objects','--all',check=False)
    if rev.returncode==0:
        for line in rev.stdout.decode('utf-8').splitlines():
            fields=line.split(' ',1)
            if len(fields)!=2:continue
            oid,name=fields
            if git('cat-file','-t',oid).stdout.strip()!=b'blob':continue
            bad=scan_blob(name,git('cat-file','blob',oid).stdout)
            if bad:history.append({'file':name,'blob':oid,'issues':bad})
    readme=git('show',':README.md').stdout.decode('utf-8')
    links=[];candidate_paths={x['file'] for x in candidates}
    for image,label,target in re.findall(r'(!?)\[([^\]]*)\]\(([^\s)]+)\)',readme):
        if target.startswith(('https://','http://','#','mailto:')):continue
        target=unquote(target.split('#')[0]);resolved=(ROOT/target).resolve()
        rel=resolved.relative_to(ROOT).as_posix()
        good=(rel in candidate_paths) or (resolved.is_dir() and any(p.startswith(rel+'/') for p in candidate_paths))
        links.append({'target':target,'image':bool(image),'valid_staged_target':good})
    code_fences=readme.count('```')%2==0
    intro=readme.split('## 项目简介')[1].split('**目标岗位')[0].strip()
    assert 100<=len(intro)<=150,f'简介长度{len(intro)}不在100-150'
    for name in ['notebooks/01_data_cleaning_v1.ipynb','notebooks/02_business_analysis_v1.ipynb']:
        notebook=nbformat.reads(git('show',':'+name).stdout.decode('utf-8'),as_version=4)
        nbformat.validate(notebook)
        assert all(c.execution_count is not None and not any(o.get('output_type')=='error' for o in c.outputs) for c in notebook.cells if c.cell_type=='code')
    proof=json.loads((ROOT/'reports/github_reproduction_evidence.json').read_text(encoding='utf-8'))
    # 审核输出不记录自身hash/size，避免自引用导致每次审核改变文件。
    self_outputs={'reports/github_candidate_manifest.json','reports/github_release_evidence.json'}
    payload=[x for x in candidates if x['file'] not in self_outputs]
    inventory=[x if x['file'] not in self_outputs else {'file':x['file'],'note':'audit output: self hash and size omitted'} for x in candidates]
    results={'candidate_file_count':len(candidates),'candidate_total_bytes':sum(x['bytes'] for x in payload),'size_scope':'excludes the two self-referential audit JSON files','largest_files':sorted(payload,key=lambda x:x['bytes'],reverse=True)[:5],'candidate_findings':findings,'history_findings':history,'readme_links':links,'markdown_fences_balanced':code_fences,'intro_characters':len(intro),'notebooks_executed':True,'full_reproduction_steps':proof['steps'],'git_remotes':git('remote').stdout.decode('utf-8').splitlines(),'repository_license':'not_selected','dashboard_public_deployment':False,'github_push_performed':False}
    (ROOT/'reports/github_candidate_manifest.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'reports/github_release_evidence.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    passed=not findings and not history and all(x['valid_staged_target'] for x in links) and code_fences and all(x['exit_code']==0 for x in proof['steps'])
    assert passed,'存在发布前问题，详见github_release_evidence.json，不得推送'
    print('PASS: actual staged blobs, existing history, README links, notebook outputs and reproduction evidence.')
    print('Candidate files:',len(candidates),'total MiB:',round(results['candidate_total_bytes']/1024**2,2))
    return results


if __name__=='__main__':main()
