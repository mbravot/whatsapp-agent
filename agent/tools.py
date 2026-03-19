# agent/tools.py — Integración con API Flask de La Hornilla (GCP Cloud Run)
# Generado por AgentKit

"""
Conecta SofIA con el sistema real de tickets de La Hornilla.
Cada usuario se autentica con sus propias credenciales — el ticket queda
asociado a su cuenta en la base de datos (via JWT identity).
"""

import os
import httpx
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("agentkit")

# URL base de la API en Cloud Run
API_BASE = os.getenv("TICKETS_API_URL", "https://apilhtickets-927498545444.us-central1.run.app/api")

# Departamento TI y CDG → id=1
ID_DEPARTAMENTO = 1

# Mapeo de nombre de categoría → id en la base de datos
CATEGORIAS = {
    "SOPORTE TECNICO":                10,
    "MANTENIMIENTO DE EQUIPO":        12,
    "ACCESO APP - NUEVO USUARIO":     13,
    "FALLA APP - DATOS MAL INGRESADOS": 14,
    "SOLICITUD INSUMO":               21,
    "MODIFICAR VISUALIZADOR":         "cec69aee-a8e2-4901-a45e-53755ab9d9e2",
}

# Cache de tokens JWT por número de WhatsApp
# { "56912345678": {"access_token": "...", "expires_at": datetime, "usuario": "..."} }
_tokens_por_telefono: dict[str, dict] = {}

# Estado de autenticación por teléfono — maneja el flujo paso a paso
# Estados: "esperando_usuario" | "esperando_clave" | "autenticado"
_estado_auth: dict[str, str] = {}
_usuario_temp: dict[str, str] = {}  # Guarda el usuario mientras espera la clave


# ── Autenticación por usuario ────────────────────────────────────────────────

async def login_usuario(telefono: str, usuario: str, clave: str) -> dict:
    """
    Autentica al usuario con sus propias credenciales y guarda el token
    asociado a su número de WhatsApp.

    Args:
        telefono: Número de WhatsApp del usuario (clave de sesión)
        usuario: Nombre de usuario o correo electrónico
        clave: Contraseña

    Returns:
        {"ok": True, "nombre": "..."} si fue exitoso
        {"ok": False, "error": "..."} si las credenciales son incorrectas
    """
    # Intentar con campo "usuario" primero, luego "correo"
    payloads = [
        {"usuario": usuario, "clave": clave},
        {"correo": usuario, "clave": clave},
    ]

    async with httpx.AsyncClient() as client:
        for payload in payloads:
            try:
                r = await client.post(
                    f"{API_BASE}/auth/login",
                    json=payload,
                    timeout=10,
                )
                if r.status_code == 200:
                    data = r.json()
                    token = data.get("access_token")
                    if not token:
                        continue

                    # Guardar token para este número de WhatsApp
                    _tokens_por_telefono[telefono] = {
                        "access_token": token,
                        "expires_at": datetime.utcnow() + timedelta(minutes=50),
                        "usuario": usuario,
                    }
                    logger.info(f"Login exitoso para {usuario} (tel: {telefono})")
                    return {"ok": True, "usuario": usuario}

            except Exception as e:
                logger.error(f"Error en login: {e}")

    return {"ok": False, "error": "Usuario o contraseña incorrectos. Por favor verifica tus credenciales."}


def obtener_token_usuario(telefono: str) -> str | None:
    """Retorna el token JWT vigente del usuario, o None si no está autenticado."""
    sesion = _tokens_por_telefono.get(telefono)
    if not sesion:
        return None
    if datetime.utcnow() >= sesion["expires_at"]:
        # Token expirado — limpiar sesión
        del _tokens_por_telefono[telefono]
        return None
    return sesion["access_token"]


def usuario_autenticado(telefono: str) -> bool:
    """Verifica si el usuario ya tiene una sesión activa."""
    return obtener_token_usuario(telefono) is not None


def cerrar_sesion(telefono: str):
    """Cierra la sesión del usuario (elimina el token y el estado)."""
    _tokens_por_telefono.pop(telefono, None)
    _estado_auth.pop(telefono, None)
    _usuario_temp.pop(telefono, None)


# ── Máquina de estados para autenticación ───────────────────────────────────

def obtener_estado_auth(telefono: str) -> str:
    """Retorna el estado actual del flujo de login para este teléfono."""
    if usuario_autenticado(telefono):
        return "autenticado"
    return _estado_auth.get(telefono, "inicio")


def iniciar_flujo_login(telefono: str):
    """Marca que estamos esperando que el usuario ingrese su nombre de usuario."""
    _estado_auth[telefono] = "esperando_usuario"


def guardar_usuario_temp(telefono: str, usuario: str):
    """Guarda el usuario ingresado mientras esperamos la contraseña."""
    _usuario_temp[telefono] = usuario
    _estado_auth[telefono] = "esperando_clave"


async def intentar_login_con_clave(telefono: str, clave: str) -> dict:
    """Intenta autenticar con el usuario guardado + la clave recibida."""
    usuario = _usuario_temp.get(telefono, "")
    resultado = await login_usuario(telefono=telefono, usuario=usuario, clave=clave)
    if resultado.get("ok"):
        _estado_auth[telefono] = "autenticado"
        _usuario_temp.pop(telefono, None)
    else:
        # Reiniciar el flujo para que vuelva a pedir usuario
        _estado_auth[telefono] = "inicio"
        _usuario_temp.pop(telefono, None)
    return resultado


# ── Herramientas de tickets ──────────────────────────────────────────────────

async def crear_ticket(telefono: str, categoria: str, descripcion: str, **kwargs) -> dict:
    """
    Crea un ticket en el sistema real usando las credenciales del usuario autenticado.
    El backend asocia el ticket al usuario dueño del JWT.

    Args:
        telefono: Número de WhatsApp (para obtener el token correcto)
        categoria: Nombre de la categoría
        descripcion: Descripción detallada
        titulo: Título breve (opcional)

    Returns:
        Datos del ticket creado o {"error": "..."}
    """
    token = obtener_token_usuario(telefono)
    if not token:
        return {"error": "Sesión expirada. Por favor vuelve a ingresar tu usuario y contraseña."}

    id_categoria = CATEGORIAS.get(categoria.upper().strip())
    if not id_categoria:
        # Búsqueda parcial
        for nombre, id_cat in CATEGORIAS.items():
            if categoria.upper() in nombre:
                id_categoria = id_cat
                break
        if not id_categoria:
            return {"error": f"Categoría no válida. Opciones: {list(CATEGORIAS.keys())}"}

    body = {
        "id_departamento": ID_DEPARTAMENTO,
        "id_categoria": id_categoria,
        "titulo": categoria,  # Usamos el nombre de la categoría como título
        "descripcion": descripcion,
    }

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{API_BASE}/tickets",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if r.status_code not in (200, 201):
                logger.error(f"Error creando ticket: {r.status_code} — {r.text}")
                return {"error": f"Error al crear ticket ({r.status_code})"}
            logger.info(f"Ticket creado — categoría: {categoria}")
            return r.json()

    except Exception as e:
        logger.error(f"Excepción al crear ticket: {e}")
        return {"error": str(e)}


async def consultar_ticket(telefono: str, ticket_id: int) -> dict | None:
    """
    Consulta el detalle de un ticket por su ID.

    Args:
        telefono: Número de WhatsApp (para obtener el token correcto)
        ticket_id: ID numérico del ticket
    """
    token = obtener_token_usuario(telefono)
    if not token:
        return {"error": "Sesión expirada. Por favor vuelve a ingresar tu usuario y contraseña."}

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{API_BASE}/tickets/{ticket_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

    except Exception as e:
        logger.error(f"Excepción al consultar ticket {ticket_id}: {e}")
        return {"error": str(e)}


async def listar_tickets(telefono: str) -> list[dict]:
    """
    Lista los tickets disponibles según el rol del usuario autenticado.

    Args:
        telefono: Número de WhatsApp (para obtener el token correcto)
    """
    token = obtener_token_usuario(telefono)
    if not token:
        return [{"error": "Sesión expirada. Por favor vuelve a ingresar tu usuario y contraseña."}]

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{API_BASE}/tickets",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()

    except Exception as e:
        logger.error(f"Excepción al listar tickets: {e}")
        return []


# ── Definición de herramientas para Groq function calling ───────────────────

TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "crear_ticket",
            "description": (
                "Crea un nuevo ticket de soporte en el sistema de La Hornilla. "
                "IMPORTANTE: Llama esta función SOLO cuando tengas AMBOS valores reales del usuario: "
                "la categoría exacta del enum Y una descripción real del problema (no un placeholder). "
                "Si aún no tienes la descripción, pregúntala primero antes de llamar esta función."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "enum": list(CATEGORIAS.keys()),
                        "description": "Categoría exacta del ticket. Debe ser uno de los valores del enum."
                    },
                    "descripcion": {
                        "type": "string",
                        "description": "Descripción real del problema proporcionada por el usuario. NO uses placeholders."
                    },
                },
                "required": ["categoria", "descripcion"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_ticket",
            "description": "Consulta el estado y detalle de un ticket existente por su ID numérico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "ID numérico del ticket a consultar"
                    }
                },
                "required": ["ticket_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listar_tickets",
            "description": "Lista todos los tickets disponibles según el rol del usuario autenticado.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]
