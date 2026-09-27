# Playlist Converter: Spotify ⇄ YouTube Music

Convierte playlists **en ambas direcciones** (de Spotify a YouTube Music y de
YouTube Music a Spotify) y las **mantiene sincronizadas**: cuando agregas canciones
a la playlist original, un botón las lleva a la copia. Genera un reporte CSV con
las canciones dudosas o no encontradas para que las revises a mano.

- **Sin cuota diaria**: usa [`ytmusicapi`](https://github.com/sigma67/ytmusicapi)
  en vez de la API oficial de YouTube (que limita a unas 65 canciones al día).
- **Búsqueda cuidadosa**: primero busca por ISRC (código único de la grabación)
  y después por "artista + título", y compara título, artista y duración. También
  descarta versiones en vivo, covers, karaoke, remixes, etc., salvo que la
  canción original también lo sea. Limpia los títulos de videos de YouTube
  ("Artista - Canción (Video Oficial)") antes de buscarlos en Spotify.
- **Sincronización sin duplicados**: recuerda qué canción corresponde a cuál, así
  al actualizar solo busca las nuevas y nunca agrega una que ya está.

## Opción fácil: la aplicación para Windows (sin instalar Python)

1. Ve a la pestaña **Releases** del repositorio y descarga `PlaylistConverter.exe`
   (o, desde **Actions** → la última ejecución verde → *Artifacts* → `PlaylistConverter-windows`).
2. Haz doble clic. Si Windows muestra "Windows protegió su PC", haz clic en
   **Más información → Ejecutar de todas formas** (el .exe no está firmado digitalmente).
3. Se abre una ventana con dos pestañas:

   **Convertir**
   1. Elige la **dirección** (o simplemente pega el link: se detecta sola).
   2. **Playlist de origen**: pega el link (o marca "Usar mis canciones guardadas").
   3. **Cuenta de YouTube Music**: donde se crea la playlist (si el destino es YouTube
      Music) o con la que se lee (opcional si la playlist de YouTube Music es pública).
   4. **Opciones**: nombre, privacidad, "Solo probar" y "No agregar coincidencias dudosas".

   Presiona **Convertir** y verás cada canción aparecer en la tabla (✔ encontrada,
   ? dudosa, ✘ no encontrada). Doble clic en una fila abre esa canción.
   Al terminar, **Abrir playlist** la abre en el navegador y **Guardar reporte…**
   exporta el resultado a un CSV para Excel.

   **Sincronizadas**
   Cada playlist que conviertes queda en esta lista. Selecciona una o varias y presiona
   **Actualizar seleccionadas** (o **Actualizar todas**): se buscan solo las canciones
   nuevas del origen y se agregan al destino. Si marcas "Quitar también del destino las
   canciones que borré del origen", la copia queda idéntica.
   **Vincular existente…** sirve para playlists que convertiste antes o armaste a mano:
   pegas el link de ambas y desde ahí se actualizan igual.

La primera vez, la ventana te pide el Client ID y el Client Secret de Spotify
(botón **Ajustes de Spotify…**, con instrucciones y un botón para copiar la Redirect URI).
Se sigue el tema claro u oscuro de Windows.

Las cuentas y credenciales se guardan en `%APPDATA%\PlaylistConverter`
(en macOS/Linux: `~/.config/playlist-converter`).

### Publicar una versión nueva del .exe

Cada push construye el .exe automáticamente (pestaña **Actions**). Para dejarlo
en una descarga fija: **Releases → Draft a new release**, crea un tag (ej. `v1.0`)
y publica. El .exe se adjunta solo a la release en un par de minutos.

## Varias cuentas de YouTube Music

Puedes guardar tantas cuentas como quieras y elegir en cuál crear cada playlist:

```bash
python -m playlist_converter add-account mama      # pide pegar la sesión de esa cuenta
python -m playlist_converter accounts              # lista las cuentas guardadas
python -m playlist_converter convert <playlist> --account mama
python -m playlist_converter remove-account mama
```

Para agregar la cuenta de otra persona, esa persona debe iniciar sesión en
music.youtube.com en el navegador (o una ventana privada) y copiar sus
encabezados. Si solo hay una cuenta guardada, se usa automáticamente.

**Spotify:** tu propio login de Spotify puede leer cualquier playlist **pública**
de otra persona (basta con su link). Para que otra persona use su propio Spotify
(por ejemplo, sus playlists privadas o sus favoritas), agrégala en tu app de Spotify
en *User Management*, o que cree su propia app.

## Instalación con Python

Requiere Python 3.10 o más reciente.

```bash
git clone https://github.com/imboqqentt/Playlist-converter.git
cd Playlist-converter
python -m venv .venv
source .venv/bin/activate      # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración (una sola vez)

### 1. Spotify

1. Entra a <https://developer.spotify.com/dashboard> y crea una app.
   - **Redirect URI**: `http://127.0.0.1:8888/callback` (Spotify ya no acepta `localhost`).
   - En "Which API/SDKs are you planning to use?" marca **Web API**.
2. Copia el **Client ID** y el **Client Secret** (en *Settings*). El programa
   te los pide la primera vez y los guarda. También puedes crear un archivo
   `.env` en la carpeta del proyecto con estas dos líneas (ver `.env.example`):

   ```
   SPOTIPY_CLIENT_ID=tu_client_id
   SPOTIPY_CLIENT_SECRET=tu_client_secret
   ```

   En Windows, si lo creas con el Bloc de notas y queda como `.env.txt`, también funciona.
   Si prefieres variables de entorno, también sirven
   (PowerShell: `$env:SPOTIPY_CLIENT_ID="..."`; macOS/Linux: `export SPOTIPY_CLIENT_ID=...`).

La primera vez que conviertas algo se abrirá el navegador para que autorices
la app. El token queda guardado en la carpeta de datos del programa.

> Las apps en "modo desarrollo" solo pueden usarlas las cuentas que agregues en
> *User Management* dentro del dashboard. Spotify también puede exigir que el
> dueño de la app tenga Premium. Para uso personal no es un problema.

### 2. YouTube Music

```bash
python -m playlist_converter add-account principal
```

El comando te guía para copiar los encabezados (headers) de una petición de
music.youtube.com desde las herramientas de desarrollo del navegador (F12 →
Red). Pégalos y presiona Enter dos veces.

> El archivo de cada cuenta equivale a esa sesión de Google: **no lo compartas**.
> Dura hasta que se cierre sesión en ese navegador. Si deja de funcionar,
> vuelve a agregar la cuenta con el mismo nombre.

## Uso

```bash
# Ventana (lo mismo que el .exe)
python -m playlist_converter

# De YouTube Music a Spotify: la dirección se detecta según el link
python -m playlist_converter convert "https://music.youtube.com/playlist?list=PL..."

# Tus "Me gusta" de YouTube Music a Spotify
python -m playlist_converter convert liked --from ytmusic

# Playlists sincronizadas
python -m playlist_converter synced                     # lista con sus IDs
python -m playlist_converter update 3f9a1c2e            # actualiza una
python -m playlist_converter update --all --remove-missing
python -m playlist_converter link <link origen> <link destino>   # vincula dos existentes
python -m playlist_converter unlink 3f9a1c2e            # deja de sincronizar (no borra nada)

# Menú guiado en la terminal
python -m playlist_converter menu

# Convertir una playlist (pega el link de "Compartir" de Spotify)
python -m playlist_converter convert "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

# Tus canciones guardadas ("Canciones que te gustan")
python -m playlist_converter convert liked --name "Mis favoritas"

# Probar primero sin crear nada: solo busca y genera el reporte
python -m playlist_converter convert <playlist> --dry-run
```

Mientras corre, verás algo así:

```
[ 1/42] ✔ Queen - Bohemian Rhapsody → Bohemian Rhapsody (0.96)
[ 2/42] ? Jarabe De Palo - La Flaca → La Flaca (Letra) (0.62)
[ 3/42] ✘ Artista Raro - Canción Rara → no encontrada
...
42 canciones: 39 encontradas, 2 dudosas, 1 no encontradas
Reporte: reporte_20260927_153000.csv

41 canciones agregadas a https://music.youtube.com/playlist?list=PL...
```

### Opciones

| Opción | Qué hace |
|---|---|
| `--name "Nombre"` | Nombre de la playlist nueva (por defecto, el mismo de Spotify). |
| `--privacy PRIVATE\|UNLISTED\|PUBLIC` | Privacidad de la playlist nueva (por defecto `PRIVATE`). |
| `--strict` | No agrega las coincidencias dudosas (quedan solo en el reporte). |
| `--dry-run` | No crea ni modifica nada en YouTube Music. |
| `--append-to ID` | Agrega a una playlist existente de YouTube Music en vez de crear otra (las repetidas se omiten). |
| `--limit N` | Procesa solo las primeras N canciones (útil para probar). |
| `--report archivo.csv` | Dónde guardar el reporte. |
| `--account NOMBRE` | Cuenta de YouTube Music donde crear la playlist. |
| `--auth archivo.json` | Usar un archivo de sesión específico en vez de una cuenta guardada. |
| `--delay 0.5` | Espera entre búsquedas, por si YouTube Music te limita. |

### El reporte

El CSV (se abre directo en Excel) tiene una fila por canción con su estado:

- **encontrada** (puntaje ≥ 0.75): coincidencia confiable.
- **dudosa** (0.50–0.75): probablemente correcta; revísala. Se agrega salvo que uses `--strict`.
- **no_encontrada** (< 0.50): no se agrega; búscala a mano.

## Cómo decide qué canción elegir

Para cada canción de Spotify prueba, en orden, hasta encontrar una coincidencia confiable:

1. Busca el **ISRC** en canciones de YouTube Music.
2. Busca **"artista principal + título"** en canciones (el audio oficial, canales "Topic").
3. Busca lo mismo en **videos** (videos oficiales, videos con letra).

Cada resultado recibe un puntaje de 0 a 1:

- **45 % título**: similitud después de quitar "(feat. …)", "- Remastered 2011", acentos, etc.
- **30 % artista**: vale más si el artista es el dueño del canal que si solo aparece en el título.
- **25 % duración**: ±3 s es perfecto; más de 40 s de diferencia resta puntos.
- **Penalizaciones** por cover, karaoke, instrumental, en vivo, remix, acústico, etc.,
  salvo que la canción original también lo sea.
- **+0.05** si es una canción (audio oficial) y no un video.

## Desarrollo

```bash
pip install -e ".[dev]"
python -m pytest
```

Estructura:

```
playlist_converter/
  cli.py             # comandos y opciones
  gui.py             # ventana (la que abre el .exe)
  converter.py       # conversión y sincronización, compartidas por la ventana y la terminal
  links.py           # registro de playlists sincronizadas (sincronizadas.json)
  refs.py            # reconoce links de Spotify y YouTube Music
  services.py        # crea los servicios con sus credenciales
  interactive.py     # menú guiado en la terminal
  assets/            # ícono
  accounts.py        # cuentas de YouTube Music y carpeta de datos
  config.py          # credenciales de Spotify (.env)
  spotify_service.py # Spotify como origen y destino
  ytmusic_service.py # YouTube Music como origen y destino
  matcher.py         # puntaje de coincidencias (lógica pura, sin red)
  report.py          # reporte CSV
  models.py          # Track, Candidate, MatchResult
tests/
launcher.py          # punto de entrada del .exe
.github/workflows/   # construye el .exe en Windows
```

Para construir el .exe localmente en Windows:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name PlaylistConverter --icon playlist_converter/assets/icon.ico --add-data "playlist_converter/assets:playlist_converter/assets" --collect-data ytmusicapi --copy-metadata ytmusicapi --collect-data sv_ttk launcher.py
```

## Limitaciones

- `ytmusicapi` no es oficial: si Google cambia YouTube Music, puede dejar de
  funcionar hasta que la librería se actualice (`pip install -U ytmusicapi`).
- Spotify no deja leer sus playlists editoriales ni algorítmicas (Discover Weekly,
  Top 50, etc.) desde apps nuevas. Solución: en Spotify, "Agregar a otra playlist"
  → crea una copia propia y convierte esa.
- Los podcasts se omiten. Los archivos locales de Spotify se buscan solo por nombre (no tienen ISRC).
- Al sincronizar, las canciones nuevas se agregan al final de la copia (no se replica el orden).
- Si borras a mano una canción de la copia, la sincronización respeta tu decisión y no la vuelve a agregar.
- Spotify no tiene playlists "no listadas": en esa dirección solo hay privada o pública.
- La primera vez que conviertas hacia Spotify, se te pedirá autorizar de nuevo (se necesitan
  permisos para crear playlists).
