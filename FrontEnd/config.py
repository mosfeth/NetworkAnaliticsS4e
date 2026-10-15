"""Configuração independente do dashboard; conecta ao Supabase compartilhado."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


FRONTEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = FRONTEND_DIR.parent
LOCAL_ENV = FRONTEND_DIR / ".env"
ROOT_ENV = PROJECT_DIR / ".env"

# A máquina do dashboard pode ter suas próprias credenciais. Em desenvolvimento,
# ainda aceitamos o .env da raiz quando FrontEnd/.env não existir.
load_dotenv(LOCAL_ENV if LOCAL_ENV.exists() else ROOT_ENV)

DATA_DIR = Path(os.getenv("SUPADIAG_DATA_DIR", "data")).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = FRONTEND_DIR / DATA_DIR
os.environ["SUPADIAG_DATA_DIR"] = str(DATA_DIR)


class FrontendSettings:
    """Configurações para o FrontEnd Streamlit."""

    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_KEY: str = (
        os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )

    PAGE_TITLE: str = "Network analysis"
    PAGE_ICON: str = "📡"
    LAYOUT: str = "wide"
    DATA_DIR: Path = DATA_DIR

    MAX_MEASUREMENTS: int = 500
    DEFAULT_HOURS: int = 24

    @classmethod
    def validate(cls) -> bool:
        parsed_url = urlparse(cls.SUPABASE_URL)
        return bool(
            parsed_url.scheme == "https"
            and parsed_url.hostname
            and cls.SUPABASE_KEY
            and not cls.SUPABASE_KEY.startswith("sb_publishable_")
        )

    @classmethod
    def validation_error(cls) -> str | None:
        if not cls.SUPABASE_URL:
            return "SUPABASE_URL não está configurada em FrontEnd/.env."
        parsed_url = urlparse(cls.SUPABASE_URL)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            return "SUPABASE_URL inválida. Use https://<project-ref>.supabase.co."
        if not cls.SUPABASE_KEY:
            return "Configure SUPABASE_SECRET_KEY em FrontEnd/.env."
        if cls.SUPABASE_KEY.startswith("sb_publishable_"):
            return "A chave configurada é publishable. Use SUPABASE_SECRET_KEY com uma chave sb_secret_ ou service_role."
        return None


settings = FrontendSettings()
