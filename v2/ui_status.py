"""Presentation-only states. Never modify eligibility, metrics or stored values."""
from enum import Enum


class Status(str, Enum):
    EMPTY_DATA = 'EMPTY_DATA'
    NO_MATCH_DATA = 'NO_MATCH_DATA'
    INSUFFICIENT_DATA = 'INSUFFICIENT_DATA'
    NOT_APPLICABLE = 'NOT_APPLICABLE'
    NORMAL = 'NORMAL'
    WARNING = 'WARNING'


TEXT = {
    Status.EMPTY_DATA: '尚未导入数据',
    Status.NO_MATCH_DATA: '当前范围无匹配数据',
    Status.INSUFFICIENT_DATA: '数据不足',
    Status.NOT_APPLICABLE: '不适用',
    Status.NORMAL: '正常',
    Status.WARNING: '请核查数据限制',
}


def workspace_has_data(store, workspace):
    return bool(store.query('SELECT EXISTS(SELECT 1 FROM records WHERE workspace=?) AS present',
                            (workspace,)).iloc[0]['present'])


def value_state(value, *, has_data=True, has_match=True, applicable=True, warning=False):
    if not has_data:
        return Status.EMPTY_DATA
    if not has_match:
        return Status.NO_MATCH_DATA
    if not applicable:
        return Status.NOT_APPLICABLE
    if value is None:
        return Status.INSUFFICIENT_DATA
    return Status.WARNING if warning else Status.NORMAL


def render_status(state, detail=None):
    import streamlit as st
    method = st.success if state == Status.NORMAL else st.warning if state == Status.WARNING else st.info
    method(TEXT[state] + ('；' + detail if detail else ''))


def quality_status(has_data, has_issues):
    if not has_data:
        return Status.EMPTY_DATA, '未评估：当前没有可检查记录，请先导入数据。'
    if has_issues:
        return Status.WARNING, '当前存在质量检查记录，请查看原因与隔离范围。'
    return Status.NORMAL, '当前检查范围内未发现异常，不代表业务账本完整。'
