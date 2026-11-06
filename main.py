import argparse
from pathlib import Path

from src import config
from src.downloader import iniciar_descarga
from src.verifier import auditar_carpeta_descargas


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automatización de descarga, verificación y eliminación opcional de documentos en Appian Designer."
    )
    parser.add_argument(
        "--solo-verificar",
        action="store_true",
        help="Ejecuta únicamente la comprobación e informe de los archivos ZIP ya presentes en la carpeta de descargas sin abrir el navegador.",
    )
    parser.add_argument(
        "--carpeta",
        type=Path,
        default=config.DOWNLOAD_DIR,
        help="Ruta a la carpeta de descargas a verificar (por defecto: la configurada en .env).",
    )
    args = parser.parse_args()

    if args.solo_verificar:
        auditar_carpeta_descargas(directorio_descargas=args.carpeta)
    else:
        iniciar_descarga()


if __name__ == "__main__":
    main()
