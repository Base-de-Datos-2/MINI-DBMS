# Despliegue para el equipo

Cómo dejar la interfaz y la API corriendo en una máquina para que otros
integrantes del grupo la usen desde su navegador. El servidor es el mismo de
[demo.md](demo.md): **un solo proceso** (`python -m api`) sirve la API y el
frontend compilado en el mismo puerto, y es el único dueño del directorio de
datos. No hay que desplegar el frontend por separado: usa rutas relativas
(`/api/...`), así que funciona en cualquier dirección donde se publique el 8000.

## 1. Antes de publicar

Desde la raíz del repositorio, con el servidor detenido:

```bash
git status                                  # saber qué versión se publica
.venv/bin/python -m pytest -q -W error      # suite completa (~3 min)
(cd frontend && npm ci && npx tsc --noEmit && npx vitest run && npm run build)
.venv/bin/python scripts/setup_demo.py      # solo si data/generated/demo no existe
```

Conviene publicar desde un commit, no desde cambios sin confirmar, para que
todos sepan qué código están usando.

No lances el servidor mientras corren los experimentos oficiales de la
Etapa 10: las consultas de los compañeros comparten CPU y disco con las
mediciones y alteran los tiempos.

## 2. Elegir el modo

| Modo | Comando | Qué pueden hacer los compañeros |
|---|---|---|
| Solo lectura (por defecto) | `.venv/bin/python -m api --host 0.0.0.0` | SELECT, EXPLAIN, ver tablas, índices y planes |
| Con escritura | `.venv/bin/python -m api --host 0.0.0.0 --allow-writes` | Además INSERT/DELETE, **Nueva tabla**, importar CSV y transacciones con BEGIN/END/ROLLBACK |

Todos trabajan sobre **la misma base**: lo que uno inserta o crea lo ven los
demás, y una transacción abierta en una pestaña bloquea a las otras hasta su
END o ROLLBACK (es la demostración de la Etapa 8). Cada pestaña tiene su propia
sesión; las sesiones inactivas expiran solas. Para volver al estado inicial:
detener el servidor y ejecutar `.venv/bin/python scripts/setup_demo.py --reset`.

Usa `--allow-writes` solo con una URL que compartas con el grupo. Cualquiera
que tenga la URL puede escribir en la base.

## 3. Publicar el puerto

### Opción A — compañeros fuera de tu red, desde tu computadora: túnel

Un túnel publica tu `127.0.0.1:8000` en una URL HTTPS temporal sin abrir
puertos ni tocar la red de WSL. Con Cloudflare (no requiere cuenta):

```bash
# Instalación, una vez (Linux/WSL x86-64)
mkdir -p ~/.local/bin
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
     -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared

# Terminal 1: el servidor (aquí basta 127.0.0.1)
.venv/bin/python -m api            # o con --allow-writes

# Terminal 2: el túnel
~/.local/bin/cloudflared tunnel --url http://127.0.0.1:8000
```

El túnel imprime una dirección `https://<palabras>.trycloudflare.com`. Esa es
la URL para el grupo. Cambia cada vez que se reinicia el túnel, y deja de
funcionar al cerrar cualquiera de las dos terminales o al apagar la máquina.
`ngrok http 8000` sirve igual si ya tienen cuenta de ngrok.

### Opción B — misma red local (Wi-Fi de la universidad o de casa)

WSL2 en modo NAT (el de esta máquina) no expone sus puertos a la red. Hay que
reenviar el puerto desde Windows:

```bash
# En WSL
.venv/bin/python -m api --host 0.0.0.0
hostname -I        # IP interna de WSL, por ejemplo 172.25.249.112
```

```powershell
# En PowerShell de Windows, como administrador (reemplaza la IP de WSL)
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 `
      connectport=8000 connectaddress=172.25.249.112
New-NetFirewallRule -DisplayName "MiniDBMS 8000" -Direction Inbound `
      -LocalPort 8000 -Protocol TCP -Action Allow
ipconfig           # la IPv4 de Windows en la red Wi-Fi: esa es la que se comparte
```

Los compañeros abren `http://<IPv4-de-Windows>:8000`. La IP interna de WSL
cambia al reiniciar WSL; en ese caso hay que repetir el `portproxy` con la
nueva. Para quitarlo:
`netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0`.
Muchas redes universitarias aíslan a los clientes entre sí; si no conecta,
usa la opción A.

### Opción C — Render (plan gratuito), sin depender de tu computadora

El repositorio trae un `Dockerfile` que compila el frontend, instala la API y
crea la base de demo dentro de la imagen. Probado localmente con los límites
del plan gratuito (512 MB de RAM, 0,1 CPU, puerto en `PORT`): arranca en
~11 s, usa ~45 MB de memoria, la consulta más pesada del demo (JOIN + GROUP BY
con volcado a disco) responde en ~3 s, y se detiene de forma ordenada con la
señal de Render.

1. Sube a GitHub la rama que quieres publicar (commit y push).
2. En <https://dashboard.render.com>: **New → Web Service** y conecta el
   repositorio. Si el repositorio es de una organización de GitHub, la
   organización tiene que autorizar a Render.
3. Configura:
   - **Branch:** la rama que subiste.
   - **Language / Runtime:** `Docker` (Render detecta el `Dockerfile`).
   - **Instance Type:** `Free`.
   - **Environment:** opcional, `ALLOW_WRITES` = `1` para habilitar escritura,
     Nueva tabla, importar CSV y transacciones.
   - **Advanced → Health Check Path:** `/api/health`.
4. **Deploy.** La URL `https://<nombre>.onrender.com` es la que se comparte.

Cómo se comporta el plan gratuito:

- **Se duerme tras ~15 minutos sin visitas.** La siguiente visita tarda cerca
  de un minuto en despertarlo; abrirlo unos minutos antes de una presentación
  lo evita.
- **El disco no es persistente.** Cada reinicio, cada vez que se duerme y cada
  nuevo deploy vuelve a la base de demo inicial: se pierde lo que hayan
  insertado o creado. Para mostrar transacciones y tablas nuevas basta; para
  guardar datos, no.
- **Cada push a la rama vuelve a desplegar** (auto-deploy activado por
  defecto), y eso también reinicia la base.
- **CPU muy limitada:** las consultas pequeñas responden al instante; las que
  vuelcan a disco tardan algunos segundos.

Para probar la misma imagen en tu máquina antes de subirla:

```bash
docker build -t minidbms-demo .
docker run --rm -p 8000:8000 -e ALLOW_WRITES=1 minidbms-demo
```

## 4. Comprobar

- `curl http://127.0.0.1:8000/api/health` responde en la máquina que sirve.
- Desde otro dispositivo, la URL pública abre la interfaz y el preset
  **Igualdad por clave** devuelve `(3, Sol, CS, 24)` con `students_id_hash` en
  el plan.
- Con `--allow-writes`, dos pestañas reproducen los pasos 10–12 del guion de
  [demo.md](demo.md): la segunda espera el lock hasta el END de la primera.

## 5. Detener

`Ctrl+C` en la terminal del servidor (cancela lo que esté corriendo y cierra
los archivos de forma segura) y `Ctrl+C` en la del túnel. No cierres la
terminal ni apagues WSL con el servidor abierto: el cierre ordenado es el que
deja los archivos consistentes.

## Límites conocidos

- Un solo proceso: en las opciones A y B, si tu computadora se apaga, la demo
  deja de estar disponible. En Render, la base vuelve al estado inicial en
  cada reinicio (sección 3, opción C).
- No hay usuarios ni contraseñas: el control de acceso es no compartir la URL
  fuera del grupo y no usar `--allow-writes` si no hace falta.
