# App

Aplicación de biblioteca de lectura autoalojada (estilo Kavita simplificado):
- sin login/registro/autenticación
- abre directo en la biblioteca
- escanea rutas locales
- clasifica archivos por tipo (PDF, GIF, Images, Comics/Archives, EPUB/Books, Unknown/Other)

## Requisitos

- Python 3.10+ (recomendado)
- `pip`

## Cómo ejecutarlo (local)

1. Entrá al repositorio:
   ```bash
   cd /home/runner/work/App/App
   ```
2. Instalá dependencias:
   ```bash
   python -m pip install -r requirements.txt
   ```
3. Iniciá la app:
   ```bash
   python run.py
   ```
4. Abrí en el navegador:
   - `http://localhost:5000`

## Uso rápido

1. En la pantalla principal, agregá una ruta en **Scan path** (ejemplo: `/home/usuario/libros`).
2. Hacé click en **Add path**.
3. Hacé click en **Scan library**.
4. La biblioteca se actualizará con secciones por tipo y cantidad de archivos.
5. Podés abrir cada ítem desde su detalle con:
   - **Open in browser**
   - **Download**

## Variables de entorno opcionales

- `APP_DB_PATH`: ubicación del archivo SQLite (por defecto: `library.db`)
- `APP_SCAN_PATHS`: rutas precargadas al iniciar, separadas por coma

Ejemplo:
```bash
APP_DB_PATH=/home/usuario/app.db APP_SCAN_PATHS=/data/libros,/data/comics python run.py
```

## Ejecutar tests

```bash
python -m unittest discover -s tests -v
```
