""" 
Optimized LLM client with single instance, compiti fondamentali:
    -> [VALIDATION] Analizza la domanda dell'utente per estrarre l'intento in formato JSON strutturato
    -> [RAG] Produce la risposta finale testuale unendo la domanda dell'utente al contesto estratto dal Web o dal database.
"""
from llama_cpp import Llama #type:ignore
import os
import json
import threading
from typing import Generator

_LLM_INSTANCE = None
_LOCK = threading.Lock() #SEMAFORO GLOBALE

#ANCHE QUI Double-Checked Locking:

def get_llm_client():
    """Entry point per ottenere sempre la stessa istanza del client."""
    global _LLM_INSTANCE
    if _LLM_INSTANCE is None: #Se il modello è già stato caricato in memoria in precedenza, SALTO GIà QUESTOPEZZO
        with _LOCK: #se è la prima volta in assoluto, blocca temporaneamente l'accesso agli altri thread
            if _LLM_INSTANCE is None: #SECONDO CONTROLLO: vediamo se un altro thread non ha appena inizializzato il modello in questo frangente di tempo, dopodiché crea l'oggetto eseguendo LLMClient()
                _LLM_INSTANCE = LLMClient()
    return _LLM_INSTANCE


class LLMClient:
    def __init__(self):
        self.model = os.getenv("LLM_MODEL_PATH", "/models/qwen2.5-3b-instruct-q4_k_m.gguf")
        if not os.path.exists(self.model):
            raise FileNotFoundError(f"Model not found: {self.model}")
        
        self._cpu_lock = threading.Lock()
        
        # SINGLE OPTIMIZED INSTANCE: 2048 tokens 
        print(f"[LLMClient] Loading model: {self.model}")
        print("[LLMClient] Loading LLM instance (4096 tokens)...")
        self.llm = Llama(
            model_path=self.model,
            n_ctx=int(os.getenv("LLM_N_CTX", "4096")), #finestra di contesto massima
            n_threads=int(os.getenv("LLM_N_THREADS", "2")), 
            n_batch=256, #dimensione del batch per il processamento dei token del prompt (il prompt processing) -> lavora i token a blocchi di 256 per volta per velocizzare l'avvio della risposta
            n_gpu_layers=int(os.getenv("LLM_N_GPU_LAYERS", "0")), #no VRAM, purtroppo ho 2gb e crepa
            verbose=False #no log nativi in C++ di llama.cpp
        ) 
        print("[LLMClient] LLM loaded")

    def generate_validation(self, prompt: str, temp: float = 0.1, fallback_query: str = "") -> str:
        """
        Generazione della risposta della llm dopo la VALIDAZIONE. Deve generare un testo in formato JSON contenente:
            - query utente
            - classificazione della query data dalla llm
            - dominio scelto per indirizzare la rocerca web
            - variabile booleana is_dynamic che determina se servirà il reparsing
            - eventuale risposta con richiesta di chiarimenti 
        """
        try:
            with self._cpu_lock: #garantisce che nessun altro utente avvii un calcolo finché questa validazione non è terminata
                print("[VALIDATION] Generating JSON response...")
                response = self.llm.create_chat_completion( #genera la risposta
                    model=self.model,
                    messages=[
                        {'role': 'user', 'content': prompt}
                    ],
                    stream=False,   #risposta generata in background
                    temperature=temp, #temp bassa -> più il modello è rigido, evitiamo allucinazioni
                    max_tokens=250, #limite max x bloccare l'interfaccia se entra in un ciclo infiniito
                    top_p=0.95,
                    top_k=40,
                    repeat_penalty=1.2  #penaità numerica se il modello tende a ripetere le stessse parole consecutivamente + forza la chiusura delle graffe del JSON
                )
                result = response["choices"][0]["message"]["content"].strip() #estraiamo dall'oggetto dizionario restituito da llama_cpp la stringa testuale pura generata dall'LLM.
                print(f"[VALIDATION] Done: {result}")
                return result
        except Exception as e:
            safe_query = fallback_query if fallback_query else "query"
            
            fallback_obj = {    #costruiamo manualmente un dizionario Python standard con valori di emergenza
                "expanded_query": safe_query,
                "classification": "VAGUE",
                "domain": "en.wikipedia.org",
                "is_dynamic": False,
                "res": "..."
            }
            return json.dumps(fallback_obj)
        
    def generate(self, prompt: str, temp: float = 0.4) -> str:
        """ 
        Qui generiamo solo la risposta dopo la logica di RAG: userà solo il contesto e la user query per restituire
        la risposta da dare all'utente
        """
        try:
            with self._cpu_lock:
                response = self.llm.create_chat_completion(
                    model=self.model,
                    messages=[
                        {'role': 'user', 'content': prompt}
                    ],
                    stream=False,
                    temperature=temp,
                    max_tokens=150
                )
                return response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[GENERATION ERROR] {e}")
            return "Errore nella generazione della risposta."

    def stream(self, prompt: str) -> Generator[str, None, None]:    
        """
        Metodo per generare la risposta in tempo reale
        """
        with self._cpu_lock:
            stream = self.llm.create_chat_completion(
                messages=[
                    {'role': 'user', 'content': prompt},
                ],
                stream=True,
                temperature=0.7
            )

            for chunk in stream:    #Ogni chunk contiene una struttura dati che racchiude la chiave "delta", cioè il pezzett di test appena prodotto
                d = chunk["choices"][0].get("delta", {})
                if "content" in d:
                    yield d["content"]
