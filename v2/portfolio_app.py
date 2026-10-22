"""Public Synthetic entrypoint. No environment-based business database access."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from v2.portfolio_sessions import sessions, DemoUnavailable


def main():
    try:
        manager = sessions()
    except OSError:
        st.error("临时演示空间无法建立，请稍后重试。")
        return
    token = st.session_state.get('_public_session')
    if st.sidebar.button('重置我的演示', key='_public_reset'):
        manager.discard(token)
        st.session_state.clear()
        st.rerun()
    try:
        with manager.lease(token) as (current, store):
            if token != current:
                st.session_state.clear()
                st.session_state['_public_session'] = current
            entry = Path(__file__).with_name('app.py')
            # A fresh namespace per rerun; unlike runpy this does not mutate sys.modules.
            exec(compile(entry.read_text(encoding='utf-8-sig'), str(entry), 'exec'),
                 {'__name__': '__main__', '__file__': str(entry), '_portfolio_store': store})
    except DemoUnavailable as exc:
        st.error(str(exc))
        st.info('公开演示只使用 Synthetic 数据；不会连接真实业务库。可点击左侧重置重试。')


if __name__ == '__main__':
    main()
