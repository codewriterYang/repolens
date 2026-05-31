"""应用配置，从环境变量加载。"""

import os
import tempfile
from dataclasses import dataclass, field


@dataclass
class Config:
    """集中配置，提供本地开发的合理默认值。"""

    # LLM 配置
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "sk-placeholder")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini")
    )
    llm_timeout_seconds: int = 60

    # 分析流水线
    pipeline_timeout_seconds: int = 180
    clone_timeout_seconds: int = 120

    # 数据库
    db_path: str = field(
        default_factory=lambda: os.getenv("DB_PATH", "data/repolens.db")
    )

    # 服务器
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8770")))

    # 路径（留空自动适配系统临时目录，填写则使用自定义路径）
    tmp_dir: str = field(
        default_factory=lambda: os.getenv("TMP_DIR") or os.path.join(tempfile.gettempdir(), "repolens")
    )


# 全局单例
config = Config()
