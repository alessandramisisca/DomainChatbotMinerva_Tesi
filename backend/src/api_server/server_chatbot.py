"""api points get/post per la logica della chat"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from contextlib import asynccontextmanager
from src.client.minerva_client import MinervaClient
from fastapi.responses import StreamingResponse
from src.chat_logic.chat_logic import ChatLogic

import json
import os
from fastapi import Request

from src.mariadb_data import database as db

db.init_db()

SUPPORTED_DOMAINS : List[str] =  [
        "en.wikipedia.org",
        "editorial.rottentomatoes.com",
        "www.nba.com",
        "www.amazon.it"
    ]

# Initialize LLM ONCE at startup (before creating app)
print("[STARTUP] Initializing LLM...")
from src.ollama_data.ollama_client import get_llm_client
_llm_client = get_llm_client()  
print("[STARTUP] LLM loaded successfully")

# Initialize clients
minerva_client = MinervaClient(base_url="http://old_parser:8003")
CHOSEN_ENGINE = "duckduckgo" 

if CHOSEN_ENGINE == "duckduckgo":
    from src.web_search_engine.DDGSearchEngine import DuckDuckGoSearcher
    web_searcher = DuckDuckGoSearcher(whitelisted_domains=SUPPORTED_DOMAINS)
else:
    from src.web_search_engine.TavilySearchEngine import TavilySearchEngine
    web_searcher = TavilySearchEngine(whitelisted_domains=SUPPORTED_DOMAINS)
chat_logic_instance = ChatLogic(minerva_client=minerva_client, web_searcher=web_searcher)

app = FastAPI()

class ChatResponse(BaseModel):
    """ Modello della risposta llm """
    sintesi_iniziale: str 
    risposta: str
    fonti_citate: List[str] 
    eventuale_riassunto: Optional[str]


class ChatRequest(BaseModel):
    user_session_id: str
    user_query_input: str

class NewSessionRequest(BaseModel):
    user_session_id: str 
    user_id: str

# ENDPOINT STRUTTURATI DEL DATABASE

# chat_new_session
@app.post("/chat_new_session")
async def chat_new_session(request: NewSessionRequest):
    """Endpoint che apre il database e aggiunge una nuova entry nella tabella che crea le sessioni """
    try:
        db.chat_new_session(request.user_session_id, request.user_id)
        return{"status": "success", "message": "Sessione creata con successo"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# chat_all_session
@app.get("/chat_all_session/{user_id}")
async def chat_all_session(user_id: str):
    """ Endpoint che apre il database e restituisce gli elementi salvati nella tabella che salva lo storico delle chat/ conversazioni """
    try:
        sessioni = db.chat_all_session(user_id)
        # Formattiamo la data per evitare problemi di serializzazione
        risultato = [
            {"session_id": s["session_id"], "created_at": s["created_at"].strftime("%Y-%m-%d %H:%M:%S")}
            for s in sessioni
        ]
        return {"status": "success", "sessions": risultato}
    except Exception as e:
        return {"status" : "error", "message": str(e)}

# chat_logic  
@app.post("/chat")
async def chat_complete_logic(request: ChatRequest) -> StreamingResponse:
    """
    Qui dentro ChatLogic esegue la ricerca sul web, estrae gli url, verifica i domini, 
    legge la cache (se la variabile booleana è True), fa il chunking e passa tutto a Ollama.
    """
    return StreamingResponse(
        chat_logic_instance.execute_chat_flow(request.user_session_id, request.user_query_input),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# chat_messages
@app.get("/chat_messages/{user_session_id}")
async def chat_messages(user_session_id: str):
    """ Endpoint che ci fa vedere tutti i messaggi scambiati in una chat per quel determinato utente restituendo la history """
    try: 
        cronologia = db.get_chat_history(user_session_id)
        return {"status": "success", "session_id": user_session_id, "history": cronologia}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
# erase_history 
@app.post("/erase_history")
async def erase_history():
    """ Endpoint per cancellare i vecchi elementi salvati nel database secondo i limiti impostati (es. 7 giorni o dominio nba) """
    try:
        db.erase_history()
        return {"status": "success", "message": "Cache ripulita con successo"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# erase_session
@app.delete("/erase_session/{user_session_id}")
async def erase_session(user_session_id: str):
    """ Endpoint per cancellare la conversazione corrente con la llm """
    try: 
        db.erase_session(user_session_id)
        return {"status": "success", "message": f"Sessione {user_session_id} eliminata"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

#erase_all_sessions
@app.delete("/erase_all_sessions/{user_id}")
async def erase_all_session(user_id: str):
    """ Endpoint per cancellare tutte le chat esistenti per quell'utente """
    try:
        db.erase_all_sessions(user_id)
        return {"status": "success", "message": f"Tutte le sessioni dall'utente {user_id} sono state eliminate"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
