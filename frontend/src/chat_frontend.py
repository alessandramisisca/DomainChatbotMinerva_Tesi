from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
import os

app = FastAPI(title="Minerva Chat Frontend")

# Configurazione Jinja2 per pescare i template dalla cartella corretta
templates = Jinja2Templates(directory="templates")

# Recuperiamo l'URL del backend dalle variabili d'ambiente (impostato nel docker-compose)
BACKEND_URL = os.getenv("BACKEND_URL", "http://chatbot_backend:8001")

timeout_config = httpx.Timeout(
    300.0,           # Timeout generale (5 minuti)
    connect=10.0,    # 10 secondi per trovare il server (lasciamolo così)
    read=None        # Nessun limite di tempo per la lettura dello stream (fondamentale per gli LLM)
)
http_client = httpx.AsyncClient(timeout=timeout_config)

@app.get("/", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    """Restituisce la pagina della chat implementata con Tailwind"""
    return templates.TemplateResponse(request=request, name="chat.html")


# 1. PROXY STREAMING: Gestisce la chiamata alla logica RAG dell'LLM
@app.post("/api/chat")
async def proxy_chat(request: Request):
    """
    Riceve la richiesta dal browser e la gira al backend del chatbot.
    Mantiene attivo lo StreamingResponse per vedere i passaggi dell'agente 
    e i token generati dall'LLM in tempo reale.
    """
    # Preleviamo il body (user_session_id e user_query_input) inviato dal frontend Javascript
    body = await request.json()
    
    try:
        req = http_client.build_request("POST", f"{BACKEND_URL}/chat", json=body)
        r = await http_client.send(req, stream=True)
        
        if r.status_code != 200:
            await r.aread()
            raise HTTPException(status_code=r.status_code, detail="Errore nel backend del chatbot")
            
        # Creiamo un generatore asincrono per evitare che la libreria blocchi il flusso
        async def stream_generator():
            async for chunk in r.aiter_text():
                yield chunk

        return StreamingResponse(
            stream_generator(), 
            media_type="text/event-stream"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore di connessione al backend: {str(e)}")


# 2. PROXY UTILITY: Un gestore generico per girare le richieste GET/POST/DELETE al database
@app.api_route("/api/database/{path:path}", methods=["GET", "POST", "DELETE"])
async def proxy_database_requests(path: str, request: Request):
    url = f"{BACKEND_URL}/{path}"
    # Passiamo anche la query string (fondamentale per session_id e user_id)
    query_string = request.url.query
    full_url = f"{url}?{query_string}" if query_string else url
    
    method = request.method
    body = await request.json() if method in ["POST", "PUT"] else None

    try:
        # Usiamo l'istanza globale http_client definita all'inizio del file
        response = await http_client.request(
            method=method,
            url=full_url,
            json=body,
            timeout=10.0
        )
        # Ritorna direttamente il JSON ricevuto dal backend
        return JSONResponse(status_code=response.status_code, content=response.json())
    except Exception as e:
        print(f"Errore Proxy: {e}") # Fondamentale per il debug nei log
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})