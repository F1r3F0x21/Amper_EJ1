# Amper Market Watch

Panel local para consultar la cotización de Amper, S.A. (`AMP.MC`, EUR), visualizar su histórico reciente, guardar puntos en SQLite y publicar variables de solo lectura por OPC-UA.

## Interfaz

La interfaz usa componentes de Tabler Core 1.6.0 (kit HTML/CSS gratuito, licencia MIT) para botones, navegación y controles. La composición, los colores, los textos y el gráfico están adaptados al panel de cotización de Amper. El CSS se carga desde jsDelivr; si el navegador no tiene acceso a Internet, se aplican los estilos propios de respaldo.

## Arranque local

Requiere Python 3.11 o superior.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_PATH = "$PWD\amper.sqlite3"
uvicorn app.main:app --reload
```

Abre <http://localhost:8000>. El servidor consulta el proveedor cada 60 segundos (mínimo configurable: 30 segundos) y persiste el histórico en SQLite. Para cambiar la frecuencia, define `POLL_SECONDS`.

## Docker Desktop

Con Docker Desktop iniciado:

```powershell
docker compose up --build -d
docker compose logs -f amper
```

Web: <http://localhost:8000> · OPC-UA: `opc.tcp://localhost:4840/amper/`.

En Matrikon OPC UA Explorer (o cualquier cliente OPC-UA), crea una conexión a `opc.tcp://localhost:4840/amper/`, selecciona seguridad `None` y acceso anónimo para esta demostración, y navega a `Objects > Amper`. Los nodos publicados son:

| Nodo | Tipo | Descripción |
| --- | --- | --- |
| `PriceEUR` | Double | Último precio en euros |
| `ChangeEUR` | Double | Variación respecto al cierre previo |
| `ChangePercent` | Double | Variación porcentual diaria |
| `Volume` | UInt64 | Volumen del último intervalo recibido |
| `TimestampUTC` | DateTime | Marca de tiempo de la cotización |
| `Status` | String | Estado de conexión con el proveedor |

La dirección del nodo de precio es `ns=2;s=Amper.PriceEUR`. El servidor de demostración usa acceso anónimo y no cifra el transporte; no expongas el puerto OPC-UA directamente a Internet sin configurar certificados, autenticación y reglas de red.

## Acceso desde otra red

Para obtener una URL HTTPS temporal accesible desde Internet, inicia el perfil público:

```powershell
docker compose --profile public up --build -d
docker compose logs -f tunnel
```

Abre la URL `https://…trycloudflare.com` que aparece en los logs. El hostname cambia y el túnel solo funciona mientras el contenedor esté activo. Este modo publica la web sin autenticación; úsalo para demostraciones y no compartas datos privados. No publica OPC-UA. En un despliegue permanente, usa un proxy inverso con TLS y limita el acceso; publica OPC-UA solo en una VPN o red privada. No se recomienda abrir directamente los puertos 8000 y 4840 en el router.

## Despliegue en AWS

El despliegue en una cuenta requiere credenciales, región y configuración de red, por lo que no se ejecuta automáticamente desde este workspace. Una opción sencilla para mantener Docker y OPC-UA es una instancia EC2 compatible con Docker Compose:

1. Comprueba en la consola de AWS qué instancias y recursos están cubiertos por la oferta gratuita vigente en tu cuenta y región. La elegibilidad y los costes cambian; configura un presupuesto y alertas de facturación.
2. Crea una instancia Linux, restringe SSH a tu IP y permite el puerto 8000 solo temporalmente para pruebas. No abras 4840 a Internet.
3. Instala Docker Compose, copia el proyecto a la instancia y ejecuta `docker compose up --build -d`.
4. Para acceso público, coloca un proxy inverso con HTTPS delante de `localhost:8000`, usa un dominio si está disponible y aplica autenticación o controles de acceso.
5. Para OPC-UA remoto, establece primero una VPN/túnel privado y configura certificados y autenticación en el servidor antes de habilitar clientes externos.

Yahoo Finance es un proveedor público no oficial de ejecución en tiempo real: puede entregar datos retrasados, limitar peticiones o cambiar su disponibilidad. La frecuencia de sondeo de la aplicación no garantiza que la cotización sea tiempo real. Las alarmas se guardan en el navegador y solo se evalúan mientras la página está abierta.