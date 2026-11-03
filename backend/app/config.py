"""集中式配置：全部来自环境变量，启动时快速失败。

安全约定：真实密钥只允许出现在 .env / 环境变量中，绝不写入代码库。
JWT_SECRET 未提供时会自动生成并持久化到 data/.jwt_secret（本地零配置）。
"""

import os
import secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    """配置非法时抛出，启动即失败。"""


def _get_cors_origins(raw: str) -> list[str]:
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins and len(origins) > 1:
        raise ConfigError("CORS_ORIGINS 含有 * 时不能再混合其他来源")
    return origins


def _get_jwt_secret() -> str:
    """优先环境变量；否则自动生成并持久化，保证重启后已签发令牌仍然有效。"""
    secret = os.getenv("JWT_SECRET", "").strip()
    if secret:
        return secret
    secret_file = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data")) / ".jwt_secret"
    try:
        if secret_file.is_file():
            return secret_file.read_text().strip()
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secrets.token_urlsafe(48))
        secret_file.chmod(0o600)
        return secret_file.read_text().strip()
    except OSError:
        # 极端环境（只读文件系统）退化为进程内随机密钥（重启后需重新登录）
        return secrets.token_urlsafe(48)


_raw_db_url = os.getenv(
    "DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'data' / 'opengantt.db').as_posix()}"
)
if _raw_db_url.startswith("sqlite"):
    _db_path = _raw_db_url.split("///", 1)[-1]
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")

def _get_dept_webhooks() -> dict[str, str]:
    """部门级企微 Webhook 映射（用于按部门推送每日工作简报）。

    环境变量格式（分号分隔，URL 留空 = 占位未启用；值为空/未设置 = 全部未启用）：
        WECOM_DEPT_WEBHOOKS='商务运营部=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx;技术部=;人事行政部='
    启用规则：URL 非空的部门，每日 17:30 会收到一份仅含本部门成员的工作简报；
    URL 为空的部门为预留占位，拿到各群 Webhook 地址后填入即可启用，无需改代码。
    """
    raw = os.getenv("WECOM_DEPT_WEBHOOKS", "").strip().strip(";")
    if not raw:
        return {}
    out: dict[str, str] = {}
    for item in raw.split(";"):
        if not item.strip():
            continue
        name, _, url = item.partition("=")
        name, url = name.strip(), url.strip()
        if name:
            out[name] = url
    return out


DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data")).resolve()
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", DATA_DIR / "uploads")).resolve()


class Settings:
    """启动时一次性读取并校验的配置对象。"""

    APP_NAME: str = os.getenv("APP_NAME", "OpenGantt")
    DATABASE_URL: str = _raw_db_url
    CORS_ORIGINS: list[str] = _get_cors_origins(_cors_raw)
    SERVE_FRONTEND: bool = os.getenv("SERVE_FRONTEND", "true").lower() == "true"
    FRONTEND_DIST: Path = Path(os.getenv("FRONTEND_DIST", BACKEND_DIR.parent / "frontend" / "dist")).resolve()
    SEED_DEMO_DATA: bool = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"

    # 认证
    JWT_SECRET: str = _get_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    TOKEN_EXPIRE_DAYS: int = int(os.getenv("TOKEN_EXPIRE_DAYS", "7"))
    COOKIE_NAME: str = "og_token"

    # 上传
    UPLOAD_DIR: Path = UPLOAD_DIR
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "20"))

    # 内置演示账号（首次启动种子；生产环境请登录后立即修改密码）
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

    # 企微工作简报推送（群机器人 + AI 摘要）。未配置 webhook 时整体静默关闭。
    WECOM_WEBHOOK_URL: str = os.getenv("WECOM_WEBHOOK_URL", "").strip()
    # 部门级简报 Webhook 映射（格式与占位示例见 _get_dept_webhooks 文档）：
    # 已启用（URL 非空）的部门各推一份本部门简报；为空/未设置时回退全局 WECOM_WEBHOOK_URL。
    WECOM_DEPT_WEBHOOKS: dict[str, str] = _get_dept_webhooks()
    # 任务提醒单独入口（不配置则复用 WECOM_WEBHOOK_URL，可指向团队群而非领导群）
    WECOM_REMIND_WEBHOOK_URL: str = os.getenv("WECOM_REMIND_WEBHOOK_URL", "").strip()
    WECOM_PLATFORM_URL: str = os.getenv("WECOM_PLATFORM_URL", "http://127.0.0.1:8000").strip()

    # AI 摘要：OpenAI 兼容接口（默认智谱 GLM）。未配置 Key 时自动降级为规则模板摘要。
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "").strip()
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").strip().rstrip("/")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "glm-4-flash").strip()

    @property
    def app_name(self) -> str:
        return self.APP_NAME

    @property
    def serve_frontend(self) -> bool:
        return self.SERVE_FRONTEND

    @property
    def seed_demo_data(self) -> bool:
        return self.SEED_DEMO_DATA


settings = Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
