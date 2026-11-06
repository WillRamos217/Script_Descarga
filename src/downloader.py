import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from src import config
from src.verifier import (
    auditar_carpeta_descargas,
    diagnosticar_estado_previo_carpeta,
    verificar_y_analizar_descarga,
)

MESES_APPIAN = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def parsear_fecha_env(fecha_str: str, nombre_campo: str) -> Tuple[int, str, int]:
    """
    Convierte una fecha del .env (ej. '25/01/2026' o '2026-01-25') en (dia, nombre_mes_es, anio).
    """
    texto = fecha_str.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(texto, fmt)
            return dt.day, MESES_APPIAN[dt.month], dt.year
        except ValueError:
            continue
    raise ValueError(
        f"❌ Formato de fecha inválido en .env para {nombre_campo}='{fecha_str}'. "
        "Usa el formato DD/MM/YYYY (por ejemplo: 25/01/2026)."
    )


def seleccionar_fecha_en_calendario(page: Page, indice_calendario: int, fecha_str: str, etiqueta: str) -> None:
    """
    Selecciona dinámicamente cualquier fecha (DD/MM/YYYY) en el calendario Desde (0) o Hasta (1) de Appian.
    """
    dia, nombre_mes, anio = parsear_fecha_env(fecha_str, etiqueta)
    print(f"   📅 Filtro '{etiqueta}': seleccionando {dia:02d} de {nombre_mes} de {anio} ({fecha_str})...")

    page.get_by_test_id("DatePickerWidget-calendarButton").nth(indice_calendario).click()

    carets = page.locator(".DatePicker---dropdown_caret")
    carets.first.click()
    page.get_by_test_id("DatePicker-container").get_by_text(nombre_mes, exact=True).click()

    if carets.count() > 1:
        texto_contenedor = page.get_by_test_id("DatePicker-container").inner_text()
        if str(anio) not in texto_contenedor:
            carets.nth(1).click()
            opcion_anio = page.get_by_test_id("DatePicker-container").get_by_text(str(anio), exact=True)
            if opcion_anio.count() > 0:
                opcion_anio.first.click()

    # Seleccionar el botón del día sin importar qué día de la semana sea (ej. "Seleccione domingo, enero 25º")
    # Nota: En RegExp de JavaScript (Chromium), 'º' no es carácter de palabra (\w), por lo que no debe usarse \b tras 'º'.
    patron_boton_dia = re.compile(rf"\b{nombre_mes}\s+{dia}º", re.IGNORECASE)
    boton_dia = page.get_by_role("button", name=patron_boton_dia)
    if boton_dia.count() > 0:
        boton_dia.first.click()
    else:
        page.get_by_test_id("DatePicker-container").get_by_role("button", name=str(dia), exact=True).first.click()
    page.wait_for_timeout(1000)


def aplicar_filtros_appian(page: Page) -> None:
    """
    Lee los filtros configurados en el archivo .env y los aplica en el panel izquierdo de Appian Designer:
      - FILTER_SEARCH_TEXT   : Buscador 'Nombre o descripción'
      - FILTER_OBJECT_TYPES  : Casillas 'TIPO DE OBJETO' (Documento, Carpeta de Documentos, Informe de Proceso)
      - FILTER_MODIFIED_BY   : Campo 'ÚLTIMA MODIFICACIÓN POR'
      - FILTER_DATE_FROM     : Fecha 'Desde' (DD/MM/YYYY)
      - FILTER_DATE_TO       : Fecha 'Hasta' (DD/MM/YYYY)
    """
    hay_algun_filtro = any(
        [
            config.FILTER_SEARCH_TEXT,
            config.FILTER_OBJECT_TYPES,
            config.FILTER_MODIFIED_BY,
            config.FILTER_DATE_FROM,
            config.FILTER_DATE_TO,
        ]
    )

    if not hay_algun_filtro:
        print("\nℹ️ No se configuraron filtros en .env. Se descargará la carpeta tal como aparece.")
        return

    print("\n🔍 Aplicando filtros configurados en .env...")

    if config.FILTER_SEARCH_TEXT:
        print(f"   🔤 Filtro 'Nombre o descripción': '{config.FILTER_SEARCH_TEXT}'")
        campo_busqueda = (
            page.get_by_placeholder("Nombre o descripción")
            .or_(page.get_by_role("textbox", name=re.compile("Nombre o descripción", re.I)))
            .first
        )
        campo_busqueda.click()
        campo_busqueda.fill(config.FILTER_SEARCH_TEXT)
        campo_busqueda.press("Enter")
        page.wait_for_timeout(1500)

    if config.FILTER_OBJECT_TYPES:
        for tipo_obj in config.FILTER_OBJECT_TYPES:
            print(f"   ☑️ Filtro 'TIPO DE OBJETO': marcando '{tipo_obj}'")
            checkbox_tipo = page.get_by_role("checkbox", name=tipo_obj, exact=True)
            if checkbox_tipo.count() > 0 and checkbox_tipo.first.is_visible():
                if not checkbox_tipo.first.is_checked():
                    checkbox_tipo.first.check(force=True)
            else:
                page.get_by_text(tipo_obj, exact=True).first.click()
            page.wait_for_timeout(1200)

    if config.FILTER_MODIFIED_BY:
        campo_usuario = page.get_by_placeholder(re.compile("Seleccione uno o más usuar", re.I)).first
        for usuario in config.FILTER_MODIFIED_BY:
            print(f"   👤 Filtro 'ÚLTIMA MODIFICACIÓN POR': '{usuario}'")
            campo_usuario.click()
            campo_usuario.fill(usuario)
            page.wait_for_timeout(1200)
            sugerencia = page.get_by_role("option").first
            if sugerencia.count() > 0 and sugerencia.is_visible():
                sugerencia.click()
            else:
                campo_usuario.press("Enter")
            page.wait_for_timeout(1200)

    if config.FILTER_DATE_FROM:
        seleccionar_fecha_en_calendario(page, 0, config.FILTER_DATE_FROM, "Desde (FILTER_DATE_FROM)")

    if config.FILTER_DATE_TO:
        seleccionar_fecha_en_calendario(page, 1, config.FILTER_DATE_TO, "Hasta (FILTER_DATE_TO)")

    encabezado_tabla = page.get_by_role("row", name="Nombre Descripción Tipo Tamañ").get_by_role("cell")
    if encabezado_tabla.count() > 0:
        encabezado_tabla.first.click()

    print("⏳ Esperando a que Appian actualice la tabla con los filtros aplicados...")
    page.wait_for_timeout(3500)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass


def explicar_error_red_o_timeout(error: Exception, etapa: str) -> str:
    """
    Traduce errores técnicos de Playwright o de red en mensajes claros en español
    para identificar rápidamente si fue un Timeout de internet, caída de red o cambio en la página.
    """
    texto = str(error)
    texto_lower = texto.lower()

    if isinstance(error, PlaywrightTimeoutError) or "timeout" in texto_lower:
        return (
            f"⏳ ERROR DE TIMEOUT (TIEMPO DE ESPERA AGOTADO) durante '{etapa}': "
            "La operación tardó demasiado en responder. Esto suele ocurrir porque la conexión "
            "a internet está lenta/inestable o el servidor de Appian tardó más de lo permitido "
            f"({config.DOWNLOAD_TIMEOUT_MS // 1000} segundos) en generar el paquete de descarga."
        )
    if (
        "err_internet_disconnected" in texto_lower
        or "err_network_changed" in texto_lower
        or "err_connection_timed_out" in texto_lower
        or "err_connection_reset" in texto_lower
        or "err_connection_closed" in texto_lower
        or "err_name_not_resolved" in texto_lower
    ):
        return (
            f"🌐 ERROR DE CONEXIÓN A INTERNET durante '{etapa}': "
            f"Se perdió la conexión de red con Appian ({texto.splitlines()[0]}). "
            "Verifica tu conexión a internet o VPN."
        )
    return f"❌ ERROR durante '{etapa}': {texto.splitlines()[0] if texto else repr(error)}"


def guardar_descarga_segura(download, ruta_preferida: Path, pagina: int) -> tuple[Path, bool, str]:
    """
    Guarda el archivo descargado en la ruta configurada en .env.
    Detecta si el archivo ya existía previamente o si no se puede sobrescribir por estar bloqueado/duplicado.
    """
    ya_existia = ruta_preferida.exists() and ruta_preferida.stat().st_size > 0
    mensaje_aviso = ""

    try:
        download.save_as(str(ruta_preferida))
        return ruta_preferida, ya_existia, mensaje_aviso
    except PermissionError:
        stem = ruta_preferida.stem
        suffix = ruta_preferida.suffix
        contador = 2
        while True:
            ruta_alternativa = ruta_preferida.parent / f"{stem}_copia_{contador}{suffix}"
            if not ruta_alternativa.exists():
                break
            contador += 1
        download.save_as(str(ruta_alternativa))
        mensaje_aviso = (
            f"⚠️ El archivo '{ruta_preferida.name}' ya existía en la carpeta y estaba abierto o bloqueado "
            f"por otro programa. Se guardó como '{ruta_alternativa.name}' para no perder la descarga."
        )
        return ruta_alternativa, True, mensaje_aviso
    except OSError as e:
        raise RuntimeError(
            f"❌ ERROR DE DISCO AL GUARDAR PÁGINA {pagina} en '{ruta_preferida}': "
            f"No se pudo escribir el archivo en el disco local (verifica espacio libre o permisos). Detalle: {e}"
        ) from e


def eliminar_documentos_seleccionados_appian(page: Page, pagina: int) -> None:
    """
    Elimina de la carpeta de Appian los documentos seleccionados en la página actual:
      1. Verifica que las filas sigan marcadas.
      2. Presiona el botón 'ELIMINAR' de la barra de herramientas superior.
      3. En la ventana emergente ('¿Eliminar X documentos?'), marca la casilla
         'Entiendo que esta acción no se puede deshacer'.
      4. Presiona el botón 'ELIMINAR' del cuadro de confirmación y espera a que la tabla se actualice.
    """
    print(f"   🗑️  [Página {pagina}] Eliminando de Appian los documentos ya descargados y comprobados...")

    selector_label = page.locator(
        '[id="53d75f33ea0598fc72884b78409780bd_headerCell_selection__0-label"], '
        '[id$="_headerCell_selection__0-label"]'
    ).first
    checkbox_todos = page.get_by_role("checkbox", name="Seleccionar todas las filas")

    if not checkbox_todos.is_checked():
        selector_label.click()
        checkbox_todos.check()
        page.wait_for_timeout(500)

    boton_eliminar_barra = page.get_by_role("button", name="Eliminar").first
    boton_eliminar_barra.click()
    page.wait_for_timeout(1000)

    casilla_confirmar = page.get_by_role(
        "checkbox", name="Entiendo que esta acción no se puede deshacer"
    )
    texto_confirmar = page.get_by_text("Entiendo que esta acción no se puede deshacer", exact=True)

    if casilla_confirmar.count() > 0:
        try:
            casilla_confirmar.first.check(force=True)
        except Exception:
            pass

    if casilla_confirmar.count() == 0 or not casilla_confirmar.first.is_checked():
        texto_confirmar.first.click()

    page.wait_for_timeout(600)

    boton_eliminar_modal = page.get_by_role("button", name="Eliminar").last
    boton_eliminar_modal.click()

    page.wait_for_timeout(3500)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    print(f"   ✅ [Página {pagina}] Documentos eliminados correctamente de la carpeta de Appian.")


def run(playwright: Playwright) -> None:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if not config.APPIAN_USERNAME or not config.APPIAN_PASSWORD or not config.APPIAN_FOLDER_URL:
        raise ValueError(
            "❌ CONFIGURACIÓN INCOMPLETA EN .env: "
            "Faltan APPIAN_USERNAME, APPIAN_PASSWORD o APPIAN_FOLDER_URL en el archivo .env"
        )

    print("=" * 74)
    print("🚀 INICIANDO DESCARGA AUTOMÁTICA DESDE APPIAN")
    print("=" * 74)
    print(f"👤 Usuario configurado       : {config.APPIAN_USERNAME}")
    print(f"🔗 Carpeta destino URL       : {config.APPIAN_FOLDER_URL}")
    print(f"📂 Carpeta local de descarga : {config.DOWNLOAD_DIR}")
    print(
        f"🗑️  Eliminar tras descargar   : "
        f"{'SÍ (ACTIVO)' if config.DELETE_AFTER_DOWNLOAD else 'NO (DESACTIVADO)'}"
    )
    print(f"🔎 Filtro texto              : {config.FILTER_SEARCH_TEXT or '(ninguno)'}")
    print(f"☑️ Filtro tipo de objeto     : {', '.join(config.FILTER_OBJECT_TYPES) or '(ninguno)'}")
    print(f"👥 Filtro modificado por     : {', '.join(config.FILTER_MODIFIED_BY) or '(ninguno)'}")
    print(f"📅 Filtro fecha Desde / Hasta: {config.FILTER_DATE_FROM or '-'} -> {config.FILTER_DATE_TO or '-'}")
    print("=" * 74)

    if config.DELETE_AFTER_DOWNLOAD:
        print("\n" + "!" * 74)
        print("⚠️  ADVERTENCIA DE SEGURIDAD: ELIMINACIÓN EN APPIAN ACTIVADA")
        print("!" * 74)
        print("La opción DELETE_AFTER_DOWNLOAD=true está activa en tu archivo .env.")
        print("Esto significa que DESPUÉS de descargar y comprobar cada página,")
        print("los archivos descargados SERÁN ELIMINADOS PERMANENTEMENTE de la carpeta en Appian:")
        print(f"   🔗 {config.APPIAN_FOLDER_URL}")
        print("!" * 74)
        confirmacion = input(
            "\n👉 ¿Estás de acuerdo en eliminar los archivos de Appian tras descargarlos?\n"
            "   Escribe 'Y' y presiona [ENTER] para continuar (cualquier otra tecla cancela): "
        ).strip()

        if confirmacion.upper() != "Y":
            print("\n🛑 Ejecución cancelada por el usuario. No se realizó ninguna descarga ni eliminación.")
            return
        print("\n✅ Confirmación recibida ('Y'). Iniciando proceso con eliminación posterior...")

    estado_previo = diagnosticar_estado_previo_carpeta(config.DOWNLOAD_DIR)
    historial_documentos = estado_previo["documentos_internos_previos"]
    errores_ejecucion: List[str] = []

    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.set_default_timeout(config.PAGE_NAVIGATION_TIMEOUT_MS)

    try:
        print("\n🌐 Conectando con Appian e iniciando sesión...")
        page.goto(config.APPIAN_FOLDER_URL, timeout=config.PAGE_NAVIGATION_TIMEOUT_MS)
        page.get_by_role("link", name="No").click()
        page.get_by_role("textbox", name="Nombre de usuario").fill(config.APPIAN_USERNAME)
        page.get_by_role("textbox", name="Contraseña").click()
        page.get_by_role("textbox", name="Contraseña").fill(config.APPIAN_PASSWORD)
        page.get_by_role("button", name="Iniciar sesión").click()

        aplicar_filtros_appian(page)

    except (PlaywrightTimeoutError, PlaywrightError, ValueError) as e:
        msg = explicar_error_red_o_timeout(e, "Inicio de sesión y aplicación de filtros en Appian")
        print("\n" + "!" * 74)
        print(msg)
        print("!" * 74)
        errores_ejecucion.append(msg)
        context.close()
        browser.close()
        return

    pagina = 1
    while True:
        print(f"\n🔄 Procesando página {pagina}...")
        descarga_exitosa = False

        for intento in range(1, config.MAX_RETRIES_PER_FILE + 1):
            try:
                selector_label = page.locator(
                    '[id="53d75f33ea0598fc72884b78409780bd_headerCell_selection__0-label"], '
                    '[id$="_headerCell_selection__0-label"]'
                ).first
                checkbox_todos = page.get_by_role("checkbox", name="Seleccionar todas las filas")

                if not checkbox_todos.is_checked():
                    selector_label.click()
                checkbox_todos.check()

                page.wait_for_timeout(800)
                if not checkbox_todos.is_checked():
                    print("   ℹ️ La tabla se refrescó; volviendo a marcar todas las filas...")
                    selector_label.click()
                    checkbox_todos.check()
                    page.wait_for_timeout(500)

                page.get_by_role("button", name="Más").click()
                with page.expect_download(timeout=config.DOWNLOAD_TIMEOUT_MS) as download_info:
                    opcion_descargar = (
                        page.get_by_role("menuitem", name="Descargar")
                        .or_(page.get_by_role("button", name="Descargar"))
                        .or_(page.get_by_text("Descargar", exact=True))
                        .last
                    )
                    opcion_descargar.click()
                download = download_info.value

                fallo_descarga = download.failure()
                if fallo_descarga:
                    raise RuntimeError(
                        f"La descarga se interrumpió a mitad de camino por un error de red: {fallo_descarga}"
                    )

                nombre_original = download.suggested_filename or f"descarga_pagina_{pagina}.zip"
                ruta_preferida = config.DOWNLOAD_DIR / f"pagina_{pagina:03d}_{nombre_original}"
                ruta_destino, ya_existia_paquete, aviso_guardado = guardar_descarga_segura(
                    download, ruta_preferida, pagina
                )

                if aviso_guardado:
                    print(f"   {aviso_guardado}")
                    errores_ejecucion.append(f"Página {pagina}: {aviso_guardado}")

                resultado_analisis = verificar_y_analizar_descarga(
                    ruta_archivo=ruta_destino,
                    numero_pagina=pagina,
                    mostrar_en_consola=True,
                    historial_documentos=historial_documentos,
                    ya_existia_paquete_en_disco=ya_existia_paquete,
                )

                if not resultado_analisis["es_valido"] or resultado_analisis["internos_vacios"] > 0:
                    raise RuntimeError(
                        f"El archivo descargado no pasó la verificación ({resultado_analisis['estado']}, "
                        f"vacíos: {resultado_analisis['internos_vacios']})."
                    )

                descarga_exitosa = True
                break

            except Exception as e:
                msg_error = explicar_error_red_o_timeout(
                    e, f"Descarga de la página {pagina} (Intento {intento}/{config.MAX_RETRIES_PER_FILE})"
                )
                print(f"\n   {msg_error}")
                if intento < config.MAX_RETRIES_PER_FILE:
                    print(f"   🔄 Reintentando descarga de la página {pagina} en 3 segundos...")
                    time.sleep(3)
                else:
                    errores_ejecucion.append(f"Página {pagina}: {msg_error}")

        if not descarga_exitosa:
            print(
                f"\n🛑 No se pudo completar la descarga de la página {pagina} tras "
                f"{config.MAX_RETRIES_PER_FILE} intentos. Se detiene el proceso para evitar pérdidas."
            )
            break

        if config.DELETE_AFTER_DOWNLOAD:
            primera_fila_antes = ""
            try:
                primera_fila_antes = page.locator("table tbody tr").first.inner_text(timeout=2000)
            except Exception:
                pass

            try:
                eliminar_documentos_seleccionados_appian(page, pagina)
            except Exception as e:
                msg_del = explicar_error_red_o_timeout(
                    e, f"Eliminación de documentos en Appian (Página {pagina})"
                )
                print(f"\n   {msg_del}")
                errores_ejecucion.append(msg_del)
                break

            checkbox_todos = page.get_by_role("checkbox", name="Seleccionar todas las filas")
            filas_con_checkbox = page.locator("table tbody tr input[type='checkbox']")
            if filas_con_checkbox.count() == 0 and not checkbox_todos.is_visible():
                print("\n🏁 Ya no quedan más documentos en la carpeta de Appian. Proceso finalizado.")
                break

            primera_fila_despues = ""
            try:
                primera_fila_despues = page.locator("table tbody tr").first.inner_text(timeout=2000)
            except Exception:
                pass

            if primera_fila_despues and primera_fila_despues != primera_fila_antes:
                pagina += 1
                continue

        boton_siguiente = page.get_by_role("button", name="Página siguiente")
        if (
            boton_siguiente.count() == 0
            or not boton_siguiente.is_visible()
            or not boton_siguiente.is_enabled()
            or boton_siguiente.get_attribute("aria-disabled") == "true"
        ):
            print("\n🏁 Ya no se ve (o está deshabilitado) el botón 'Página siguiente'. Proceso finalizado.")
            break

        try:
            boton_siguiente.click()
            page.wait_for_timeout(2000)
            pagina += 1
        except Exception as e:
            msg_pag = explicar_error_red_o_timeout(e, f"Cambio de página {pagina} a {pagina + 1}")
            print(f"\n{msg_pag}")
            errores_ejecucion.append(msg_pag)
            break

    context.close()
    browser.close()

    auditar_carpeta_descargas(errores_ejecucion=errores_ejecucion)


def iniciar_descarga() -> None:
    """Punto de entrada para ejecutar la automatización completa."""
    with sync_playwright() as playwright:
        run(playwright)


if __name__ == "__main__":
    iniciar_descarga()
