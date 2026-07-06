
import requests 
from fastapi import FastAPI, Request, Form 
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from typing import List, Dict, Any, Optional
import json

app = FastAPI() 

templates = Jinja2Templates(directory="templates")
#Indirizzo del backend 
#BACKEND_URL = "http://127.0.0.1:8003"
BACKEND_URL = "http://backend:8003"

def loading_domains() -> List[str]:
    """ Carica la lista dei domini supportati accedendo al file domains.json """
    with open("domains.json", 'r', encoding='utf-8') as f:
        data : Dict[str, Any] = json.load(f)
        return data["domains"]
supported_domains : List[str] = loading_domains()

def all_gs_links() -> List[Dict[str, Any]]:
    """Restituisce in output la lista completa di tutti i link dal Gold Standard dal backend"""
    all_links : List[Dict[str, Any]] = []
    try:
        # Chiamata al backend per ogni dominio supportato
        for domain in supported_domains:
            response : requests.Response = requests.get(
                f"{BACKEND_URL}/full_gold_standard", 
                params={"domain":domain}
            )
            if response.status_code == 200:
                data : Dict[str, Any] = response.json()
                links : List[Dict[str, Any]]= data.get("gold_standard", [])
                all_links.extend(links)
    except Exception as e:
        print(f"Errore di connessione al backend: {e}")
    return all_links


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """ Pagina principale: carica la lista di URL dal Gold Standard del backend """
    gs_list : List[Dict[str, Any]]= all_gs_links()
    return templates.TemplateResponse(
        request = request,
        name = "index.html",
        context={"request": request, "gs_list": gs_list}
    ) 

@app.post("/analyze", response_class=HTMLResponse)
async def analyze(request: Request, url: str = Form(...)) -> HTMLResponse:
    """Coordina Parsing e Evaluation per il singolo url. Viene inviato quando l'utente preme il tasto. 
    Coordina le chiamate al backend.
    """
    # Chiamata al backend per il PARSING 
    parse_url : str = f"{BACKEND_URL}/parse"
    parse_response : Dict[str, Any] = requests.get(parse_url, params={"url":url}).json()

    html_raw : str = parse_response.get("html_text", "")
    parsed_text : str = parse_response.get("parsed_text", "")

    # Chiamata al backend per vedere SE ESISTE il GOLD STANDARD
    gs_url : str = f"{BACKEND_URL}/gold_standard"
    gs_response : requests.Response = requests.get(gs_url, params={"url":url})

    evaluation : Optional[Dict[str, Any]] = None 

    if gs_response.status_code == 200:
        gs_data : Dict[str, Any] = gs_response.json()

        #Se il GS esiste, chiediamo al backend di calcolare le metriche 
        eval_payload : Dict[str, str]= {
            "parsed_text": parsed_text,
            "gold_text": gs_data.get("gold_text", ""),
            
        }
        eval_res = requests.post(f"{BACKEND_URL}/evaluate", 
                                 json=eval_payload)
        
    
        if eval_res.status_code == 200:
            evaluation = eval_res.json()

    gs_list : List[Dict[str, Any]] = all_gs_links()
    return templates.TemplateResponse(
        request = request,
        name ="index.html",
        context={
            "request": request,
            "url": url,
            "html_raw": html_raw,
            "parsed": parsed_text,
            "evaluation": evaluation,
            "gs_list": gs_list 
        }
    )

@app.post("/analyze_full_gs", response_class=HTMLResponse)
async def analyze_full_gs(request: Request, url : str = Form(...)) -> HTMLResponse:
    """Analizza l'intero Gold Standard e calcola le medie globali del dominio"""
    full_results : Optional[Dict[str, Any]]= None 
    domain : str = url.split("/")[2]
    try:
        response : requests.Response = requests.get(f"{BACKEND_URL}/full_gs_eval", params={"domain":domain})
        if response.status_code == 200:
            full_results = response.json()
    except Exception as e:
        print(f"Errore analisi: {e}")
    
    gs_list : List[Dict[str, Any]] = all_gs_links()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "full_results": full_results,
            "gs_list" : gs_list
        }
    )

if __name__ == "__main__":
    import uvicorn 
    # il frontend gira sulla porta 8080 per non 'litigare' col backend
    uvicorn.run(app, host="127.0.0.1", port = 8004)
