# agent/brain.py — Cerebro del agente con function calling
# Generado por AgentKit

"""
Lógica de IA del agente. Usa Groq (Llama 3.3) con function calling
para que SofIA pueda autenticar usuarios y gestionar tickets en la API real de La Hornilla.
"""

import os
import json
import yaml
import logging
from groq import AsyncGroq
from dotenv import load_dotenv

from agent.tools import (
    TOOLS_DEFINITION,
    crear_ticket,
    consultar_ticket,
    listar_tickets,
    obtener_estado_auth,
    iniciar_flujo_login,
    guardar_usuario_temp,
    intentar_login_con_clave,
    _tokens_por_telefono,
)

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Groq
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

# Modelo — soporta function calling
GROQ_MODEL = "llama-3.3-70b-versatile"


def cargar_config_prompts() -> dict:
    """Lee toda la configuración desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    config = cargar_config_prompts()
    return config.get("system_prompt", "Eres un asistente útil. Responde en español.")


def obtener_mensaje_error() -> str:
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    config = cargar_config_prompts()
    return config.get("fallback_message", "Hmm, no entendí bien tu mensaje 😅 ¿Puedes contarme un poco más?")


async def _manejar_autenticacion(mensaje: str, telefono: str) -> str | None:
    """
    Maneja el flujo de login de forma determinista, sin depender del LLM.
    Retorna un mensaje de respuesta si el flujo de auth está activo,
    o None si el usuario ya está autenticado y puede continuar normalmente.
    """
    estado = obtener_estado_auth(telefono)

    if estado == "autenticado":
        return None  # Continuar con Groq

    if estado == "inicio":
        # Primera vez — saludar y pedir usuario
        iniciar_flujo_login(telefono)
        return (
            "¡Hola! Soy SofIA, la asistente de soporte de La Hornilla 👋\n"
            "Para continuar, necesito que inicies sesión.\n\n"
            "¿Cuál es tu *usuario o correo*?"
        )

    if estado == "esperando_usuario":
        # El usuario respondió con su nombre de usuario
        guardar_usuario_temp(telefono, mensaje.strip())
        return "Perfecto 👍 Ahora ingresa tu *contraseña*:"

    if estado == "esperando_clave":
        # El usuario respondió con su contraseña — intentar login
        resultado = await intentar_login_con_clave(telefono, mensaje.strip())
        if resultado.get("ok"):
            nombre_usuario = _tokens_por_telefono.get(telefono, {}).get("usuario", "")
            return (
                f"✅ ¡Sesión iniciada correctamente! Bienvenido/a, *{nombre_usuario}* 😊\n\n"
                "¿En qué puedo ayudarte hoy?"
            )
        else:
            iniciar_flujo_login(telefono)
            return (
                "❌ Usuario o contraseña incorrectos. Intenta de nuevo.\n\n"
                "¿Cuál es tu *usuario o correo*?"
            )

    return None


async def _ejecutar_herramienta(nombre: str, argumentos: dict, telefono: str) -> str:
    """
    Ejecuta la herramienta solicitada por Groq e inyecta el telefono del usuario.
    Retorna el resultado como string JSON.
    """
    logger.info(f"Herramienta: {nombre} | Args: {argumentos}")

    if nombre == "login_usuario":
        resultado = await login_usuario(telefono=telefono, **argumentos)
    elif nombre == "crear_ticket":
        resultado = await crear_ticket(telefono=telefono, **argumentos)
    elif nombre == "consultar_ticket":
        resultado = await consultar_ticket(telefono=telefono, **argumentos)
    elif nombre == "listar_tickets":
        resultado = await listar_tickets(telefono=telefono)
    else:
        resultado = {"error": f"Herramienta desconocida: {nombre}"}

    return json.dumps(resultado, ensure_ascii=False, default=str)


async def generar_respuesta(mensaje: str, historial: list[dict], telefono: str = "test") -> str:
    """
    Genera una respuesta usando Groq con function calling.

    Flujo:
    1. Envía mensaje + historial a Groq con las herramientas definidas
    2. Si Groq llama una herramienta (login, crear ticket, etc.), la ejecuta
    3. Envía el resultado de vuelta a Groq para la respuesta final al usuario

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Mensajes anteriores [{"role": "...", "content": "..."}]
        telefono: Número de WhatsApp — identifica la sesión del usuario

    Returns:
        Respuesta final de SofIA
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    # Flujo de autenticación determinista — tiene prioridad sobre el LLM
    respuesta_auth = await _manejar_autenticacion(mensaje, telefono)
    if respuesta_auth is not None:
        return respuesta_auth

    system_prompt = cargar_system_prompt()

    # Construir lista de mensajes
    mensajes = [{"role": "system", "content": system_prompt}]
    for msg in historial:
        mensajes.append({"role": msg["role"], "content": msg["content"]})
    mensajes.append({"role": "user", "content": mensaje})

    try:
        # Primera llamada — puede solicitar ejecutar una herramienta
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=1024,
            messages=mensajes,
            tools=TOOLS_DEFINITION,
            tool_choice="auto",
        )

        mensaje_asistente = response.choices[0].message

        # Sin herramientas → respuesta directa
        if not mensaje_asistente.tool_calls:
            return mensaje_asistente.content

        # Groq solicitó herramientas — agregarlas al historial y ejecutarlas
        mensajes.append({
            "role": "assistant",
            "content": mensaje_asistente.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in mensaje_asistente.tool_calls
            ]
        })

        for tool_call in mensaje_asistente.tool_calls:
            nombre = tool_call.function.name
            argumentos = json.loads(tool_call.function.arguments)
            resultado = await _ejecutar_herramienta(nombre, argumentos, telefono)

            mensajes.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": resultado,
            })

        # Segunda llamada — respuesta final con los resultados de las herramientas
        response_final = await client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=1024,
            messages=mensajes,
        )

        respuesta = response_final.choices[0].message.content
        logger.info(f"Respuesta generada con herramientas — {GROQ_MODEL}")
        return respuesta

    except Exception as e:
        logger.error(f"Error Groq API: {e}")
        return obtener_mensaje_error()
