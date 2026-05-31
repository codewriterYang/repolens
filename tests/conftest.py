"""最小 conftest — 仅需项目根目录在 PYTHONPATH 上。"""
import sys
from pathlib import Path

# 确保 backend/ 可被导入
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))
