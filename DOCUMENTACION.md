# SofIA — Agente de Soporte WhatsApp para La Hornilla
## Documentación Técnica Completa

> Generado el 19 de marzo de 2026
> Versión 1.0 — Producción en Railway

---

## Índice

1. [Resumen del sistema](#1-resumen-del-sistema)
2. [Arquitectura](#2-arquitectura)
3. [Stack tecnológico](#3-stack-tecnológico)
4. [Estructura del proyecto](#4-estructura-del-proyecto)
5. [Flujo de un mensaje](#5-flujo-de-un-mensaje)
6. [Módulos principales](#6-módulos-principales)
7. [Integración con API de Tickets](#7-integración-con-api-de-tickets)
8. [Variables de entorno](#8-variables-de-entorno)
9. [Proveedor de WhatsApp](#9-proveedor-de-whatsapp)
10. [Deploy y producción](#10-deploy-y-producción)
11. [Comandos útiles](#11-comandos-útiles)
12. [Alternativas a Whapi.cloud](#12-alternativas-a-whapicloud)
13. [Próximos pasos sugeridos](#13-próximos-pasos-sugeridos)

---

## 1. Resumen del sistema

**SofIA** es un agente de soporte por WhatsApp construido para **La Hornilla** (empresa exportadora de fruta). Permite a los usuarios internos de la empresa crear, consultar y listar tickets de soporte directamente desde WhatsApp, sin necesidad de acceder a ninguna aplicación web.

### Capacidades de SofIA

| Capacidad | Descripción |
|-----------|-------------|
| **Autenticación** | Pide usuario y contraseña al iniciar la conversación. Autentica contra la API real de La Hornilla vía JWT. |
| **Crear ticket** | Recoge categoría y descripción, crea el ticket en el sistema real usando las credenciales del usuario autenticado. |
| **Consultar ticket** | Busca un ticket por su ID y muestra su estado actual. |
| **Listar tickets** | Muestra todos los tickets accesibles para el usuario. |
| **FAQ interna** | Responde preguntas frecuentes sobre procedimientos y el sistema de tickets. |
| **Memoria** | Recuerda el contexto de la conversación durante toda la sesión. |

### Datos del agente

- **Nombre:** SofIA
- **Número de WhatsApp:** +56 9 8284 1794
- **Tono:** Amigable y casual
- **Horario:** Lunes a Sábado, 7:00 am a 00:00 am
- **Idioma:** Español

---

## 2. Arquitectura

```
Usuario (WhatsApp)
       │
       ▼
Whapi.cloud (canal +56 9 8284 1794)
       │ POST /webhook
       ▼
FastAPI — agent/main.py
  (Railway: whatsapp-agent-production-fac7.up.railway.app)
       │
       ├──► Providers — agent/providers/whapi.py
       │     (normaliza mensajes, envía respuestas)
       │
       ├──► Memory — agent/memory.py
       │     (historial de conversación por número, SQLite)
       │
       └──► Brain — agent/brain.py
             (Groq LLM — Llama 3.3 70B con function calling)
                   │
                   └──► Tools — agent/tools.py
                         (llama a la API de tickets de La Hornilla)
                               │
                               ▼
                   API Flask (Google Cloud Run)
                   https://apilhtickets-927498545444.us-central1.run.app/api
                               │
                               ▼
                   MySQL — Google Cloud SQL (GCP)
```

### Flujo de autenticación

```
Usuario escribe "hola"
       │
       ▼
¿Tiene token en caché? ──NO──► Pide usuario
       │                              │
      SÍ                              ▼
       │                       Pide contraseña
       ▼                              │
Continúa con Groq                     ▼
                            POST /api/auth/login
                                       │
                            ┌──────────┴──────────┐
                           401                   200
                            │                     │
                        Mensaje de          Guarda token
                          error             en memoria
                                                  │
                                                  ▼
                                        Saludo personalizado
                                        con nombre del usuario
```

---

## 3. Stack tecnológico

| Componente | Tecnología | Detalles |
|-----------|-----------|----------|
| Runtime | Python 3.11 | |
| Servidor web | FastAPI + Uvicorn | Webhook handler |
| IA / LLM | Groq — Llama 3.3 70B | Function calling para herramientas |
| WhatsApp | Whapi.cloud | Canal en período de prueba |
| Base de datos local | SQLite + aiosqlite | Historial de conversaciones |
| ORM | SQLAlchemy 2.0 (async) | |
| API de tickets | Flask + JWT (GCP Cloud Run) | API existente de La Hornilla |
| BD de tickets | MySQL (Google Cloud SQL) | BD existente de La Hornilla |
| Variables de entorno | python-dotenv | |
| Contenedor | Docker + Compose | |
| Deploy | Railway | Auto-deploy desde GitHub |

---

## 4. Estructura del proyecto

```
whatsapp-agent/
├── agent/
│   ├── __init__.py
│   ├── main.py            # FastAPI app + webhook handler
│   ├── brain.py           # Groq API + function calling
│   ├── memory.py          # SQLite — historial por número de teléfono
│   ├── tools.py           # Integración con API de tickets de La Hornilla
│   └── providers/
│       ├── __init__.py    # Factory: obtener_proveedor() según .env
│       ├── base.py        # Clase abstracta ProveedorWhatsApp
│       └── whapi.py       # Adaptador Whapi.cloud
├── config/
│   ├── business.yaml      # Datos del negocio
│   └── prompts.yaml       # System prompt de SofIA
├── knowledge/             # Archivos de conocimiento interno
│   └── .gitkeep
├── tests/
│   └── test_local.py      # Simulador de chat en terminal
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env                   # API keys (NO está en GitHub)
└── .env.example           # Template de variables de entorno
```

---

## 5. Flujo de un mensaje

```
1. Usuario escribe en WhatsApp → +56 9 8284 1794

2. Whapi.cloud recibe el mensaje y hace POST a:
   https://whatsapp-agent-production-fac7.up.railway.app/webhook

3. agent/main.py recibe el webhook:
   - Parsea el mensaje con providers/whapi.py
   - Obtiene un MensajeEntrante normalizado {telefono, texto, mensaje_id}

4. agent/brain.py verifica si el usuario está autenticado:
   - NO autenticado → máquina de estados para login (sin LLM)
   - SÍ autenticado → llama a Groq con el historial de conversación

5. Groq (Llama 3.3 70B) genera la respuesta:
   - Si necesita crear un ticket → llama tool crear_ticket()
   - Si necesita consultar → llama tool consultar_ticket()
   - Si necesita listar → llama tool listar_tickets()
   - Si es conversación → responde directamente

6. Las tools llaman a la API Flask de La Hornilla con el JWT del usuario

7. La respuesta se guarda en SQLite (memoria) y se envía al usuario via Whapi.cloud
```

---

## 6. Módulos principales

### agent/main.py — Servidor FastAPI

Punto de entrada del sistema. Expone dos endpoints:

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/` | GET | Health check (para Railway/monitoreo) |
| `/webhook` | GET | Verificación de webhook (Meta Cloud API) |
| `/webhook` | POST | Recibe mensajes de WhatsApp |

### agent/brain.py — Cerebro con Groq

- Usa el modelo `llama-3.3-70b-versatile` de Groq
- Implementa **function calling** para invocar herramientas reales
- Maneja la máquina de estados de autenticación de forma determinista
- Lee el system prompt desde `config/prompts.yaml`
- Mantiene max 20 mensajes de historial por conversación

**Tools disponibles para Groq:**

| Tool | Descripción |
|------|-------------|
| `crear_ticket` | Crea un ticket con categoría y descripción |
| `consultar_ticket` | Consulta el estado de un ticket por ID |
| `listar_tickets` | Lista todos los tickets del usuario |

### agent/memory.py — Memoria con SQLite

- Guarda todas las conversaciones en `agentkit.db`
- Indexado por número de teléfono
- Recupera los últimos 20 mensajes por conversación
- Compatible con PostgreSQL para producción

**Tabla `mensajes`:**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | INTEGER | Primary key autoincremental |
| telefono | VARCHAR(50) | Número del usuario (indexado) |
| role | VARCHAR(20) | "user" o "assistant" |
| content | TEXT | Contenido del mensaje |
| timestamp | DATETIME | Fecha y hora del mensaje |

### agent/tools.py — Integración con API de tickets

Maneja toda la comunicación con la API Flask de La Hornilla.

**Funciones principales:**

| Función | Descripción |
|---------|-------------|
| `login_usuario(telefono, usuario, clave)` | Autentica al usuario y cachea el JWT |
| `usuario_autenticado(telefono)` | Verifica si hay token válido en caché |
| `crear_ticket_api(telefono, categoria, descripcion)` | Crea ticket via POST /api/tickets |
| `obtener_ticket_api(telefono, ticket_id)` | Consulta ticket via GET /api/tickets/{id} |
| `listar_tickets_api(telefono)` | Lista tickets via GET /api/tickets |

**Categorías mapeadas:**

| Nombre | ID en BD |
|--------|----------|
| SOPORTE TÉCNICO | 10 |
| MANTENIMIENTO DE EQUIPO | 12 |
| ACCESO APP - NUEVO USUARIO | 13 |
| FALLA APP - DATOS MAL INGRESADOS | 14 |
| SOLICITUD INSUMO | 21 |
| MODIFICAR VISUALIZADOR | cec69aee-... |

**Departamento:** ID = 1 (TI y CDG)

---

## 7. Integración con API de Tickets

### Base URL
```
https://apilhtickets-927498545444.us-central1.run.app/api
```

### Autenticación
```
POST /api/auth/login
Body: { "usuario": "...", "clave": "..." }
Respuesta: { "access_token": "...", "refresh_token": "..." }

Uso en requests: Authorization: Bearer <access_token>
```

### Endpoints usados por SofIA

```
# Crear ticket
POST /api/tickets
Authorization: Bearer <token>
Body: {
  "id_departamento": 1,
  "id_categoria": <id>,
  "titulo": "<nombre_categoria>",
  "descripcion": "<descripcion>"
}
Nota: el id_usuario se obtiene automáticamente del JWT

# Listar tickets
GET /api/tickets
Authorization: Bearer <token>

# Detalle de ticket
GET /api/tickets/<id>
Authorization: Bearer <token>
```

### Seguridad
- Los tokens JWT se cachean en memoria por número de WhatsApp
- Expiración automática a los 50 minutos (antes del vencimiento real)
- El `id_usuario` del ticket se obtiene del JWT — nunca se hardcodea
- La `id_sucursal` se obtiene del perfil del usuario autenticado

---

## 8. Variables de entorno

```env
# IA
GROQ_API_KEY=gsk_...              # API key de Groq (groq.com)

# WhatsApp
WHATSAPP_PROVIDER=whapi           # Proveedor activo
WHAPI_TOKEN=7INjf2ja...           # Token de Whapi.cloud

# API de tickets La Hornilla
TICKETS_API_URL=https://apilhtickets-927498545444.us-central1.run.app/api
TICKETS_API_USER=mbravo           # Usuario de servicio para la API
TICKETS_API_PASSWORD=...          # Contraseña del usuario de servicio

# Servidor
PORT=8000
ENVIRONMENT=production            # development | production

# Base de datos
DATABASE_URL=sqlite+aiosqlite:///./agentkit.db
```

---

## 9. Proveedor de WhatsApp

### Whapi.cloud (actual)

- **Plan:** Prueba gratuita hasta 25.03.2026
- **Canal:** Soporte La Hornilla
- **Número:** +56 9 8284 1794
- **Channel ID:** HAWKEY-PCDC2
- **Webhook:** `https://whatsapp-agent-production-fac7.up.railway.app/webhook`
- **Método webhook:** POST

### Cambiar de proveedor

El sistema está diseñado para cambiar de proveedor con mínimo esfuerzo:

1. Crear el archivo `agent/providers/<nuevo_proveedor>.py` implementando `ProveedorWhatsApp`
2. Registrarlo en `agent/providers/__init__.py`
3. Cambiar `WHATSAPP_PROVIDER=<nuevo_proveedor>` en las variables de entorno

Ver sección [12. Alternativas a Whapi.cloud](#12-alternativas-a-whapicloud) para más detalles.

---

## 10. Deploy y producción

### Railway (producción actual)

- **URL pública:** `https://whatsapp-agent-production-fac7.up.railway.app`
- **Repositorio:** `https://github.com/mbravot/whatsapp-agent`
- **Auto-deploy:** Sí — cada push a `main` redespliega automáticamente
- **Health check:** `GET /` → `{"status": "ok"}`

### Proceso de deploy

```bash
# 1. Hacer cambios localmente
# 2. Subir a GitHub
git add .
git commit -m "descripción del cambio"
git push

# Railway despliega automáticamente en ~2 minutos
```

### Docker (alternativa local)

```bash
# Construir y levantar
docker compose up --build

# Ver logs
docker compose logs -f agent

# Detener
docker compose down
```

---

## 11. Comandos útiles

```bash
# Test local (simula WhatsApp en terminal)
python tests/test_local.py

# Arrancar servidor en desarrollo
uvicorn agent.main:app --reload --port 8000

# Instalar dependencias
pip install -r requirements.txt

# Ver logs en Railway
# (desde el dashboard de Railway → Deployments → View Logs)
```

---

## 12. Alternativas a Whapi.cloud

El plan gratuito de Whapi.cloud vence el **25.03.2026** y tiene limitaciones de mensajes.
Estas son las alternativas, ordenadas por facilidad de implementación:

---

### Opción A — Meta Cloud API (WhatsApp oficial) ⭐ Recomendada para producción

**Pros:**
- API oficial de Meta — más estable y confiable
- Modelo de precios por conversación (primeras 1.000/mes gratis)
- Sin límites artificiales de mensajes
- Escalable a miles de usuarios

**Contras:**
- Requiere cuenta de **Facebook Business verificada**
- Proceso de aprobación puede tomar 1-3 días
- Número de teléfono dedicado (no puede estar en WhatsApp normal)

**Costo:** Gratis hasta 1.000 conversaciones/mes, luego ~$0.015 USD por conversación

**Pasos para migrar:**
1. Crear app en developers.facebook.com → tipo "Business"
2. Agregar producto "WhatsApp"
3. Obtener: `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_VERIFY_TOKEN`
4. Cambiar en Railway: `WHATSAPP_PROVIDER=meta`
5. Agregar variables: `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_VERIFY_TOKEN`
6. Configurar webhook en Meta: `https://whatsapp-agent-production-fac7.up.railway.app/webhook`

El adaptador `agent/providers/meta.py` **ya está incluido** en el código (solo hay que activarlo).

---

### Opción B — Twilio WhatsApp

**Pros:**
- Muy confiable con buena documentación
- Fácil de implementar
- Sandbox gratis para pruebas

**Contras:**
- Más caro que Meta (~$0.05 USD por conversación)
- También requiere aprobación de número para producción

**Costo:** ~$0.05 USD por mensaje enviado/recibido

**Pasos para migrar:**
1. Crear cuenta en twilio.com
2. Obtener: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
3. Cambiar en Railway: `WHATSAPP_PROVIDER=twilio`
4. Configurar webhook en Twilio Console

El adaptador `agent/providers/twilio.py` **ya está incluido** en el código.

---

### Opción C — Baileys (open source, sin costo)

**Pros:**
- Completamente gratuito
- Sin límites de mensajes
- Basado en WhatsApp Web (no requiere aprobación)

**Contras:**
- No es oficial — riesgo de baneo de número
- Requiere mantener sesión activa (como WhatsApp Web)
- Más complejo de mantener en producción
- **No recomendado para uso empresarial**

---

### Comparativa rápida

| Proveedor | Costo | Estabilidad | Facilidad | Oficial |
|-----------|-------|-------------|-----------|---------|
| Whapi.cloud (actual) | Pago después de prueba | Alta | ⭐⭐⭐⭐⭐ | No |
| **Meta Cloud API** | Gratis hasta 1K conv/mes | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ✅ Sí |
| Twilio | ~$0.05/msg | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Sí (revendedor) |
| Baileys | Gratis | ⭐⭐ | ⭐⭐ | ❌ No |

**Recomendación:** Migrar a **Meta Cloud API** antes del 25.03.2026.

---

## 13. Próximos pasos sugeridos

### Corto plazo (antes del 25.03.2026)
- [ ] Migrar de Whapi.cloud a **Meta Cloud API** (gratis y oficial)
- [ ] Agregar número de teléfono dedicado para SofIA

### Mediano plazo
- [ ] Migrar base de datos de SQLite a **PostgreSQL** en Railway (para persistencia real en producción)
- [ ] Agregar **actualización de tickets** (cambiar estado, agregar comentarios)
- [ ] Notificaciones proactivas: SofIA avisa cuando un ticket es atendido o resuelto
- [ ] Panel de administración para ver conversaciones de SofIA

### Largo plazo
- [ ] Integrar con más departamentos (no solo id=1)
- [ ] Soporte para imágenes/documentos adjuntos en tickets
- [ ] Métricas: tickets creados por SofIA, tiempo de respuesta, satisfacción

---

*Documentación generada con AgentKit — whatsapp-agent v1.0*
