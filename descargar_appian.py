import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import BrowserContext, Download, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

import config
from verificar_descargas import auditar_carpeta_descargas, validar_archivo_individual


def limpiar_nombre_archivo(nombre: str) -> str:
    """Elimina caracteres inválidos en Windows para nombres de archivo."""
    nombre_limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nombre).strip()
    return nombre_limpio or "documento_sin_nombre"


def cargar_progreso() -> Dict[str, Any]:
    """Carga el archivo JSON de progreso para poder reanudar ejecuciones interrumpidas."""
    if config.PROGRESS_FILE.exists():
        try:
            with open(config.PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"descargados": {}, "pagina_actual": 1}


def guardar_progreso(progreso: Dict[str, Any]) -> None:
    """Guarda el estado actual de descargas en disco."""
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progreso, f, indent=2, ensure_ascii=False)


def registrar_en_log_csv(fila_log: Dict[str, str]) -> None:
    """Agrega una línea al archivo CSV de registro de descargas en tiempo real."""
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    existe = config.DOWNLOAD_LOG_CSV.exists()
    columnas = [
        "fecha_hora",
        "pagina",
        "fila_en_pagina",
        "nombre_en_appian",
        "archivo_guardado",
        "tamano_bytes",
        "estado",
        "detalle",
    ]
    with open(config.DOWNLOAD_LOG_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        if not existe:
            writer.writeheader()
        writer.writerow(fila_log)


def obtener_ruta_destino_unica(nombre_sugerido: str, clave_item: str, progreso: Dict[str, Any]) -> Path:
    """
    Calcula la ruta donde se guardará el archivo.
    Si un documento distinto tiene el mismo nombre de archivo que otro ya descargado,
    le agrega un sufijo numérico (ej. documento_2.pdf) para no sobrescribirlo.
    """
    nombre_limpio = limpiar_nombre_archivo(nombre_sugerido)
    ruta_base = config.DOWNLOAD_DIR / nombre_limpio

    # Si este mismo item ya tenía una ruta asignada antes, reutilizarla
    if clave_item in progreso["descargados"]:
        archivo_previo = progreso["descargados"][clave_item].get("archivo_guardado")
        if archivo_previo:
            return config.DOWNLOAD_DIR / archivo_previo

    if not ruta_base.exists():
        return ruta_base

    # Verificar si el archivo existente pertenece a otro registro distinto
    archivos_usados = {
        info.get("archivo_guardado")
        for k, info in progreso["descargados"].items()
        if k != clave_item and info.get("archivo_guardado")
    }
    if ruta_base.name not in archivos_usados:
        return ruta_base

    stem = ruta_base.stem
    suffix = ruta_base.suffix
    contador = 2
    while True:
        candidato = config.DOWNLOAD_DIR / f"{stem}_{contador}{suffix}"
        if not candidato.exists() or candidato.name not in archivos_usados:
            return candidato
        contador += 1


def detectar_filas_documentos(page: Page) -> List[Dict[str, Any]]:
    """
    Analiza la tabla visible en Appian Designer y devuelve las filas que corresponden a documentos.
    Filtra automáticamente carpetas (Folders), Knowledge Centers u otros objetos si están mezclados.
    """
    filas_locator = page.locator("table tbody tr")
    total_filas = filas_locator.count()
    items: List[Dict[str, Any]] = []

    for i in range(total_filas):
        tr = filas_locator.nth(i)
        if not tr.is_visible():
            continue

        texto_fila = (tr.inner_text() or "").strip()
        if not texto_fila:
            continue

        # Detectar si la fila es una carpeta (Folder / Knowledge Center) para no intentar descargarla como archivo
        img_alt = ""
        imgs = tr.locator("img[alt]")
        if imgs.count() > 0:
            img_alt = (imgs.first.get_attribute("alt") or "").lower()

        es_carpeta = (
            "folder" in img_alt
            or "carpeta" in img_alt
            or "knowledge center" in img_alt
        )
        if es_carpeta:
            continue

        # Buscar el enlace principal del nombre del documento dentro de la fila
        enlaces = tr.locator("td a")
        if enlaces.count() == 0:
            enlaces = tr.locator("a")

        if enlaces.count() == 0:
            continue

        enlace_principal = enlaces.first
        nombre_visible = (enlace_principal.inner_text() or "").strip()
        if not nombre_visible:
            # Si el primer enlace es un ícono sin texto, buscar el primer enlace con texto
            for j in range(enlaces.count()):
                cand = enlaces.nth(j)
                txt = (cand.inner_text() or "").strip()
                if txt:
                    enlace_principal = cand
                    nombre_visible = txt
                    break

        if not nombre_visible:
            nombre_visible = f"documento_fila_{i + 1}"

        href = enlace_principal.get_attribute("href") or ""

        items.append(
            {
                "indice_fila": i,
                "nombre_visible": nombre_visible,
                "href": href,
            }
        )

    return items


def descargar_por_clic_directo(page: Page, indice_fila: int, timeout_ms: int) -> Download:
    """Intenta descargar el documento haciendo clic directamente sobre su enlace en la tabla."""
    tr = page.locator("table tbody tr").nth(indice_fila)
    tr.scroll_into_view_if_needed(timeout=5000)

    enlaces = tr.locator("td a")
    if enlaces.count() == 0:
        enlaces = tr.locator("a")

    enlace_objetivo = enlaces.first
    for j in range(enlaces.count()):
        cand = enlaces.nth(j)
        if (cand.inner_text() or "").strip():
            enlace_objetivo = cand
            break

    with page.expect_download(timeout=timeout_ms) as download_info:
        enlace_objetivo.click()

    return download_info.value


def descargar_por_checkbox_y_boton(page: Page, indice_fila: int, timeout_ms: int) -> Download:
    """
    Alternativa para vistas de Appian Designer donde se debe seleccionar el checkbox de la fila
    y luego pulsar el botón 'Download' / 'Descargar' de la barra de herramientas superior.
    """
    tr = page.locator("table tbody tr").nth(indice_fila)
    tr.scroll_into_view_if_needed(timeout=5000)

    # Asegurar que ningún otro checkbox esté seleccionado antes
    checkboxes_marcados = page.locator("table tbody input[type='checkbox']:checked")
    for k in range(checkboxes_marcados.count()):
        checkboxes_marcados.nth(k).uncheck(force=True)

    # Marcar el checkbox de la fila actual
    checkbox_fila = tr.locator("input[type='checkbox']").first
    if checkbox_fila.count() > 0:
        checkbox_fila.check(force=True)
    else:
        tr.locator("td").first.click()

    time.sleep(0.3)

    # Buscar el botón Download / Descargar en la barra superior
    boton_descarga = page.locator(
        "button:has-text('Download'), button:has-text('Descargar'), "
        "a:has-text('Download'), a:has-text('Descargar')"
    ).first

    with page.expect_download(timeout=timeout_ms) as download_info:
        boton_descarga.click()

    # Desmarcar el checkbox de la fila actual para dejar limpia la selección
    try:
        if checkbox_fila.count() > 0:
            checkbox_fila.uncheck(force=True)
        else:
            tr.locator("td").first.click()
    except Exception:
        pass

    return download_info.value


def ir_a_siguiente_pagina(page: Page) -> bool:
    """
    Busca el botón de 'Siguiente página' en el paginador de la tabla de Appian Designer.
    Si está habilitado, hace clic y espera a que cargue la siguiente página.
    Retorna True si avanzó de página, o False si ya no hay más páginas.
    """
    selectores_siguiente = [
        "a[aria-label*='Next' i]",
        "button[aria-label*='Next' i]",
        "a[aria-label*='Siguiente' i]",
        "button[aria-label*='Siguiente' i]",
        "a[title*='Next' i]",
        "button[title*='Next' i]",
        "a[title*='Siguiente' i]",
        "button[title*='Siguiente' i]",
        "[class*='Pagination---next']",
        "[class*='GridFooter'] a:has-text('Next')",
        "[class*='GridFooter'] a:has-text('Siguiente')",
    ]

    for selector in selectores_siguiente:
        loc = page.locator(selector)
        if loc.count() == 0:
            continue

        btn = loc.last
        if not btn.is_visible():
            continue

        aria_disabled = (btn.get_attribute("aria-disabled") or "").lower()
        disabled_attr = btn.get_attribute("disabled")
        clases = (btn.get_attribute("class") or "").lower()

        if aria_disabled == "true" or disabled_attr is not None or "disabled" in clases:
            return False

        # Capturar texto de la primera fila antes de avanzar para confirmar cambio
        primera_fila_antes = ""
        try:
            primera_fila_antes = page.locator("table tbody tr").first.inner_text(timeout=2000)
        except Exception:
            pass

        btn.click()
        time.sleep(config.DELAY_AFTER_PAGE_CHANGE_SEC)

        # Esperar hasta que cambie el contenido o termine de cargar la red
        for _ in range(15):
            try:
                primera_fila_despues = page.locator("table tbody tr").first.inner_text(timeout=2000)
                if primera_fila_despues and primera_fila_despues != primera_fila_antes:
                    break
            except Exception:
                pass
            time.sleep(0.5)

        return True

    return False


def ejecutar_flujo_descarga() -> None:
    """Flujo principal interactivo para descargar y verificar los ~1,200 archivos de Appian."""
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    progreso = cargar_progreso()

    print("\n" + "=" * 75)
    print("🚀 AUTOMATIZACIÓN DE DESCARGA Y VERIFICACIÓN PARA APPIAN DESIGNER")
    print("=" * 75)
    print(f"📁 Carpeta destino de descargas : {config.DOWNLOAD_DIR}")
    print(f"📊 Carpeta de reportes          : {config.REPORTS_DIR}")
    print("=" * 75)

    with sync_playwright() as p:
        context: BrowserContext = p.chromium.launch_persistent_context(
            user_data_dir=str(config.BROWSER_PROFILE_DIR),
            headless=False,
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
            args=["--start-maximized"],
        )

        page: Page = context.pages[0] if context.pages else context.new_page()

        try:
            if config.APPIAN_URL and "tu-entorno" not in config.APPIAN_URL:
                page.goto(config.APPIAN_URL)
            else:
                page.goto("about:blank")
        except Exception:
            pass

        print("\n👉 PASO 1: En la ventana del navegador que se acaba de abrir:")
        print("   1. Ingresa la URL de tu entorno Appian e inicia sesión manualmente (SSO/MFA).")
        print("   2. Entra a Appian Designer y abre el Knowledge Center o Carpeta donde están los documentos.")
        print("   3. (Tip) Si puedes, cambia el tamaño de página de la tabla a 50 o 100 elementos por página.")
        input("\n✅ Cuando estés viendo la tabla con los documentos en pantalla, presiona [ENTER] aquí para continuar...")

        # Asegurar que trabajamos sobre la pestaña activa donde el usuario dejó abierta la carpeta
        paginas_abiertas = context.pages
        if len(paginas_abiertas) > 1:
            print(f"\nSe detectaron {len(paginas_abiertas)} pestañas abiertas:")
            for idx_p, pg in enumerate(paginas_abiertas, start=1):
                print(f"  [{idx_p}] {pg.title()} -> {pg.url}")
            seleccion = input(f"Elige el número de pestaña donde están los documentos [por defecto {len(paginas_abiertas)}]: ").strip()
            if seleccion.isdigit() and 1 <= int(seleccion) <= len(paginas_abiertas):
                page = paginas_abiertas[int(seleccion) - 1]
            else:
                page = paginas_abiertas[-1]

        print("\n👉 PASO 2: ¿Cómo se descargan los documentos en tu vista actual de Appian Designer?")
        print("   [1] (Recomendado) Haciendo clic directamente sobre el nombre/enlace del documento en la tabla")
        print("   [2] Marcando el checkbox de la fila y pulsando el botón 'Download' / 'Descargar' arriba")
        print("   [3] Automático (probar clic directo primero y usar checkbox+botón si no descarga)")
        modo_input = input("Selecciona una opción [1/2/3, por defecto 3]: ").strip() or "3"

        pagina_num = 1
        descargados_sesion = 0
        saltados_sesion = 0
        errores_sesion = 0

        while True:
            print(f"\n--- 📄 Analizando Página {pagina_num} ---")
            items_pagina = detectar_filas_documentos(page)

            if not items_pagina:
                print("⚠️ No se detectaron filas de documentos en la tabla actual.")
                reintentar = input("¿Deseas volver a escanear la página actual? (s/n) [n]: ").strip().lower()
                if reintentar == "s":
                    continue
                break

            print(f"🔍 Se encontraron {len(items_pagina)} documentos en la página {pagina_num}.")

            for pos, item in enumerate(items_pagina, start=1):
                indice_fila = item["indice_fila"]
                nombre_visible = item["nombre_visible"]
                href = item["href"]

                # Clave única para control de reanudación
                clave_item = href if href and not href.startswith("#") else f"p{pagina_num}_f{indice_fila}_{nombre_visible}"

                # Verificar si ya se descargó y es válido (> 0 bytes) en una ejecución previa
                if config.SKIP_EXISTING_VALID_FILES and clave_item in progreso["descargados"]:
                    archivo_prev = progreso["descargados"][clave_item].get("archivo_guardado", "")
                    ruta_prev = config.DOWNLOAD_DIR / archivo_prev if archivo_prev else None
                    if ruta_prev and validar_archivo_individual(ruta_prev)[0]:
                        saltados_sesion += 1
                        print(
                            f"⏭️  [Pág {pagina_num} | {pos}/{len(items_pagina)}] Ya descargado y validado: "
                            f"{archivo_prev} ({ruta_prev.stat().st_size:,} bytes)"
                        )
                        continue

                exito_archivo = False
                ultimo_error = ""

                for intento in range(1, config.MAX_RETRIES_PER_FILE + 1):
                    try:
                        print(
                            f"⬇️  [Pág {pagina_num} | {pos}/{len(items_pagina)}] Descargando '{nombre_visible}' "
                            f"(Intento {intento}/{config.MAX_RETRIES_PER_FILE})...",
                            end=" ",
                            flush=True,
                        )

                        download: Optional[Download] = None
                        if modo_input == "1":
                            download = descargar_por_clic_directo(page, indice_fila, config.DOWNLOAD_TIMEOUT_MS)
                        elif modo_input == "2":
                            download = descargar_por_checkbox_y_boton(page, indice_fila, config.DOWNLOAD_TIMEOUT_MS)
                        else:
                            try:
                                download = descargar_por_clic_directo(page, indice_fila, 12000)
                                modo_input = "1"  # Fijar modo 1 tras confirmar que funciona
                            except PlaywrightTimeoutError:
                                download = descargar_por_checkbox_y_boton(page, indice_fila, config.DOWNLOAD_TIMEOUT_MS)
                                modo_input = "2"  # Fijar modo 2 tras confirmar que funciona

                        fallo_red = download.failure()
                        if fallo_red:
                            raise RuntimeError(f"Fallo de red en la descarga: {fallo_red}")

                        nombre_sugerido = download.suggested_filename or nombre_visible
                        ruta_destino = obtener_ruta_destino_unica(nombre_sugerido, clave_item, progreso)

                        download.save_as(str(ruta_destino))

                        # VALIDACIÓN INMEDIATA POST-DESCARGA (> 0 bytes, no temporal, no HTML de error)
                        es_valido, estado_val, tamano_bytes = validar_archivo_individual(ruta_destino)
                        if not es_valido:
                            raise RuntimeError(f"Validación fallida ({estado_val}, {tamano_bytes} bytes)")

                        print(f"✅ OK -> {ruta_destino.name} ({tamano_bytes:,} bytes)")

                        progreso["descargados"][clave_item] = {
                            "nombre_en_appian": nombre_visible,
                            "archivo_guardado": ruta_destino.name,
                            "tamano_bytes": tamano_bytes,
                            "pagina": pagina_num,
                            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        guardar_progreso(progreso)

                        registrar_en_log_csv(
                            {
                                "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "pagina": str(pagina_num),
                                "fila_en_pagina": str(pos),
                                "nombre_en_appian": nombre_visible,
                                "archivo_guardado": ruta_destino.name,
                                "tamano_bytes": str(tamano_bytes),
                                "estado": "OK",
                                "detalle": "Descargado y verificado (>0 bytes)",
                            }
                        )

                        descargados_sesion += 1
                        exito_archivo = True
                        time.sleep(config.DELAY_BETWEEN_DOWNLOADS_SEC)
                        break

                    except Exception as e:
                        ultimo_error = str(e)
                        print(f"❌ Falló: {ultimo_error}")
                        time.sleep(1.5)

                if not exito_archivo:
                    errores_sesion += 1
                    registrar_en_log_csv(
                        {
                            "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "pagina": str(pagina_num),
                            "fila_en_pagina": str(pos),
                            "nombre_en_appian": nombre_visible,
                            "archivo_guardado": "",
                            "tamano_bytes": "0",
                            "estado": "ERROR",
                            "detalle": ultimo_error,
                        }
                    )

            # Intentar avanzar a la siguiente página de la tabla de Appian Designer
            print(f"\n🔄 Buscando botón de siguiente página después de la página {pagina_num}...")
            if ir_a_siguiente_pagina(page):
                pagina_num += 1
                progreso["pagina_actual"] = pagina_num
                guardar_progreso(progreso)
            else:
                print("🏁 No hay más páginas habilitadas en la tabla actual.")
                otra_carpeta = input(
                    "\n¿Deseas navegar manualmente a otra carpeta/página en el navegador y continuar descargando? (s/n) [n]: "
                ).strip().lower()
                if otra_carpeta == "s":
                    input("👉 Navega a la siguiente carpeta en el navegador y presiona [ENTER] cuando esté lista...")
                    pagina_num += 1
                    continue
                break

        print("\n" + "=" * 75)
        print("📊 RESUMEN DE LA SESIÓN DE DESCARGA")
        print("=" * 75)
        print(f"⬇️  Descargados nuevos en esta sesión : {descargados_sesion}")
        print(f"⏭️  Omitidos (ya existían válidos)    : {saltados_sesion}")
        print(f"❌ Errores tras reintentos           : {errores_sesion}")
        print("=" * 75)

        context.close()

    # Ejecutar auditoría final de toda la carpeta de descargas
    auditar_carpeta_descargas()


if __name__ == "__main__":
    ejecutar_flujo_descarga()
