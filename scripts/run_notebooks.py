"""从干净Jupyter内核执行V1 Notebook，保存实际输出，不触碰原学习Notebook。"""
from pathlib import Path
import asyncio
import sys
import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager

ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    if hasattr(asyncio,'WindowsSelectorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    for name in ['01_data_cleaning_v1.ipynb','02_business_analysis_v1.ipynb']:
        path=ROOT/'notebooks'/name
        notebook=nbformat.read(path,as_version=4)
        # 明确使用执行此脚本的解释器，避免新虚拟环境误用本机注册的旧内核。
        manager=KernelManager(kernel_name='python3')
        manager.kernel_spec.argv=[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}']
        NotebookClient(notebook,km=manager,timeout=180,startup_timeout=60,kernel_name='python3',resources={'metadata':{'path':str(ROOT/'notebooks')}}).execute()
        nbformat.write(notebook,path)
        print(name,'executed successfully',flush=True)
