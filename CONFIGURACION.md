# Guía de Configuración Inicial - OpenShorts

Esta guía explica paso a paso cómo configurar las bases necesarias de **OpenShorts** (YouTube Studio y Configuración) para que funcione en tu entorno local.

---

## 🔑 1. Obtener la API Key de DeepSeek

El motor de inteligencia artificial para sugerir títulos virales y descripciones con capítulos funciona mediante la API de **DeepSeek**.

1. Ve al panel oficial de DeepSeek: **[platform.deepseek.com](https://platform.deepseek.com/)**
2. Regístrate o inicia sesión con tu cuenta.
3. Dirígete a la sección **API Keys** en el menú de la izquierda.
4. Haz clic en **Create API Key**.
5. Ponle un nombre (por ejemplo, "OpenShorts") y copia la clave generada (tendrá un formato similar a `sk-...`).
6. *Nota: Recuerda recargar saldo (mínimo $2-$5) en la pestaña "Top Up" para que la API responda correctamente, ya que no cuenta con un nivel gratuito ilimitado por defecto.*

---

## 📺 2. Configurar la API de YouTube (Autenticación OAuth)

Para publicar tus vídeos y miniaturas directamente en YouTube desde el panel de OpenShorts sin intermediarios, debes crear un **Cliente OAuth 2.0** en Google Cloud Console.

### Paso 2.1: Crear un proyecto en Google Cloud
1. Entra a **[Google Cloud Console](https://console.cloud.google.com/)**.
2. Inicia sesión con la cuenta de Google donde deseas subir los vídeos.
3. Crea un nuevo proyecto haciendo clic en el menú desplegable de proyectos (arriba a la izquierda) y seleccionando **Nuevo proyecto** (New Project). Asigna un nombre como `OpenShorts-Studio` y haz clic en **Crear**.

### Paso 2.2: Habilitar la API de YouTube
1. En la barra de búsqueda de Google Cloud Console, busca **"YouTube Data API v3"**.
2. Selecciona la opción que aparece y haz clic en el botón **Habilitar** (Enable).

### Paso 2.3: Configurar la Pantalla de Consentimiento OAuth (OAuth Consent Screen)
1. En el menú lateral de la izquierda, navega a **API y servicios** (APIs & Services) > **Pantalla de consentimiento OAuth** (OAuth Consent Screen).
2. Selecciona Tipo de usuario **Externo** (External) y haz clic en **Crear**.
3. Rellena la información básica:
   - **Nombre de la aplicación**: `OpenShorts`
   - **Correo de asistencia al usuario**: Tu correo electrónico de Google.
   - **Información de contacto del desarrollador**: Tu correo electrónico.
4. Haz clic en **Guardar y continuar** (Save and Continue).
5. En la sección **Permisos/Ámbitos** (Scopes), haz clic en **Agregar o quitar ámbitos** (Add or remove scopes). En la barra de búsqueda que aparece escribe `youtube.upload`, selecciona el permiso `.../auth/youtube.upload` y haz clic en **Actualizar** (Update) en la parte inferior. Guarda y continúa.
6. En **Usuarios de prueba** (Test Users), es **CRÍTICO** que agregues el correo electrónico de la cuenta de Google que posee el canal de YouTube al que vas a subir los vídeos. Haz clic en **Agregar usuarios** (Add Users), ingresa tu correo y guarda. Guarda y continúa.

### Paso 2.4: Crear las Credenciales OAuth
1. En el menú lateral izquierdo, ve a **Credenciales** (Credentials).
2. Haz clic en **Crear credenciales** (Create Credentials) en la parte superior y selecciona **ID de cliente OAuth** (OAuth Client ID).
3. Selecciona **Aplicación web** (Web application) como tipo de aplicación.
4. En **Orígenes de JavaScript autorizados**, agrega:
   - `http://localhost:8000`
   - `http://localhost:5175`
5. En **URI de redireccionamiento autorizados** (Authorized redirect URIs), agrega exactamente la siguiente dirección:
   - `http://localhost:8000/auth/youtube/callback`
6. Haz clic en **Crear**.
7. Te aparecerá una ventana emergente. Haz clic en **Descargar JSON** (Download JSON).
8. **IMPORTANTE**: Cambia el nombre del archivo descargado a `youtube_client_secrets.json` y guárdalo en la carpeta `data/` dentro del directorio del proyecto:
   `c:\discolocal\PROYECTOS\PYTHON\openshorts\data\youtube_client_secrets.json`

---

## 🚀 3. Ejecución e Inicio de Sesión

1. Asegúrate de tener guardado el archivo `youtube_client_secrets.json` en la carpeta `data/`.
2. Inicia el sistema con el archivo `.bat` (`run_openshorts.bat`) o ejecutando `docker compose up --build`.
3. Abre el navegador en `http://localhost:5175`.
4. El sistema te exigirá configurar tus claves la primera vez. Introduce la **DeepSeek API Key** (`sk-...`) y haz clic en **Guardar**.
5. Conecta tu canal de YouTube en la pestaña **Configuración**:
   - Haz clic en **Conectar YouTube**.
   - Se abrirá una pestaña del navegador con el consentimiento de Google. Selecciona tu cuenta, pulsa en "Continuar" ante la advertencia de aplicación no verificada, marca el check para permitir la gestión de tus vídeos de YouTube y haz clic en **Autorizar**.
   - Tras la autorización, serás redirigido a una página local. Si la página no carga automáticamente, **copia la URL completa de la barra de direcciones de tu navegador**, pégala en el campo de entrada que aparece en OpenShorts y pulsa **Conectar**.
6. ¡Listo! Ya puedes ir a **YouTube Studio**, subir tus vídeos o insertar enlaces, y publicar de forma directa y automatizada.
