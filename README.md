# Playlist Converter: Spotify → YouTube Music

Script de línea de comandos que lee una playlist de Spotify (o tus canciones
guardadas), busca cada canción en YouTube Music y crea una playlist con las
que encontró. Además genera un reporte CSV con las canciones dudosas o no
encontradas para que las revises a mano.

- **Sin cuota diaria**: usa [`ytmusicapi`](https://github.com/sigma67/ytmusicapi)
  en vez de la API oficial de YouTube (que limita a unas 65 canciones al día).
- **Búsqueda cuidadosa**: primero busca por ISRC (código único de la grabación)
  y después por "artista + título", y compara título, artista y duración. También
  descarta versiones en vivo, covers, karaoke, remixes, etc., salvo que la
  canción original también lo sea.

## Instalación

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
2. Copia el **Client ID** y el **Client Secret** (en *Settings*) y crea un archivo
   llamado `.env` en la carpeta del proyecto con estas dos líneas
   (puedes copiar `.env.example`):

   ```
   SPOTIPY_CLIENT_ID=tu_client_id
   SPOTIPY_CLIENT_SECRET=tu_client_secret
   ```

   En Windows, si lo creas con el Bloc de notas y queda como `.env.txt`, también funciona.
   Si prefieres variables de entorno, también sirven
   (PowerShell: `$env:SPOTIPY_CLIENT_ID="..."`; macOS/Linux: `export SPOTIPY_CLIENT_ID=...`).

La primera vez que conviertas algo se abrirá el navegador para que autorices
la app. El token queda guardado en `.spotify_cache`.

> Las apps en "modo desarrollo" solo pueden usarlas las cuentas que agregues en
> *User Management* dentro del dashboard. Spotify también puede exigir que el
> dueño de la app tenga Premium. Para uso personal no es un problema.

### 2. YouTube Music

```bash
python -m playlist_converter setup-ytmusic
```

El comando te guía para copiar los encabezados (headers) de una petición de
music.youtube.com desde las herramientas de desarrollo del navegador (F12 →
Red) y los guarda en `browser.json`.

> `browser.json` equivale a tu sesión de Google: **no lo compartas ni lo subas
> a GitHub** (ya está en `.gitignore`). Dura unos dos años o hasta que cierres
> sesión en ese navegador.

## Uso

```bash
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
| `--auth archivo.json` | Credenciales de YouTube Music (por defecto `browser.json`). |
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
  spotify_source.py  # lectura de Spotify
  ytmusic_target.py  # búsqueda y creación de playlists en YouTube Music
  matcher.py         # puntaje de coincidencias (lógica pura, sin red)
  report.py          # reporte CSV
  models.py          # Track, Candidate, MatchResult
tests/
```

## Limitaciones

- `ytmusicapi` no es oficial: si Google cambia YouTube Music, puede dejar de
  funcionar hasta que la librería se actualice (`pip install -U ytmusicapi`).
- Spotify no deja leer sus playlists editoriales ni algorítmicas (Discover Weekly,
  Top 50, etc.) desde apps nuevas. Solución: en Spotify, "Agregar a otra playlist"
  → crea una copia propia y convierte esa.
- Los podcasts se omiten. Los archivos locales de Spotify se buscan solo por nombre (no tienen ISRC).
