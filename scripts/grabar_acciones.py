import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config


def iniciar_grabador() -> None:
    """
    Ejecuta `playwright codegen` guardando automáticamente el código Python
    de las acciones grabadas en el navegador dentro de `scripts/grabacion_codegen.py`.
    """
    archivo_salida = config.BASE_DIR / "scripts" / "grabacion_codegen.py"

    url_inicial = (
        config.APPIAN_URL
        if config.APPIAN_URL and "tu-entorno" not in config.APPIAN_URL
        else "about:blank"
    )

    print("\n" + "=" * 75)
    print("🎥 GRABADOR DE ACCIONES DE PLAYWRIGHT (CODEGEN)")
    print("=" * 75)
    print(f"💾 El código grabado se guardará en: {archivo_salida}")
    print("=" * 75 + "\n")

    comando = [
        sys.executable,
        "-m",
        "playwright",
        "codegen",
        "--target",
        "python",
        "-o",
        str(archivo_salida),
        url_inicial,
    ]

    subprocess.run(comando, check=False)


if __name__ == "__main__":
    iniciar_grabador()
