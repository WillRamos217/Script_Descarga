# Automatización de Descarga y Verificación de Documentos en Appian Designer

Herramienta en **Python + Playwright** para automatizar la descarga masiva de documentos por páginas desde cualquier carpeta de **Appian Designer**, comprobando inmediatamente después de cada descarga la integridad del archivo `.zip`, contando cuántos documentos vienen adentro, clasificándolos por tipo (`PDF`, `Word`, `Excel`, `Imagen`, etc.) y detectando duplicados, descargas parciales previas o caídas de conexión (*Timeouts*).

---

## 📁 Estructura del Proyecto

```text
Pro-Descarga-Doc-Appian/
├── src/                          # Código fuente modular del proyecto
│   ├── __init__.py
│   ├── config.py                 # Carga de variables .env, rutas y configuración UTF-8
│   ├── downloader.py             # Automatización con Playwright (login, filtros, descarga y eliminación)
│   └── verifier.py               # Inspección de archivos .zip, conteo por tipos y generación de reportes
├── scripts/                      # Utilidades auxiliares de desarrollo
│   └── grabar_acciones.py        # Grabador opcional de acciones con Playwright Codegen
├── descargas/                    # Carpeta predeterminada donde se guardan los .zip descargados
│   └── .gitkeep
├── reportes/                     # Carpeta donde se generan los informes CSV y TXT
│   └── .gitkeep
├── main.py                       # Punto de entrada principal para ejecutar el programa
├── .env                          # Credenciales y configuración local (ignorado en Git por seguridad)
├── .env.example                  # Plantilla de ejemplo para configurar el archivo .env
├── .gitignore                    # Reglas de exclusión de Git
├── requirements.txt              # Dependencias de Python necesarias
└── README.md                     # Documentación completa del proyecto
```

---

## 🛠️ 1. Instalación desde Cero (En cualquier PC)

Si vas a configurar este proyecto por primera vez en una computadora nueva o después de clonarlo desde GitHub, sigue estos pasos en orden:

### Paso 1: Requisitos previos
- Tener instalado **Python 3.10 o superior** (puedes descargarlo desde [python.org](https://www.python.org/downloads/) asegurándote de marcar la casilla *"Add Python to PATH"* durante la instalación).
- Para comprobar que Python está instalado, abre **PowerShell** y ejecuta:
  ```powershell
  python --version
  ```

### Paso 2: Clonar o abrir la carpeta del proyecto
Abre una terminal **PowerShell** y clona el repositorio:
```powershell
git clone https://github.com/WillRamos217/Script_Descarga.git
cd Script_Descarga
```

### Paso 3: Crear el entorno virtual (`.venv`)
Se recomienda crear un entorno virtual limpio dentro del proyecto (`--clear` elimina cualquier `.venv` residual si copiaste la carpeta desde otra PC):
```powershell
python -m venv --clear .venv
```
*(Si Windows bloquea la activación de scripts en PowerShell, puedes habilitarla para tu usuario con: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`).*

### Paso 4: Instalar las dependencias de Python
Con el entorno virtual creado, instala todas las librerías listadas en [`requirements.txt`](requirements.txt) (`playwright`, `python-dotenv`, etc.):
```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Paso 5: Instalar el navegador Chromium de Playwright
Playwright necesita descargar su propio navegador Chromium para controlar las descargas de forma aislada:
```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

### Paso 6: Crear tu archivo `.env`
Crea tu archivo `.env` copiando la plantilla [`.env.example`](.env.example):
```powershell
Copy-Item .env.example .env
```

---

## ⚙️ 2. Configuración del archivo `.env`

Antes de ejecutar el script, abre el archivo [`.env`](.env) y ajusta los valores que necesites:

```env
# ==============================================================================
# 1. CREDENCIALES Y CARPETA DE APPIAN
# ==============================================================================
APPIAN_USERNAME=tu_usuario@dominio.com
APPIAN_PASSWORD=tu_contraseña

# Link directo a la carpeta de Appian Designer que deseas descargar
APPIAN_FOLDER_URL=link de la carpeta

# ==============================================================================
# 2. CARPETA LOCAL DE DESCARGA Y OPCIONES DE ELIMINACIÓN
# ==============================================================================
# Si se deja vacío o como ./descargas, se guardarán en la carpeta "descargas" del proyecto.
# También puedes colocar cualquier ruta absoluta de tu disco local:
# Ejemplo: DOWNLOAD_DIR=C:\Users\willa\Downloads\Documentos_Appian
DOWNLOAD_DIR=./descargas

# ¿Eliminar de Appian los archivos de cada página después de descargarlos y comprobarlos?
# Opciones: true (sí eliminar tras comprobar que el ZIP es válido) | false (no eliminar, solo descargar)
DELETE_AFTER_DOWNLOAD=false

# ==============================================================================
# 3. FILTROS DE BÚSQUEDA EN APPIAN DESIGNER
# (Deja en blanco cualquier filtro que NO quieras aplicar)
# ==============================================================================

# Buscar por "Nombre o descripción" (texto libre)
FILTER_SEARCH_TEXT=

# Filtrar por "TIPO DE OBJETO"
# Opciones válidas (una o varias separadas por coma):
# Documento, Carpeta de Documentos, Informe de Proceso
FILTER_OBJECT_TYPES=

# Filtrar por "ÚLTIMA MODIFICACIÓN POR" (uno o varios usuarios separados por coma)
FILTER_MODIFIED_BY=

# Filtrar por "ÚLTIMA MODIFICACIÓN" (Formato DD/MM/YYYY, ej: 25/01/2026)
FILTER_DATE_FROM=25/01/2026
FILTER_DATE_TO=05/06/2026
```

### Detalle de las variables y filtros disponibles
| Variable en `.env` | Equivalente en Appian Designer | Cómo funciona |
| :--- | :--- | :--- |
| `FILTER_SEARCH_TEXT` | **Nombre o descripción** | Escribe el texto en el buscador superior izquierdo y presiona `Enter`. |
| `FILTER_OBJECT_TYPES` | **TIPO DE OBJETO** | Marca las casillas indicadas (`Documento`, `Carpeta de Documentos`, `Informe de Proceso`). |
| `FILTER_MODIFIED_BY` | **ÚLTIMA MODIFICACIÓN POR** | Busca y selecciona el usuario o lista de usuarios separados por coma. |
| `FILTER_DATE_FROM` | **Desde** (`DD/MM/YYYY`) | Selecciona automáticamente el mes, año y día inicial en el calendario de Appian. |
| `FILTER_DATE_TO` | **Hasta** (`DD/MM/YYYY`) | Selecciona automáticamente el mes, año y día final en el calendario de Appian. |
| `DELETE_AFTER_DOWNLOAD` | Botón **ELIMINAR** | Si es `true`, elimina de Appian los documentos de cada página únicamente después de comprobar que su `.zip` descargado es válido (`> 0 bytes`). Por defecto es `false`. |

> **Nota:** Si dejas cualquier filtro en blanco (después del signo `=`), el script simplemente lo omitirá.

---

## 🚀 3. Cómo Ejecutar el Script

Abre una terminal PowerShell en la carpeta raíz del proyecto y ejecuta [`main.py`](main.py):

```powershell
.\.venv\Scripts\python.exe main.py
```

*(Si solo deseas auditar y generar el informe de una carpeta de descargas ya existente sin abrir el navegador, ejecuta):*
```powershell
.\.venv\Scripts\python.exe main.py --solo-verificar
```

### ¿Qué hace el script paso a paso?
1. **Confirmación de seguridad (si `DELETE_AFTER_DOWNLOAD=true`):**
   - Si activaste la eliminación posterior en el `.env`, **antes de abrir el navegador** el script mostrará una advertencia en la consola indicando que se borrarán permanentemente los archivos de Appian tras descargarlos y te pedirá escribir **`Y`** y presionar `Enter` para confirmar. Si ingresas cualquier otra tecla, se cancela de inmediato sin tocar nada.
2. **Diagnóstico previo del disco local:**
   - Comprueba que la ruta en `DOWNLOAD_DIR` exista y tenga permisos de escritura.
   - Detecta si quedaron archivos incompletos (`.crdownload`, `.part`, `0 bytes` o `.zip` corruptos) de una ejecución anterior interrumpida.
   - Indexa los documentos que ya existían en la carpeta para alertar sobre posibles duplicados.
3. **Inicio de sesión y aplicación de filtros:**
   - Abre Chromium, entra a `APPIAN_FOLDER_URL`, inicia sesión con tus credenciales y aplica los filtros configurados en el `.env`.
   - Espera automáticamente a que la tabla de Appian termine de refrescarse tras filtrar para evitar que las casillas seleccionadas se desmarquen solas.
4. **Descarga por páginas, comprobación inmediata y eliminación opcional:**
   - Selecciona todas las filas de la página actual (verificando que permanezcan marcadas antes de continuar), abre el menú **`MÁS`** y hace clic en **`Descargar`**.
   - Guarda el archivo con prefijo de página (`pagina_001_...zip`, `pagina_002_...zip`).
   - **Comprobación inmediata post-descarga:** Abre e inspecciona el `.zip` recién descargado sin descomprimirlo en disco, verificando que no esté dañado, contando cuántos archivos trae adentro, comprobando que ninguno pese `0 bytes` y mostrando en consola cuántos son **PDF**, **Word**, **Excel**, etc.
   - **Eliminación opcional en Appian (`DELETE_AFTER_DOWNLOAD=true`):** Solo si la comprobación del `.zip` fue 100% exitosa (`0` archivos vacíos), presiona el botón **`ELIMINAR`** de la barra superior, marca la casilla *"Entiendo que esta acción no se puede deshacer"* en la ventana emergente y confirma la eliminación antes de continuar con el siguiente lote de documentos.
   - Avanza con el botón **`Página siguiente`** (o procesa los siguientes 25 documentos que suben a la tabla tras eliminar) y se detiene automáticamente cuando ya no quedan más páginas o documentos.

---

## ⚠️ 4. Advertencias para Usar tu PC y Dejar el Script en Segundo Plano

Playwright controla su propio navegador internamente (no mueve el cursor físico de tu mouse ni bloquea tu teclado), por lo que **puedes seguir usando tu PC en otras tareas** mientras el script descarga, siempre que tengas en cuenta estas reglas:

### ✅ Lo que SÍ puedes hacer mientras corre
- **Usar el mouse y el teclado con normalidad** en cualquier otro programa (Word, Excel, VS Code, Teams, etc.).
- **Abrir y navegar en tus propios navegadores** (tu ventana habitual de Chrome, Edge, Firefox, etc.).
- **Poner otras ventanas encima de la ventana del script:** Puedes cubrir por completo la ventana de Chromium del script con otras aplicaciones y seguirá funcionando en segundo plano.

### 🚫 Lo que NO debes hacer para no alterar su funcionamiento
1. **NO minimices la ventana de Chromium del script con el botón `_`:**
   - **Importante:** En Windows, cuando minimizas una ventana a la barra de tareas, el sistema operativo pausa el repintado visual de esa ventana y los menús desplegables de Appian (como el botón **`MÁS -> Descargar`** o el calendario de fechas) pueden congelarse o no abrirse.
   - **Solución:** Déjala siempre **abierta en el fondo** (detrás de las ventanas en las que estés trabajando), nunca minimizada.
2. **NO hagas clic ni escribas dentro de la ventana de Chromium que abrió el script:**
   - Mientras el script está corriendo, cualquier clic accidental dentro de esa página de Appian puede cerrar el menú desplegable **`MÁS`** o desmarcar las filas seleccionadas justo antes de iniciar la descarga.
3. **NO abras ni muevas los archivos `.zip` de la carpeta de descargas mientras el script sigue corriendo:**
   - Si abres un `.zip` en WinRAR/7-Zip justo cuando el script intenta escribir o verificar ese archivo, Windows bloqueará el archivo (aunque el script tiene protección para guardarlo como `_copia_2.zip`, es mejor esperar a que termine).
4. **NO dejes que el PC entre en modo suspensión, hibernación o bloqueo por inactividad:**
   - Si la descarga va a tardar varios minutos, asegúrate de que la configuración de energía de Windows no suspenda el equipo ni apague la tarjeta de red.
5. **Evita desconectar o cambiar de red Wi-Fi / VPN a mitad del proceso:**
   - Si hay un microcorte de internet, el script reintentará automáticamente hasta 3 veces cada página, pero si la desconexión dura más tiempo detendrá la corrida de forma segura.

> **💡 Tip opcional (Ejecución 100% oculta / Headless):**
> Si en algún momento prefieres que ni siquiera se abra la ventana del navegador, en [`src/downloader.py`](src/downloader.py) puedes cambiar `headless=False` por `headless=True`. En ese modo corre 100% invisible sin riesgo de minimizarla o tocarla por accidente.

---

## 📊 5. Manejo de Errores y Reportes Generados

### Alertas automáticas en consola
- **Error de Timeout / Conexión a Internet:** Si la red falla o Appian tarda más de 60 segundos en responder, el script informa exactamente en qué página ocurrió y realiza hasta **3 reintentos automáticos**.
- **Alerta de descargas parciales previas:** Si en la carpeta de descargas habían quedado archivos `.crdownload`, `.part`, archivos de `0 bytes` o `.zip` corruptos de una sesión anterior, el script avisa al iniciar.
- **Alerta de duplicados:** Si parte o todos los documentos dentro de un `.zip` ya habían sido descargados en otra página o en una corrida previa, el reporte en consola te indica cuántos documentos son repetidos y cuántos son nuevos.

### Archivos de reporte en `./reportes/`
Al finalizar el proceso (o ejecutando manualmente `.\.venv\Scripts\python.exe main.py --solo-verificar`), se generan tres archivos:
1. **`resumen_tipos_descargados.txt`**: Informe general con el total de paquetes `.zip`, cantidad total de documentos internos (válidos, únicos, duplicados y vacíos) y el **desglose por tipo de archivo** (cuántos PDFs, cuántos Words, etc.).
2. **`reporte_verificacion.csv`**: Tabla resumen por cada paquete `.zip` descargado.
3. **`detalle_archivos_en_zips.csv`**: Inventario detallado documento por documento dentro de todos los `.zip`, indicando a qué página pertenece, su nombre, su tipo (`PDF`, `Word`, etc.), su peso en KB y su estado.
