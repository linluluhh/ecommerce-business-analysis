"""Transactional, append-only ingestion, quality review and Decimal accounting."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import uuid
import pandas as pd
from v2.rules import GRAINS, SCHEMAS, VERSION, check, policy, affected_fields, describe, v1


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class Store:
    api_version = 3
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'monitor.sqlite'
        with self.connect() as con:
            con.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
        from v2.migrate import migrate
        migrate(self)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA journal_mode=WAL')
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def log(self, con, workspace, action, target, actor, detail):
        con.execute('INSERT INTO operation_logs(workspace,action,target,actor,detail_json,created_at) VALUES(?,?,?,?,?,?)',
                    (workspace,action,str(target),actor,dump(detail),now()))

    def parse(self, filename, content, kind):
        suffix = Path(filename).suffix.lower()
        if suffix == '.csv':
            if kind not in SCHEMAS:
                raise ValueError('CSV 必须选择业务表类型')
            try:
                frame = pd.read_csv(BytesIO(content),dtype='string',encoding='utf-8-sig')
            except UnicodeDecodeError:
                frame = pd.read_csv(BytesIO(content),dtype='string',encoding='gb18030')
            frames = {kind: frame}
        elif suffix == '.xlsx':
            book = pd.ExcelFile(BytesIO(content),engine='openpyxl')
            if kind == 'workbook':
                if not set(book.sheet_names).issubset(SCHEMAS):
                    raise ValueError('工作表名必须为 orders/products/customers/refunds/ads/inventory')
                frames = {name: pd.read_excel(book,sheet_name=name,dtype='string') for name in book.sheet_names}
            else:
                if len(book.sheet_names) != 1:
                    raise ValueError('多表 Excel 请选择 workbook；单表 Excel 必须只有一个工作表')
                frames = {kind: pd.read_excel(book,dtype='string')}
        else:
            raise ValueError('仅支持 .csv 与 .xlsx（旧 .xls 请另存为 .xlsx）')
        for name, frame in frames.items():
            if name not in SCHEMAS or list(frame.columns) != SCHEMAS[name]:
                if name in SCHEMAS and set(frame.columns) == set(SCHEMAS[name]):
                    frames[name] = frame[SCHEMAS[name]]
                else:
                    raise ValueError(f'{name} 字段不符合 V1 模板，应为：{SCHEMAS.get(name)}')
        if sum(len(f) for f in frames.values()) > 100000:
            raise ValueError('单次导入最多 100,000 行，请分批上传')
        return frames

    def ingest(self, filename, content, kind='orders', workspace='business', actor='本地操作员'):
        if workspace not in ('business','demo'):
            raise ValueError('未知数据空间')
        if not actor.strip():
            raise ValueError('请填写操作员')
        if len(content) > 20 * 1024 * 1024:
            raise ValueError('上传文件不能超过 20MB')
        batch = uuid.uuid4().hex
        raw_dir = self.root / 'uploads' / batch
        raw_dir.mkdir(parents=True)
        suffix = Path(filename).suffix.lower()
        raw = raw_dir / ('original' + (suffix if suffix in ('.csv','.xlsx') else '.bin'))
        with raw.open('xb') as file:
            file.write(content)
        sha = hashlib.sha256(content).hexdigest()
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            previous = con.execute("SELECT id FROM batches WHERE workspace=? AND sha256=? AND import_kind=? AND status='imported'",(workspace,sha,kind)).fetchone()
            con.execute('INSERT INTO batches(id,workspace,filename,sha256,import_kind,raw_path,status,duplicate_of,created_at,rule_version) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (batch,workspace,Path(filename).name,sha,kind,str(raw.relative_to(self.root)),
                         'duplicate' if previous else 'failed',previous['id'] if previous else None,now(),VERSION))
            if previous:
                self.log(con,workspace,'duplicate_upload',batch,actor,{'duplicate_of':previous['id']})
                return {'batch_id':batch,'status':'duplicate','added':0,'duplicate_of':previous['id']}
            try:
                frames = self.parse(filename,content,kind)
                con.execute('SAVEPOINT ingestion')
                added = duplicate = 0
                revised_fingerprints=set()
                if con.execute("SELECT 1 FROM record_revisions WHERE workspace=? AND status='已批准' LIMIT 1",(workspace,)).fetchone():
                    for rec in self.records(con,workspace):
                        if rec.get('revision_ids'):
                            value=json.loads(rec['raw_json'])
                            revised_fingerprints.add((rec['table_name'],hashlib.sha256(dump(self.canonical(rec['table_name'],value)).encode()).hexdigest()))
                for name, frame in frames.items():
                    for offset, row in enumerate(frame.to_dict('records'),start=2):
                        row = {k: None if pd.isna(v) else str(v) for k,v in row.items()}
                        payload = dump(row)
                        # Canonical numeric spelling prevents 10 vs 10.0 (CSV/Excel) double imports.
                        fingerprint = hashlib.sha256(dump(self.canonical(name,row)).encode()).hexdigest()
                        if (name,fingerprint) in revised_fingerprints:
                            duplicate+=1
                            continue
                        key = dump([self.key_value(k,row[k]) for k in GRAINS[name][0]])
                        cursor = con.execute('INSERT OR IGNORE INTO records(workspace,batch_id,table_name,source_row,business_key,fingerprint,raw_json) VALUES(?,?,?,?,?,?,?)',
                                             (workspace,batch,name,offset,key,fingerprint,payload))
                        added += cursor.rowcount
                        duplicate += 1-cursor.rowcount
                self.refresh(con,workspace)
                con.execute('RELEASE ingestion')
                count = sum(len(f) for f in frames.values())
                con.execute("UPDATE batches SET status='imported',row_count=?,added_count=?,duplicate_rows=? WHERE id=?",(count,added,duplicate,batch))
                self.log(con,workspace,'import',batch,actor,{'rows':count,'added':added,'duplicates':duplicate})
                return {'batch_id':batch,'status':'imported','added':added,'duplicates':duplicate}
            except Exception as exc:
                if con.in_transaction:
                    # Parsing may fail before the savepoint exists.
                    try:
                        con.execute('ROLLBACK TO ingestion')
                        con.execute('RELEASE ingestion')
                    except sqlite3.OperationalError:
                        pass
                con.execute('UPDATE batches SET error=? WHERE id=?',(str(exc),batch))
                self.log(con,workspace,'failed_import',batch,actor,{'error':str(exc)})
                return {'batch_id':batch,'status':'failed','error':str(exc),'added':0}

    @staticmethod
    def key_value(key, value):
        if value is None:
            return None
        if key == 'sku':
            return value.strip().upper()
        if key == 'platform':
            return v1.PLATFORMS.get(value.strip().lower(),value)
        if key == 'date':
            return value.strip().replace('/','-')
        return value

    def canonical(self, name, row):
        numeric = set(SCHEMAS[name]) - set(GRAINS[name][0]) - {
            'order_id','customer_id','sku','refund_id','campaign_id','product_name','category','supplier',
            'platform','country','order_status','refund_reason','refund_status','customer_type',
            'order_date','date','refund_date','register_date','launch_date'}
        result = dict(row)
        for col in numeric:
            try:
                val = Decimal(str(row[col]))
                if val.is_finite():
                    result[col] = format(val.normalize(),'f')
            except InvalidOperation:
                pass
        return result

    def records(self, con, workspace):
        from v2.revisions import effective_rows
        return effective_rows(con,workspace)

    def evaluate(self, con, workspace):
        rows = self.records(con,workspace)
        tables = {n: pd.DataFrame(columns=cols).astype('string') for n,cols in SCHEMAS.items()}
        groups = {}
        for rec in rows:
            groups.setdefault((rec['table_name'],rec['business_key']),[]).append(rec['id'])
        conflicts = {idx for ids in groups.values() if len(ids)>1 for idx in ids}
        diagnostics = []
        prepared = {name: [] for name in SCHEMAS}
        indices = {name: [] for name in SCHEMAS}
        for rec in rows:
            name, idx = rec['table_name'], rec['id']
            row = json.loads(rec['raw_json'])
            codes = []
            if idx in conflicts:
                codes.append(('business_key_conflict','同一标准业务键存在不同内容；所有版本隔离，禁止自动覆盖'))
            if any(row[key] is None for key in GRAINS[name][0]):
                codes.append(('missing_business_key','业务键缺失，无法可靠去重或关联'))
            for value in self.canonical(name,row).values():
                if str(value).lower() in ('inf','-inf','infinity','-infinity','nan'):
                    codes.append(('non_finite','非有限值不得进入金额统计'))
                    break
            if codes:
                diagnostics.extend({'record_id':idx,'table':name,'issue':code,'action':reason} for code,reason in codes)
            else:
                prepared[name].append(row)
                indices[name].append(idx)
        for name in SCHEMAS:
            if prepared[name]:
                tables[name] = pd.DataFrame(prepared[name],index=indices[name],columns=SCHEMAS[name]).astype('string')
        clean, issues = check(tables)
        diagnostics.extend({**issue,'record_id':issue['source_csv_row']-2} for issue in issues)
        return clean, diagnostics

    def refresh(self, con, workspace):
        _, issues = self.evaluate(con,workspace)
        con.execute('UPDATE anomalies SET active=0 WHERE record_id IN (SELECT id FROM records WHERE workspace=?)',(workspace,))
        for issue in issues:
            code, table = issue['issue'], issue['table']
            scope, hard, severity = policy(code,table)
            con.execute('INSERT INTO anomalies(record_id,code,reason,fields,severity,scope,hard,created_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(record_id,code) DO UPDATE SET active=1',
                        (issue['record_id'],code,describe(code,issue['action']),affected_fields(code,table),severity,scope,int(hard),now()))

    def query(self, sql, args=()):
        with self.connect() as con:
            return pd.read_sql_query(sql,con,params=args)

    def anomalies(self, workspace):
        return self.query('SELECT a.*,r.table_name,r.business_key,r.batch_id,r.source_row,r.raw_json FROM anomalies a JOIN records r ON a.record_id=r.id WHERE r.workspace=? ORDER BY a.active DESC,a.id DESC',(workspace,))

    def review(self, anomaly_id, status, note, reviewer, expected_version, workspace):
        if status not in ('确认','驳回','待核实') or not note.strip() or not reviewer.strip():
            raise ValueError('状态、操作员和处理说明均为必填')
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            issue = con.execute('SELECT a.* FROM anomalies a JOIN records r ON a.record_id=r.id WHERE a.id=? AND r.workspace=?',(anomaly_id,workspace)).fetchone()
            if not issue or not issue['active']:
                raise ValueError('异常不存在或已失效，请刷新工作台')
            if issue['version'] != expected_version:
                raise ValueError('异常已被其他会话审核，请刷新后重试')
            con.execute('UPDATE anomalies SET status=?,version=version+1 WHERE id=?',(status,anomaly_id))
            con.execute('INSERT INTO reviews(anomaly_id,from_status,to_status,note,reviewer,created_at) VALUES(?,?,?,?,?,?)',
                        (anomaly_id,issue['status'],status,note.strip(),reviewer.strip(),now()))
            self.log(con,workspace,'review',anomaly_id,reviewer,{'from':issue['status'],'to':status,'note':note})

    def metrics(self, workspace):
        from v2.metrics import MetricCenter
        return MetricCenter(self).legacy(workspace)
