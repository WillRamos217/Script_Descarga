import subprocess
import sys
from pathlib import Path

import config


def iniciar_grabador() -> None:
    """
    Ejecuta `playwright codegen` guardando automáticamente el código Python
    de todo lo que hagas en el navegador dentro del archivo `grabacion_appian.py`.
    """
    archivo_salida = config.BASE_DIR / "grabacion_appian.py"
    playwright_exe = config.BASE_DIR / ".venv" / "Scripts" / "playwright.exe"

    url_inicial = (
        config.APPIAN_URL
        if config.APPIAN_URL and "tu-entorno" not in config.APPIAN_URL
        else "about:blank"
    )

    print("\n" + "=" * 75)
    print("🎥 GRABADOR DE ACCIONES DE PLAYWRIGHT (CODEGEN)")
    print("=" * 75)
    print("Se abrirán dos ventanas: el Navegador y el Inspector de Playwright.")
    print("\n👉 ¿Qué debes hacer para que quede perfecto?")
    print("   1. Inicia sesión en Appian y entra a la carpeta donde están los 1,200 archivos.")
    print("   2. Descarga el PRIMER archivo (tal como lo haces normalmente).")
    print("   3. Descarga el SEGUNDO archivo (para que veamos cómo cambia de una fila a otra).")
    print("   4. Haz clic una vez en el botón de 'Siguiente página' (Next) de la tabla.")
    print("   5. Cierra la ventana del navegador.")
    print(f"\n💾 Todo el código quedará guardado automáticamente en: {archivo_salida}")
    print("=" * 75 + "\n")

    comando = [
        str(playwright_exe),
        "codegen",
        "--target",
        "python",
        "-o",
        str(archivo_salida),
        url_inicial,
    ]

    subprocess.run(comando, check=False)

    if archivo_salida.exists():
        print(f"\n✅ ¡Grabación guardada con éxito en: {archivo_salida}!")
        print("Avísame en el chat que ya terminaste de grabar para convertir esos pasos exactos en el bucle de los 1,200 archivos.")
    else:
        print("\n⚠️ No se generó el archivo de grabación.")


if __name__ == "__main__":
    iniciar_grabador()
