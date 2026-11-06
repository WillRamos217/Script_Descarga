import os
import sys
from pathlib import Path
from typing import List

# Asegurar salida UTF-8 en terminales de Windows (PowerShell / CMD)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Directorios del proyecto
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def _cargar_env_manual(ruta_env: Path) -> None:
    """Carga variables desde .env sin depender exclusivamente de librerías externas."""
    if not ruta_env.exists():
        return
    with open(ruta_env, "r", encoding="utf-8-sig") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            if clave and clave not in os.environ:
                os.environ[clave] = valor


try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=ENV_FILE, override=True)
except ImportError:
    _cargar_env_manual(ENV_FILE)


def _resolver_directorio_descargas() -> Path:
    """
    Obtiene la carpeta de descargas desde la variable DOWNLOAD_DIR en .env.
    Si está vacía o no se define, usa por defecto ./descargas dentro del proyecto.
    """
    valor_env = os.getenv("DOWNLOAD_DIR", "").strip().strip('"').strip("'")
    if not valor_env or valor_env in {"./descargas", ".\\descargas", "descargas"}:
        return BASE_DIR / "descargas"

    ruta_personalizada = Path(valor_env).expanduser()
    if not ruta_personalizada.is_absolute():
        return (BASE_DIR / ruta_personalizada).resolve()
    return ruta_personalizada


def _parsear_lista_env(nombre_var: str) -> List[str]:
    """Convierte una variable separada por comas en .env en una lista limpia."""
    valor = os.getenv(nombre_var, "").strip()
    if not valor:
        return []
    return [item.strip() for item in valor.split(",") if item.strip()]


# ==============================================================================
# 1. CREDENCIALES, URL Y RUTA DE DESCARGA DESDE EL ARCHIVO .env
# ==============================================================================
APPIAN_USERNAME = os.getenv("APPIAN_USERNAME", "").strip()
APPIAN_PASSWORD = os.getenv("APPIAN_PASSWORD", "").strip()
APPIAN_FOLDER_URL = os.getenv(
    "APPIAN_FOLDER_URL",
    "https://pgn-dev.appiancloud.com/suite/design/docFolder/j_wE_8A5lGI7_Uv1qEbNvkJRwKQ",
).strip()
APPIAN_URL = APPIAN_FOLDER_URL

# Carpeta donde se guardarán las descargas (configurable desde DOWNLOAD_DIR en .env)
DOWNLOAD_DIR = _resolver_directorio_descargas()

# ==============================================================================
# 2. FILTROS DE LA TABLA DE APPIAN DESIGNER DESDE EL ARCHIVO .env
# ==============================================================================
FILTER_SEARCH_TEXT = os.getenv("FILTER_SEARCH_TEXT", "").strip()
FILTER_OBJECT_TYPES = _parsear_lista_env("FILTER_OBJECT_TYPES")
FILTER_MODIFIED_BY = _parsear_lista_env("FILTER_MODIFIED_BY")
FILTER_DATE_FROM = os.getenv("FILTER_DATE_FROM", "").strip()
FILTER_DATE_TO = os.getenv("FILTER_DATE_TO", "").strip()

# ==============================================================================
# 3. DIRECTORIOS Y ARCHIVOS DE REPORTE
# ==============================================================================
REPORTS_DIR = BASE_DIR / "reportes"
BROWSER_PROFILE_DIR = BASE_DIR / "sesion_navegador"

PROGRESS_FILE = REPORTS_DIR / "estado_progreso.json"
DOWNLOAD_LOG_CSV = REPORTS_DIR / "registro_descargas.csv"
VERIFICATION_REPORT_CSV = REPORTS_DIR / "reporte_verificacion.csv"
ZIP_DETAIL_CSV = REPORTS_DIR / "detalle_archivos_en_zips.csv"
ZIP_SUMMARY_TXT = REPORTS_DIR / "resumen_tipos_descargados.txt"

# Configuración de tiempos y reintentos
EXPECTED_TOTAL_FILES = 1200
DELAY_BETWEEN_DOWNLOADS_SEC = 0.8
DELAY_AFTER_PAGE_CHANGE_SEC = 2.5
DOWNLOAD_TIMEOUT_MS = 60000
PAGE_NAVIGATION_TIMEOUT_MS = 45000
MAX_RETRIES_PER_FILE = 3
SKIP_EXISTING_VALID_FILES = True

# Extensiones temporales que indican una descarga incompleta o interrumpida
TEMP_EXTENSIONS = {".crdownload", ".part", ".tmp", ".download"}
