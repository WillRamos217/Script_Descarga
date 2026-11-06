import argparse
import csv
import hashlib
import io
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Permitir ejecución tanto desde main.py como directamente con python src/verifier.py
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config

ARCHIVOS_IGNORADOS_SISTEMA = {".gitkeep", "desktop.ini", "thumbs.db", ".ds_store"}


def es_archivo_sistema_ignorado(ruta_archivo: Path) -> bool:
    """Ignora archivos de control como .gitkeep o desktop.ini dentro de la carpeta de descargas."""
    return (
        ruta_archivo.name.lower() in ARCHIVOS_IGNORADOS_SISTEMA
        or ruta_archivo.name.startswith(".test_permisos_")
    )


def calcular_sha256(ruta_archivo: Path) -> str:
    """Calcula el hash SHA-256 de un archivo."""
    sha256 = hashlib.sha256()
    try:
        with open(ruta_archivo, "rb") as f:
            for bloque in iter(lambda: f.read(65536), b""):
                sha256.update(bloque)
        return sha256.hexdigest()
    except OSError:
        return ""


def es_html_sesion_expirada(ruta_archivo: Path) -> bool:
    """Detecta si un archivo descargado es por error una página HTML de login de Appian."""
    if ruta_archivo.suffix.lower() in {".html", ".htm"}:
        return False
    try:
        with open(ruta_archivo, "rb") as f:
            cabecera = f.read(512).lstrip().lower()
            if cabecera.startswith(b"<!doctype html") or cabecera.startswith(b"<html"):
                if b"appian" in cabecera or b"login" in cabecera or b"sign in" in cabecera:
                    return True
    except OSError:
        pass
    return False


def detectar_tipo_documento(nombre_archivo: str, primeros_bytes: bytes = b"") -> str:
    """
    Identifica de qué tipo es un archivo (PDF, Word, Excel, Imagen, etc.)
    usando su extensión o, si no tiene extensión visible, su firma de bytes (magic bytes).
    """
    ext = Path(nombre_archivo).suffix.lower()

    mapa_extensiones = {
        ".pdf": "PDF (.pdf)",
        ".docx": "Word (.docx)",
        ".doc": "Word (.doc)",
        ".docm": "Word con macros (.docm)",
        ".rtf": "Word / RTF (.rtf)",
        ".xlsx": "Excel (.xlsx)",
        ".xls": "Excel (.xls)",
        ".xlsm": "Excel con macros (.xlsm)",
        ".csv": "CSV (.csv)",
        ".pptx": "PowerPoint (.pptx)",
        ".ppt": "PowerPoint (.ppt)",
        ".png": "Imagen (.png)",
        ".jpg": "Imagen (.jpg)",
        ".jpeg": "Imagen (.jpeg)",
        ".gif": "Imagen (.gif)",
        ".tif": "Imagen (.tif)",
        ".tiff": "Imagen (.tiff)",
        ".bmp": "Imagen (.bmp)",
        ".txt": "Texto (.txt)",
        ".xml": "XML (.xml)",
        ".json": "JSON (.json)",
        ".html": "HTML (.html)",
        ".htm": "HTML (.htm)",
        ".msg": "Correo Outlook (.msg)",
        ".eml": "Correo (.eml)",
        ".zip": "Archivo comprimido (.zip)",
        ".rar": "Archivo comprimido (.rar)",
        ".7z": "Archivo comprimido (.7z)",
    }

    if ext in mapa_extensiones:
        return mapa_extensiones[ext]

    if primeros_bytes:
        if primeros_bytes.startswith(b"%PDF"):
            return "PDF (.pdf)"
        if primeros_bytes.startswith(b"\x89PNG"):
            return "Imagen (.png)"
        if primeros_bytes.startswith(b"\xff\xd8\xff"):
            return "Imagen (.jpg)"
        if primeros_bytes.startswith(b"GIF8"):
            return "Imagen (.gif)"
        if primeros_bytes.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(primeros_bytes), "r") as sub_zf:
                    nombres_sub = sub_zf.namelist()
                    if any(n.startswith("word/") for n in nombres_sub):
                        return "Word (.docx)"
                    if any(n.startswith("xl/") for n in nombres_sub):
                        return "Excel (.xlsx)"
                    if any(n.startswith("ppt/") for n in nombres_sub):
                        return "PowerPoint (.pptx)"
            except Exception:
                if b"word/" in primeros_bytes:
                    return "Word (.docx)"
                if b"xl/" in primeros_bytes:
                    return "Excel (.xlsx)"
                if b"ppt/" in primeros_bytes:
                    return "PowerPoint (.pptx)"
            return "Documento Office / ZIP"
        if primeros_bytes.startswith(b"\xd0\xcf\x11\xe0"):
            return "Documento Office antiguo (.doc/.xls)"

    if ext:
        return f"Otro ({ext})"
    return "Sin extensión definida"


def validar_archivo_individual(ruta_archivo: Path) -> Tuple[bool, str, int]:
    """
    Valida que un archivo descargado:
      1. Exista físicamente en el disco.
      2. No tenga extensión temporal (.crdownload, .part, .tmp).
      3. Tenga un tamaño estrictamente mayor a 0 bytes.
      4. No sea una página HTML de sesión expirada disfrazada.
    """
    if not ruta_archivo.exists() or not ruta_archivo.is_file():
        return False, "ERROR_NO_EXISTE", 0

    if ruta_archivo.suffix.lower() in config.TEMP_EXTENSIONS:
        return False, "ERROR_DESCARGA_INCOMPLETA_TEMP", ruta_archivo.stat().st_size

    tamano = ruta_archivo.stat().st_size
    if tamano <= 0:
        return False, "ERROR_ARCHIVO_VACIO_0_BYTES", 0

    if es_html_sesion_expirada(ruta_archivo):
        return False, "ERROR_SESION_EXPIRADA_HTML", tamano

    return True, "OK", tamano


def diagnosticar_estado_previo_carpeta(
    directorio_descargas: Path = config.DOWNLOAD_DIR,
) -> Dict[str, Any]:
    """
    Verifica antes de iniciar las descargas:
      1. Si la carpeta destino en disco local es accesible y tiene permisos de escritura.
      2. Si existen archivos parciales/incompletos (.crdownload, .part, 0 bytes o ZIPs corruptos)
         de una ejecución anterior interrumpida.
      3. Qué documentos ya habían sido descargados previamente en esa carpeta para detectar
         duplicados o descargas parciales previas.
    """
    try:
        directorio_descargas.mkdir(parents=True, exist_ok=True)
        archivo_prueba = directorio_descargas / ".test_permisos_escritura.tmp"
        archivo_prueba.write_text("ok", encoding="utf-8")
        archivo_prueba.unlink(missing_ok=True)
    except Exception as e:
        raise RuntimeError(
            f"❌ ERROR DE DISCO LOCAL: No se puede acceder o escribir en la carpeta de descargas "
            f"configurada en .env ('{directorio_descargas}'). Detalle: {e}"
        ) from e

    archivos_existentes = sorted(
        [
            p
            for p in directorio_descargas.iterdir()
            if p.is_file() and not es_archivo_sistema_ignorado(p)
        ],
        key=lambda x: x.name.lower(),
    )

    archivos_incompletos_previos: List[str] = []
    paquetes_previos: Set[str] = set()
    documentos_internos_previos: Dict[Tuple[str, int, int], str] = {}

    for archivo in archivos_existentes:
        es_valido, estado, _ = validar_archivo_individual(archivo)
        if not es_valido:
            archivos_incompletos_previos.append(f"{archivo.name} ({estado})")
            continue

        if zipfile.is_zipfile(archivo):
            try:
                with zipfile.ZipFile(archivo, "r") as zf:
                    if zf.testzip() is not None:
                        archivos_incompletos_previos.append(f"{archivo.name} (ERROR_ZIP_CORRUPTO)")
                        continue
                    paquetes_previos.add(archivo.name)
                    for info in zf.infolist():
                        if not info.is_dir():
                            nombre_doc = (Path(info.filename).name or info.filename).lower()
                            huella = (nombre_doc, info.file_size, info.CRC)
                            documentos_internos_previos[huella] = archivo.name
            except zipfile.BadZipFile:
                archivos_incompletos_previos.append(f"{archivo.name} (ERROR_ZIP_INCOMPLETO)")
        else:
            paquetes_previos.add(archivo.name)
            huella = (archivo.name.lower(), archivo.stat().st_size, 0)
            documentos_internos_previos[huella] = archivo.name

    if archivos_incompletos_previos:
        print("\n" + "!" * 72)
        print("⚠️  ALERTA: SE DETECTARON DESCARGAS PARCIALES O DAÑADAS DE UNA SESIÓN ANTERIOR")
        print("!" * 72)
        print(f"En la carpeta '{directorio_descargas}' hay {len(archivos_incompletos_previos)} archivo(s) incompletos:")
        for item in archivos_incompletos_previos[:10]:
            print(f"   • {item}")
        if len(archivos_incompletos_previos) > 10:
            print(f"   • ... y {len(archivos_incompletos_previos) - 10} más.")
        print("Estos archivos incompletos serán reemplazados o reportados al finalizar.")
        print("!" * 72)

    if paquetes_previos:
        print("\n" + "-" * 72)
        print(
            f"ℹ️  NOTA DE ARCHIVOS PREVIOS: La carpeta '{directorio_descargas}' ya contiene "
            f"{len(paquetes_previos)} paquete(s) válido(s) ({len(documentos_internos_previos)} documentos internos)."
        )
        print("   El script te avisará en cada descarga si hay documentos duplicados o ya descargados antes.")
        print("-" * 72)

    return {
        "incompletos_previos": archivos_incompletos_previos,
        "paquetes_previos": paquetes_previos,
        "documentos_internos_previos": documentos_internos_previos,
    }


def verificar_y_analizar_descarga(
    ruta_archivo: Path,
    numero_pagina: Optional[int] = None,
    mostrar_en_consola: bool = True,
    historial_documentos: Optional[Dict[Tuple[str, int, int], str]] = None,
    ya_existia_paquete_en_disco: bool = False,
) -> Dict[str, Any]:
    """
    Se ejecuta inmediatamente después de cada descarga.
    Comprueba que el archivo descargado exista y sea > 0 bytes, inspecciona todos los
    documentos dentro del .zip, clasifica sus tipos (Word, PDF, etc.) y alerta si hay
    documentos duplicados o partes que ya habían sido descargadas anteriormente.
    """
    es_valido, estado, tamano_bytes = validar_archivo_individual(ruta_archivo)

    resultado: Dict[str, Any] = {
        "pagina": numero_pagina,
        "nombre_archivo": ruta_archivo.name,
        "ruta": str(ruta_archivo),
        "es_valido": es_valido,
        "estado": estado,
        "tamano_bytes": tamano_bytes,
        "es_zip": False,
        "total_archivos_internos": 0,
        "internos_validos": 0,
        "internos_vacios": 0,
        "duplicados_previos": [],
        "duplicados_mismo_nombre_en_zip": [],
        "conteo_tipos": Counter(),
        "archivos_internos": [],
    }

    if not es_valido:
        if mostrar_en_consola:
            etiqueta_pag = f" (Página {numero_pagina})" if numero_pagina is not None else ""
            print(f"\n❌ ERROR EN ARCHIVO DESCARGADO{etiqueta_pag}: '{ruta_archivo.name}'")
            if estado == "ERROR_DESCARGA_INCOMPLETA_TEMP":
                print("   Motivo: La descarga quedó incompleta (archivo temporal .crdownload/.part).")
            elif estado == "ERROR_ARCHIVO_VACIO_0_BYTES":
                print("   Motivo: El archivo se descargó vacío (0 bytes).")
            elif estado == "ERROR_SESION_EXPIRADA_HTML":
                print("   Motivo: La sesión de Appian expiró y se descargó una página HTML en lugar del documento.")
            else:
                print(f"   Motivo: {estado}")
        return resultado

    if zipfile.is_zipfile(ruta_archivo):
        resultado["es_zip"] = True
        try:
            with zipfile.ZipFile(ruta_archivo, "r") as zf:
                archivo_corrupto = zf.testzip()
                if archivo_corrupto is not None:
                    resultado["es_valido"] = False
                    resultado["estado"] = f"ERROR_ZIP_CORRUPTO_EN_{archivo_corrupto}"

                entradas = [info for info in zf.infolist() if not info.is_dir()]
                resultado["total_archivos_internos"] = len(entradas)

                conteo_nombres_internos: Counter = Counter()

                for info in entradas:
                    nombre_interno = Path(info.filename).name or info.filename
                    tamano_interno = info.file_size
                    conteo_nombres_internos[nombre_interno] += 1

                    primeros_bytes = b""
                    if tamano_interno > 0:
                        try:
                            with zf.open(info) as f_int:
                                primeros_bytes = f_int.read(2048)
                        except Exception:
                            pass

                    tipo_doc = detectar_tipo_documento(nombre_interno, primeros_bytes)
                    resultado["conteo_tipos"][tipo_doc] += 1

                    interno_ok = tamano_interno > 0
                    if interno_ok:
                        resultado["internos_validos"] += 1
                    else:
                        resultado["internos_vacios"] += 1

                    huella = (nombre_interno.lower(), tamano_interno, info.CRC)
                    origen_previo = ""
                    if historial_documentos is not None:
                        if huella in historial_documentos and historial_documentos[huella] != ruta_archivo.name:
                            origen_previo = historial_documentos[huella]
                            resultado["duplicados_previos"].append((nombre_interno, origen_previo))
                        else:
                            historial_documentos[huella] = ruta_archivo.name

                    resultado["archivos_internos"].append(
                        {
                            "archivo_zip": ruta_archivo.name,
                            "pagina": str(numero_pagina or "-"),
                            "nombre_documento": nombre_interno,
                            "tipo_documento": tipo_doc,
                            "tamano_bytes": tamano_interno,
                            "tamano_kb": f"{tamano_interno / 1024:.2f}",
                            "estado": (
                                f"DUPLICADO (ya en {origen_previo})"
                                if origen_previo
                                else ("OK (>0 bytes)" if interno_ok else "VACIO (0 bytes)")
                            ),
                        }
                    )

                resultado["duplicados_mismo_nombre_en_zip"] = [
                    f"{nom} (x{cant})" for nom, cant in conteo_nombres_internos.items() if cant > 1
                ]

        except zipfile.BadZipFile:
            resultado["es_valido"] = False
            resultado["estado"] = "ERROR_ZIP_INVALIDO"
    else:
        primeros_bytes = b""
        try:
            with open(ruta_archivo, "rb") as f_ind:
                primeros_bytes = f_ind.read(2048)
        except OSError:
            pass
        tipo_doc = detectar_tipo_documento(ruta_archivo.name, primeros_bytes)
        resultado["total_archivos_internos"] = 1
        resultado["internos_validos"] = 1
        resultado["conteo_tipos"][tipo_doc] += 1

        huella = (ruta_archivo.name.lower(), tamano_bytes, 0)
        origen_previo = ""
        if historial_documentos is not None:
            if huella in historial_documentos and historial_documentos[huella] != ruta_archivo.name:
                origen_previo = historial_documentos[huella]
                resultado["duplicados_previos"].append((ruta_archivo.name, origen_previo))
            else:
                historial_documentos[huella] = ruta_archivo.name

        resultado["archivos_internos"].append(
            {
                "archivo_zip": ruta_archivo.name,
                "pagina": str(numero_pagina or "-"),
                "nombre_documento": ruta_archivo.name,
                "tipo_documento": tipo_doc,
                "tamano_bytes": tamano_bytes,
                "tamano_kb": f"{tamano_bytes / 1024:.2f}",
                "estado": f"DUPLICADO (ya en {origen_previo})" if origen_previo else "OK (>0 bytes)",
            }
        )

    if mostrar_en_consola:
        titulo_pag = f" - PÁGINA {numero_pagina}" if numero_pagina is not None else ""
        tamano_kb = tamano_bytes / 1024
        print("   " + "-" * 68)
        print(f"   📦 COMPROBACIÓN DE DESCARGA{titulo_pag}")
        print("   " + "-" * 68)
        print(f"   📄 Archivo guardado       : {ruta_archivo.name}")
        print(f"   💾 Tamaño en disco        : {tamano_kb:,.2f} KB ({tamano_bytes:,} bytes)")
        print(
            f"   ✅ Estado del archivo     : "
            f"{'CORRECTO' if resultado['es_valido'] else resultado['estado']}"
        )

        if ya_existia_paquete_en_disco:
            print(
                "   ⚠️  AVISO DE ARCHIVO PREVIO: Ya existía una descarga previa de esta página "
                "en la carpeta destino y fue actualizada/verificada."
            )

        if resultado["es_zip"]:
            print(
                f"   📂 Archivos dentro del ZIP: {resultado['total_archivos_internos']} documento(s) "
                f"({resultado['internos_validos']} válidos >0B | {resultado['internos_vacios']} vacíos)"
            )
            print("   📊 Tipos de archivos descargados en este ZIP:")
            for tipo, cantidad in resultado["conteo_tipos"].most_common():
                print(f"      • {tipo:<28}: {cantidad} archivo(s)")
        else:
            tipo_unico = next(iter(resultado["conteo_tipos"].keys()), "Documento")
            print(f"   📊 Tipo de documento      : {tipo_unico}")

        cant_dup = len(resultado["duplicados_previos"])
        total_int = resultado["total_archivos_internos"]
        if cant_dup > 0:
            if cant_dup == total_int:
                print(
                    f"   ⚠️  ALERTA DE DUPLICADOS: Los {cant_dup} documento(s) de este paquete "
                    "YA HABÍAN SIDO DESCARGADOS anteriormente en otra página o ejecución previa."
                )
            else:
                nuevos = total_int - cant_dup
                print(
                    f"   ⚠️  ALERTA DE DESCARGA PARCIAL PREVIA: {cant_dup} de los {total_int} documento(s) "
                    f"de este ZIP ya se habían descargado antes ({nuevos} son nuevos)."
                )
            ejemplos = ", ".join(
                f"'{doc}' (en {orig})" for doc, orig in resultado["duplicados_previos"][:3]
            )
            print(f"      Ejemplos detectados: {ejemplos}")

        if resultado["duplicados_mismo_nombre_en_zip"]:
            muestra_nom = ", ".join(resultado["duplicados_mismo_nombre_en_zip"][:3])
            print(f"   ℹ️  Nombres repetidos dentro del mismo ZIP: {muestra_nom}")

        print("   " + "-" * 68)

    return resultado


def auditar_carpeta_descargas(
    directorio_descargas: Path = config.DOWNLOAD_DIR,
    ruta_reporte: Path = config.VERIFICATION_REPORT_CSV,
    errores_ejecucion: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Recorre todos los archivos descargados en la carpeta configurada, comprueba cada uno
    y sus contenidos ZIP, detecta duplicados entre archivos y genera el informe final.
    """
    directorio_descargas.mkdir(parents=True, exist_ok=True)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    archivos_en_disco = sorted(
        [
            p
            for p in directorio_descargas.iterdir()
            if p.is_file() and not es_archivo_sistema_ignorado(p)
        ],
        key=lambda x: x.stat().st_mtime,
    )

    filas_csv_zips: List[Dict[str, str]] = []
    filas_csv_detalle_internos: List[Dict[str, Any]] = []

    zips_validos = 0
    zips_con_error = 0
    bytes_totales_disco = 0

    total_documentos_en_zips = 0
    total_documentos_validos = 0
    total_documentos_vacios = 0
    total_documentos_duplicados = 0
    conteo_global_tipos: Counter = Counter()
    historial_auditoria: Dict[Tuple[str, int, int], str] = {}

    for idx, archivo in enumerate(archivos_en_disco, start=1):
        info_analisis = verificar_y_analizar_descarga(
            archivo,
            numero_pagina=idx,
            mostrar_en_consola=False,
            historial_documentos=historial_auditoria,
        )
        fecha_mod = datetime.fromtimestamp(archivo.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        tamano = info_analisis["tamano_bytes"]

        if info_analisis["es_valido"]:
            zips_validos += 1
            bytes_totales_disco += tamano
        else:
            zips_con_error += 1

        total_documentos_en_zips += info_analisis["total_archivos_internos"]
        total_documentos_validos += info_analisis["internos_validos"]
        total_documentos_vacios += info_analisis["internos_vacios"]
        total_documentos_duplicados += len(info_analisis["duplicados_previos"])
        conteo_global_tipos.update(info_analisis["conteo_tipos"])
        filas_csv_detalle_internos.extend(info_analisis["archivos_internos"])

        resumen_tipos_str = "; ".join(
            f"{t}: {c}" for t, c in info_analisis["conteo_tipos"].most_common()
        )

        filas_csv_zips.append(
            {
                "indice": str(idx),
                "nombre_archivo_descargado": archivo.name,
                "tamano_bytes": str(tamano),
                "tamano_kb": f"{tamano / 1024:.2f}",
                "estado": info_analisis["estado"],
                "es_valido": "SI" if info_analisis["es_valido"] else "NO",
                "archivos_dentro_del_zip": str(info_analisis["total_archivos_internos"]),
                "duplicados_detectados": str(len(info_analisis["duplicados_previos"])),
                "desglose_tipos": resumen_tipos_str,
                "fecha_descarga": fecha_mod,
            }
        )

    columnas_zips = [
        "indice",
        "nombre_archivo_descargado",
        "tamano_bytes",
        "tamano_kb",
        "estado",
        "es_valido",
        "archivos_dentro_del_zip",
        "duplicados_detectados",
        "desglose_tipos",
        "fecha_descarga",
    ]
    with open(ruta_reporte, "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=columnas_zips)
        writer.writeheader()
        writer.writerows(filas_csv_zips)

    columnas_internos = [
        "archivo_zip",
        "pagina",
        "nombre_documento",
        "tipo_documento",
        "tamano_bytes",
        "tamano_kb",
        "estado",
    ]
    with open(config.ZIP_DETAIL_CSV, "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=columnas_internos)
        writer.writeheader()
        writer.writerows(filas_csv_detalle_internos)

    mb_totales = bytes_totales_disco / (1024 * 1024)
    documentos_unicos = max(0, total_documentos_en_zips - total_documentos_duplicados)
    lineas_informe = [
        "=" * 74,
        "📊 INFORME FINAL DE DESCARGAS Y CONTENIDO DE ARCHIVOS ZIP",
        "=" * 74,
        f"📂 Carpeta de descargas en disco    : {directorio_descargas}",
        f"📦 Total paquetes/ZIPs en carpeta   : {len(archivos_en_disco)} ({zips_validos} correctos, {zips_con_error} con error)",
        f"📄 Total documentos dentro de ZIPs  : {total_documentos_en_zips}",
        f"   ├─ Documentos válidos (> 0 bytes): {total_documentos_validos}",
        f"   ├─ Documentos únicos             : {documentos_unicos}",
        f"   ├─ Documentos duplicados/previos : {total_documentos_duplicados}",
        f"   └─ Documentos vacíos (0 bytes)   : {total_documentos_vacios}",
        f"💾 Peso total en disco              : {mb_totales:.2f} MB ({bytes_totales_disco:,} bytes)",
        "-" * 74,
        "📑 DESGLOSE POR TIPO DE DOCUMENTO (DENTRO DE LOS ZIPS):",
    ]

    if conteo_global_tipos:
        for tipo, cantidad in conteo_global_tipos.most_common():
            porcentaje = (
                (cantidad / total_documentos_en_zips) * 100
                if total_documentos_en_zips > 0
                else 0.0
            )
            lineas_informe.append(f"   • {tipo:<32}: {cantidad:>5} archivo(s) ({porcentaje:5.1f}%)")
    else:
        lineas_informe.append("   (No se encontraron documentos para clasificar)")

    if errores_ejecucion:
        lineas_informe.append("-" * 74)
        lineas_informe.append("⚠️  INCIDENCIAS / ERRORES REGISTRADOS DURANTE LA EJECUCIÓN:")
        for err in errores_ejecucion:
            lineas_informe.append(f"   • {err}")

    lineas_informe.extend(
        [
            "-" * 74,
            f"📋 Reporte de ZIPs guardado en      : {ruta_reporte}",
            f"📋 Detalle de documentos en ZIPs    : {config.ZIP_DETAIL_CSV}",
            f"📋 Resumen ejecutivo en texto       : {config.ZIP_SUMMARY_TXT}",
            "=" * 74,
        ]
    )

    texto_informe = "\n".join(lineas_informe)
    print("\n" + texto_informe)

    with open(config.ZIP_SUMMARY_TXT, "w", encoding="utf-8") as f_txt:
        f_txt.write(texto_informe + "\n")

    return {
        "total_zips": len(archivos_en_disco),
        "zips_validos": zips_validos,
        "total_documentos_en_zips": total_documentos_en_zips,
        "documentos_validos": total_documentos_validos,
        "documentos_duplicados": total_documentos_duplicados,
        "documentos_vacios": total_documentos_vacios,
        "conteo_tipos": dict(conteo_global_tipos),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verifica los archivos ZIP descargados de Appian e informa cuántos documentos contienen y de qué tipos son."
    )
    parser.add_argument(
        "--carpeta",
        type=Path,
        default=config.DOWNLOAD_DIR,
        help="Ruta a la carpeta de descargas configurada en .env (por defecto: ./descargas)",
    )
    args = parser.parse_args()

    auditar_carpeta_descargas(directorio_descargas=args.carpeta)
