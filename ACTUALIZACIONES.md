# Que bunnylol se actualice solo (desde TU GitHub)

Una sola vez:

1. Crea un repositorio en GitHub (puede ser privado). Ejemplo: `tu-usuario/bunnylol`.
2. Sube **el contenido de esta carpeta** (donde está `app.py`) a la raíz del repo. El archivo
   `.gitignore` ya excluye `cache/`, así que tus ajustes y tu diario NO se suben.
   ```
   git init
   git add .
   git commit -m "bunnylol"
   git branch -M main
   git remote add origin https://github.com/tu-usuario/bunnylol.git
   git push -u origin main
   ```
3. En `cache/settings.json` añade:
   ```json
   "update_repo": "tu-usuario/bunnylol",
   "update_branch": "main"
   ```
   Si el repo es privado, añade también `"update_token": "..."` (token de GitHub de **solo lectura**
   para ese repo: Settings → Developer settings → Fine-grained tokens → Contents: Read-only).

Desde entonces: cada vez que subas un cambio a `main`, la app lo descarga sola (cada 6 h con la app
abierta) y lo instala **la próxima vez que la abras**. Si el código nuevo no compila o falla al copiarse,
vuelve sola a la versión anterior. Tus ajustes (`cache/`) nunca se tocan.

Estado: `http://127.0.0.1:8765/api/meta` → `health.update`.
Para apagarlo: `"auto_update": false`.

Importante: la app ejecuta el código que haya en ese repo, así que debe ser un repo tuyo y con tu cuenta protegida.
Si cambia `requirements.txt`, ejecuta `pip install -r requirements.txt` a mano.

---
# Aviso automático cada parche (GitHub Actions)

Con el repo ya subido, el archivo `.github/workflows/patch-audit.yml` se ejecuta solo el miércoles por
la noche, el jueves y el viernes (UTC): baja de Data Dragon los objetos del parche nuevo y del anterior,
comprueba qué pasivas cambiaron y, **solo si hay algo que revisar** (objeto nuevo o pasiva de daño nueva
que la app no sabe leer), abre un *Issue* en tu repo con el informe. GitHub te avisa por correo.

- No hace falta configurar nada más: usa el token que GitHub da a cada ejecución.
- Para probarlo ya: pestaña **Actions → Informe de parche → Run workflow**.
- También funciona a mano: `python tools/patch_audit.py`.
- Dentro de la app, si pasa lo mismo, sale una franja amarilla arriba con el botón **Copiar informe**.

Cuando te llegue un aviso: pégamelo en el chat y te devuelvo el zip con la regla; súbelo al repo y la app se actualiza sola.
