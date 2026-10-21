"""Shared display formatting; inputs and exported evidence remain unchanged."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from v2.ui_status import Status, TEXT


def number(value, suffix='', state=None):
    if state is not None and state not in (Status.NORMAL, Status.WARNING):
        return TEXT[state]
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return TEXT[Status.INSUFFICIENT_DATA]
        return f'{amount:.2f}{suffix}'
    except (InvalidOperation, ValueError, TypeError):
        return TEXT[Status.INSUFFICIENT_DATA]


def money(value, state=None):
    return number(value, ' USD', state)


def percent(value, state=None):
    if state is not None and state not in (Status.NORMAL, Status.WARNING):
        return TEXT[state]
    try:
        return number(None if value is None else Decimal(str(value))*100, '%', state)
    except (InvalidOperation, ValueError, TypeError):
        return TEXT[Status.INSUFFICIENT_DATA]


def percentage_points(value, *, directional=True, state=None):
    if value is None or (state is not None and state not in (Status.NORMAL, Status.WARNING)):
        return number(None, state=state)
    try:
        amount = Decimal(str(value))*100
    except (InvalidOperation, ValueError, TypeError):
        return TEXT[Status.INSUFFICIENT_DATA]
    if not amount.is_finite():
        return TEXT[Status.INSUFFICIENT_DATA]
    if not directional:
        return number(amount, '个百分点')
    prefix = '上涨' if amount > 0 else '下降' if amount < 0 else '持平'
    return prefix + number(abs(amount), '个百分点')


def roas(value, state=None):
    return number(value, '倍', state)


def timestamp(value):
    if value is None or str(value).strip() in ('', 'NaT', 'nan', 'None'):
        return TEXT[Status.INSUFFICIENT_DATA]
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        # A date or naive timestamp has no proven timezone: do not guess.
        if parsed.tzinfo is None:
            return str(value)
        return parsed.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return str(value)


def display_times(frame):
    result = frame.copy()
    for column in ('created_at', 'updated_at', 'effective_at', 'first_detected', 'last_detected'):
        if column in result:
            result[column] = result[column].map(timestamp)
    return result


def rule_value(kind, value):
    if kind in ('margin_drop', 'unknown_cost_up', 'refund_platform_up'):
        return percentage_points(value, directional=False)
    if kind == 'roas_low':
        return roas(value)
    if kind == 'stock_low':
        return number(value, '件')
    if kind == 'stock_cover':
        return number(value, '天')
    return percent(value)
