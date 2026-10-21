"""Additive, checksum-verified migrations, with consistent SQLite backup."""
import hashlib
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime,timezone


def migrate(store):
    with store.connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,sha256 TEXT NOT NULL,applied_at TEXT NOT NULL,backup_path TEXT)')
        for path in sorted(Path(__file__).with_name('migrations').glob('*.sql')):
            sql=path.read_text(encoding='utf-8')
            sha=hashlib.sha256(sql.encode()).hexdigest()
            previous=con.execute('SELECT sha256 FROM schema_migrations WHERE version=?',(path.stem,)).fetchone()
            if previous:
                if previous[0]!=sha:
                    raise RuntimeError('已执行的迁移文件发生变化，必须新增迁移，禁止改写历史迁移')
                continue
            backup=None
            if con.execute('SELECT count(*) FROM records').fetchone()[0]:
                directory=store.root/'backups';directory.mkdir(exist_ok=True)
                backup=directory/(path.stem+'-'+uuid.uuid4().hex+'.sqlite')
                with sqlite3.connect(backup) as dest:
                    con.backup(dest)
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM schema_migrations WHERE version=?',(path.stem,)).fetchone():
                con.commit();continue
            statement=''
            for line in sql.splitlines():
                statement+=line+'\n'
                if sqlite3.complete_statement(statement):
                    con.execute(statement);statement=''
            if statement.strip():
                raise RuntimeError('迁移SQL不完整')
            con.execute('INSERT INTO schema_migrations VALUES(?,?,?,?)',
                        (path.stem,sha,datetime.now(timezone.utc).isoformat(),str(backup) if backup else None))
            con.commit()
