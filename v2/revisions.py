"""Evidence-backed local revisions. Immutable originals; one effective version."""
import hashlib
import json
from v2.rules import SCHEMAS,GRAINS
from v2.service import dump,now


def digest(row):
    return hashlib.sha256(dump(row).encode()).hexdigest()


def effective_rows(con,workspace):
    rows=[dict(r) for r in con.execute('SELECT * FROM records WHERE workspace=? ORDER BY id',(workspace,))]
    revisions={}
    for rev in con.execute("SELECT * FROM record_revisions WHERE workspace=? AND status='已批准' ORDER BY id",(workspace,)):
        revisions.setdefault(rev['record_id'],[]).append(rev)
    for row in rows:
        data=json.loads(row['raw_json'])
        row['revision_ids']=[]
        for rev in revisions.get(row['id'],[]):
            if digest(data)!=rev['base_hash']:
                raise RuntimeError('修订版本链失配，停止计算，请核查审计记录')
            data.update(json.loads(rev['changes_json']))
            row['revision_ids'].append(rev['id'])
        row['raw_json']=dump(data)
    return rows


class Revisions:
    def __init__(self,store):
        self.store=store

    def request(self,workspace,record_id,changes,reason,evidence,applicant,anomaly_id=None):
        if not changes or not all(str(s).strip() for s in (reason,evidence,applicant)):
            raise ValueError('字段变化、原因、证据引用和申请人必填')
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            rows=effective_rows(con,workspace)
            record=next((r for r in rows if r['id']==record_id),None)
            if not record:
                raise ValueError('记录不属于当前空间')
            permitted=set(SCHEMAS[record['table_name']])-set(GRAINS[record['table_name']][0])
            if not set(changes).issubset(permitted):
                raise ValueError('只能修订现有非业务键字段；业务键冲突本阶段不自动选择版本')
            if anomaly_id is not None and not con.execute('SELECT 1 FROM anomalies WHERE id=? AND record_id=?',(anomaly_id,record_id)).fetchone():
                raise ValueError('异常与原始记录不匹配')
            old=json.loads(record['raw_json'])
            values={key:None if value is None else str(value) for key,value in changes.items()}
            if all(old[k]==v for k,v in values.items()):
                raise ValueError('新值与当前值完全相同')
            cur=con.execute('INSERT INTO record_revisions(workspace,record_id,base_hash,original_json,changes_json,reason,evidence_ref,applicant,created_at,anomaly_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (workspace,record_id,digest(old),dump(old),dump(values),reason,evidence,applicant,now(),anomaly_id))
            self.store.log(con,workspace,'revision_request',cur.lastrowid,applicant,{'record_id':record_id,'changes':values,'evidence':evidence})
            return cur.lastrowid

    def decide(self,workspace,revision_id,decision,actor,note):
        if decision not in ('已批准','已驳回') or not actor.strip() or not note.strip():
            raise ValueError('审批状态、操作员、说明必填')
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            rev=con.execute('SELECT * FROM record_revisions WHERE id=? AND workspace=?',(revision_id,workspace)).fetchone()
            if not rev or rev['status']!='待审核':
                raise ValueError('修订不存在、跨空间或已审核')
            if decision=='已批准':
                current=next(r for r in effective_rows(con,workspace) if r['id']==rev['record_id'])
                if digest(json.loads(current['raw_json']))!=rev['base_hash']:
                    raise ValueError('申请基于旧版本，请重新申请；禁止覆盖其他已批准修订')
            con.execute('UPDATE record_revisions SET status=?,effective_at=? WHERE id=?',
                        (decision,now() if decision=='已批准' else None,revision_id))
            con.execute('INSERT INTO revision_reviews(revision_id,decision,actor,note,created_at) VALUES(?,?,?,?,?)',
                        (revision_id,decision,actor,note,now()))
            if decision=='已批准':
                for flag in con.execute('SELECT * FROM anomalies WHERE record_id=? AND active=1',(rev['record_id'],)).fetchall():
                    if flag['status']!='待核实':
                        con.execute("UPDATE anomalies SET status='待核实',version=version+1 WHERE id=?",(flag['id'],))
                        con.execute('INSERT INTO reviews(anomaly_id,from_status,to_status,note,reviewer,created_at) VALUES(?,?,?,?,?,?)',
                                    (flag['id'],flag['status'],'待核实',f'修订 #{revision_id} 生效，旧值审核不自动授权新值',actor,now()))
                self.store.refresh(con,workspace)
            self.store.log(con,workspace,'revision_review',revision_id,actor,{'decision':decision,'note':note})
            # Approved invalid values remain flagged and quarantined by the unchanged V1 rules.
