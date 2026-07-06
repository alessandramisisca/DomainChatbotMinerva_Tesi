import json
import asyncio
import time
from typing import AsyncGenerator, Dict
from urllib.parse import urlparse
from src.client.minerva_client import MinervaClient
from src.web_search_engine.base_searcher import BaseSearcher
from src.ollama_data.ollama_client import get_llm_client
from src.ollama_data.ollama_prompt import PromptManager
#from src.web_search_engine.TavilySearchEngine import WebSearcher
from src.rag.chunking import TextChunker
from src.rag.embedding import get_embedding_module
from src.mariadb_data import database as db
import os
from dotenv import load_dotenv
import numpy as np

# GLOBAL VARIABLES
# MAX URLS DA USARE PER OGNI QUERY + MAX DURATA IN CACHE
MAX_URLS = 5
MAX_URLS_FROM_DB = 3
REPARSE_THRESHOLD_DAYS = 5

def sse_format(step: str, message: str) -> str:
    """Format messages for SSE streaming."""
    return f"data: {json.dumps({'step': step, 'message': message})}\n\n"

class ChatLogic:
    def __init__(self, minerva_client: MinervaClient, web_searcher: BaseSearcher):
        """
        Input : 
        minerva_client : client per il parsing dei documenti
        web_searcher : motore di ricerca selezionato per la selezione dei siti web

        Inizializza il client che ci permette di comunicare con gli endpoint dei parser specifici per gli url selezionati,
        il motore di ricerca selezionato, il modulo contenente i prompt di validazione e generazione della risppsta per la LLM, 
        e i moduli contenenti la logica RAG (chunking ed embedding)

        """
        self.minerva_client = minerva_client
        self.web_searcher = web_searcher
        self.prompt_manager = PromptManager()
        self.chunker = TextChunker()
        self.vector_store = get_embedding_module()  #ISTANZA CONDIVISA, protetta da threading.Lock

    @property
    def ollama_client(self):
        """Metodo per ottenere l'stanza condivisa della LLM """
        return get_llm_client()
    
    def _validate_query(self, user_query: str, chat_history: str = ""):
        """ 
        Input: query inserita dall'utente nella conversazione, storico degli utimi quattro messaggi della conversazione corrente
        Output: oggetto JSON contenente una variabile booleana (TRUE se la query è stata valutata come chiara, FALSE altrimenti) e il dizionario della validazione fatta dalla LLM
        In questa funzione viene completato il prompt di validazione, dove viene inserita la query dell'utente e lo storico degli ultimi messaggi, e
        e viene passato in input al corrispondente metodo di comunicazione con il modello LLM scelto. 
        Quest'ultimo restituirà l'oggetto JSON contenente la query dell'utente (eventualmente risolta con il contesto della conversazione), la classificazione della query
        (CLEAR, VAGUE, REJECTED), il dominio individuato per la ricerca sul web, la valutazione della dinamicità dell'argomento (true -> l'argomento cambia spesso, riguarda
        attulità o situazioni dinamiche come data corrente/meteo) e infine in "res" un'eventuale risposta elaborata dalla LLM da restituire 
        se la query corrente è stata classificata come VAGUE
        """
        print(f"[VALIDATION] Starting validation: {user_query}")
        
        prompt : str = self.prompt_manager.get_intent_from_user_query(user_query, chat_history)
        json_risposta = self.ollama_client.generate_validation(prompt, fallback_query=user_query)
        
        try:
            data = json.loads(json_risposta)
            stato : str = data.get("classification")
            
            if stato == "CLEAR":
                return True, data
            else:
                clarification : str = data.get("res")
                return False, clarification
        except json.JSONDecodeError as e:
            print(f"[VALIDATION ERROR] {e}: {json_risposta}")
            return True, {"expanded_query": user_query, "classification": "CLEAR", "domain": "en.wikipedia.org", "is_dynamic": False, "res":""} #non esplode così
        
    def _check_db_relevance(self, query_embedding: np.ndarray, db_chunks: list, top_k : int = 3, threshold : float = 0.82) -> list:
        """
        Input:
             query_embedding: vettore della query utente
             db_chunks: lista di dizionari conteneti chunk e il corrispettivo embedding del database
             top_k: numero massimo di url da restituire 
             threshold: soglia minima di similarità da usare per selezionare gli url rilevanti che contengono informazioni per rispondere alla query dell'utente 
        Output:
            lista di tuple contenente gli url selezionati come utili da riustilizzare con il punteggio corrispondente
        La funzione filtra i chunk già presenti all'interno del database tramite embedding. 
        Confronta la query dell'utente inserita nella chat con i chunk salvati nel database.
        Estraiamo tutti i vettori embedding dei chunk del database (ad ogni chunk è associato anche il corrispettivo url da cui è stato estratto) 
        e li inseriamo in una matrice numpy a due dimensioni, usata per il calcolo della similarità coseno tra matrice e vettore della query corrente.
        Successivamente, salviamo  in un dizionario ogni url con la corrispettiva lista di punteggi di similarità calcolati per i suoi chunk rispetto alla query,
        e per ogni elemento del dizionario, viene fatta la media pesata dei punteggi di similarità dei due chunk col valore di punteggio più alto, così
        da penalizzare valutazioni erroneamente alte.
        Infine, salviamo in una lista le tuple di (url, punteggio) con il valore di punteggio maggiore della soglia scelta, riordinati dal punteggio più
        alto a quello più basso, e vengono restituite solo le prime k tuple.
        Queste k tuple saranno proprio quelle contenenti gli url già salvati nel database che 
        contengono informazioni utili per la risposta da fornire all'utente, così da evitare la ricerca sul web.
        """

        if not db_chunks:
            return []
        
        all_db_vectors : np.ndarray = np.array([chunk["embedding"] for chunk in db_chunks])  #estraiamo tutti i vettori, messi in una matrice numpy a due dimensioni
    
        # 2. cosine similarity, ma calcolo il prodotto scalare tra matrice e vettore della query corrente
        similarities : np.ndarray= self.vector_store._calculate_cosine_similarity(all_db_vectors, query_embedding)
        
        # 3. Mappa i punteggi calcolati sui rispettivi URL, dunque per quell'url raggruppiamo i suoi chunks insieme e ne salviamo i suoi valori di similarità con la query attuale
        url_scores = {}
        for chunk, sim in zip(db_chunks, similarities):
            url = chunk["url"]
            if url not in url_scores:
                url_scores[url] = []
            url_scores[url].append(sim)
        
        url_robust_scores = []
        for url, scores in url_scores.items():
            # Media dei 2 migliori chunk per documento: penalizza documenti fuori tema con 1 solo chunk fortunato
            # se usiamo max(scores) rischiamo di prendere un chunk con alta similarità ma errato
            top_2_scores = sorted(scores, reverse=True)[:2] #prendiamo i due punteggi più alti di ogni doc
            avg_score = sum(top_2_scores) / len(top_2_scores) #media dei due punteggi più alti per i chunk di quell'url
            url_robust_scores.append((url, avg_score))  #salviamo url + media dei punteggi di similarità dei top chunk, la media pesata ci fa capire quanto è davvero rilevante quell'url

        url_robust_scores.sort(key=lambda x: x[1], reverse=True)    #riordiniamo tutte le tuple (url, punteggio similarità) in ordine decrescente in base al punteggio di similarità
        filtered_results = [item for item in url_robust_scores if item[1] >= threshold] # salviamo in una lista solo le tuple che hanno punteggio di similarità >= della soglia di similarità da noi stabilita
        
        return filtered_results[:top_k] #le prime top_k tuple, dunque qui ci saranno i tok_k url del db che possono essere riutilizzati

    def _get_or_create_embeddings(self, url: str, text: str):
        """
        Input: nuovo url scelto dalla ricerca web e testo parsato associato

        Effettua il chunking e l'embedding di un nuovo testo parsato e lo salva nel DB assieme al corrispettivo url.
        """

        chunks = self.chunker.split(text)   #metodo del modulo di embedding, chiama RecursiveCharacterTextSplitter
        if not chunks:
            return
        
        embs : np.ndarray = self.vector_store.encode(chunks, is_query=False) #metodo nel modello embedding che restituisce la lista dei vettori di embedding
        domain : str = urlparse(url).hostname
        try:
            db.save_document_with_chunks(url, domain, text, 0.0, chunks, [e.tolist() for e in embs]) #[e.tolist() for e in embs]) converte ognuno di questi vettori numpy in una lista di float, che può essere ssalvata correttamente nel db
        except Exception as e:
            print(f"[DB SAVE ERROR] {e}")
        for c, e in zip(chunks, embs):
            #aggiungiamo i chunk e i vettori di embedding nell'indice della sessione corrente (è volatile, non sta nel db, infatti coì evitiamo riletture)
            self.vector_store.add_to_index(c, e)
    
    async def execute_chat_flow(self, user_session_id: str, user_query_input: str) -> AsyncGenerator[str, None]:
        """
        Gestisce il flusso principale della chat: validazione, ricerca DB, Web search e generazione.
        
        Input:
            user_session_id: ID univoco della sessione chat
            user_query_input: Messaggio in input dell'utente
            
        Yields:
            Messaggi in formato SSE per lo streaming lato client.
        1. Estrae dal database lo storico degli ultimi messaggi della chat corrente, la funzione definita nel db è sincrona -> bloccante, con await asyncio.to_thread la query viene eseguita da un thread secondario in un pool interno di python
        2. Chiama il metodo di valutazione della richiesta dell'utente, che fornisce anche l'eventuale dominio da utilizzare nella ricerca sul web: se la query è VAGUE, viene mandato un mesaggio all'utente
        dove viene richiesto di fornire più informazioni, si salvano query e risposta della LLM nel database, e la logica si interrompe. Se CLEAR, si continua.
        3. Viene fatto il calcolo del vettore embedding della query dell'utente
        4. In maniera asincrona, estraiamo dal DB tutti i chunk salvati con i corrispettivi url e li passiamo in input al metodo definito in precedenza che calcola l'embedding
        sui chunk già salvati nel database e ne confronta la similarità con la query dell'utente, per valutare se si possono riutilizzare i siti presenti. Una volta scelti MAX_URLS_FROM_DB url
        tra quelli valutati come utili, essi vengono inseriti nella lista di url che mantiene quelli correntemente usati nella risposta, viene estratto il testo parsato associato (sempre salvato nel DB), e se il salvataggio 
        supera la soglia di giorni limite (REPARSE_THRESHOLD_DAYS), gli viene associato il valore true nella variabile boolena "needs_reparse", così da effettuare nuovamente l'estrazione del testo.
        5. Se il numero di url raggiunto è ancora inferiore a MAX_URLS, viene fatta la ricerca sul web chiamando il metodo corrispondente nel motore di ricerca, passando anche il dominio a cui dare la priorità. 
        Gli url scelti dalla ricerca sul web vengono aggiunti alla lista corrente e al dizionario con "needs_reparse": true, in quanto il testo parsato non è ancora disponibile poiché selezionati per la prima volta.
        6. Per tutti gli url presenti nel database vengono estratti i corrispettivi chunk e i vettori embedding da utilizzare, mentre con un metodo asincrono viene fatto il parsing e l'embedding in parallelo di tutti gli url selezionati invece dalla ricerca sul web.
        7. Terminato l'embedding degli url, vengono restituiti i 3 migliori chunk che saranno passati come come contesto alla LLM per costruire la risposta per l'utente
        8. Viene chiamato il metodo che restituisce il prompt di generazione della risposta, completato con il contesto fornito, e successivamente viene passato in input al metodo che permetterà alla LLM di costruire la risposta finale, mostrata a schermo token per token all'utente
        9. I siti utilizzati per la risposta e i rispettivi domini vengono salvati in un dizionario che viene poi prelevato lato frontend per essere mostrato a schermo assieme alla risposta.
        10. La query dell'utente con la risposta della LLM e i siti utilizzati vengono salvati nel database, e l'esecuzione termina

        General logic: validate user query -> check if db has relevant urls (embedding user_query + saved chunks) -> 
        uses urls (if found) from db + urls from web search -> for db urls, checks if re-parsing is needed (max-threshold-days or is_dynamic)
        -> chunking + embedding -> response prompt -> user response
        """
        # 1. GET CHAT HISTORY
        history_records = await asyncio.to_thread(db.get_chat_history, user_session_id)
        chat_history_str_format = "\n".join([f"{'Utente' if m['role']=='user' else 'Assistente'}: {m['content']}" for m in history_records[-4:]])
        
        print(f"[DEBUG] Session: {user_session_id} | Records: {len(history_records)}")

        # 2. VALIDATE + CLASSIFY DOMAIN + DETECT DYNAMIC
        yield sse_format("status", "Validazione della richiesta")
        print(f"[DEBUG HIST] History passata al validatore: {chat_history_str_format}")
        is_valid, validation_result = await asyncio.to_thread(
            self._validate_query, 
            user_query_input,
            chat_history_str_format
        )
        
        if not is_valid:
            yield sse_format("status", "Richiesta ambigua o non valida")
            
            clarification_text = validation_result if validation_result else "Errore nella validazione."
            for char in clarification_text:
                yield sse_format("token", char)
            #salvo nel db in modo concorrente
            asyncio.create_task(asyncio.to_thread(db.save_chat_message, user_session_id, "user", user_query_input))
            asyncio.create_task(asyncio.to_thread(db.save_chat_message, user_session_id, "assistant", clarification_text))
            yield sse_format("complete", "Terminato")

            return

        expanded_query = validation_result.get("expanded_query", user_query_input)
        chosen_domain = validation_result.get("domain", "null")
        if chosen_domain == "null" or chosen_domain == "":
            chosen_domain = None
        is_dynamic = validation_result.get("is_dynamic", False)
        
        print(f"[VALIDATION] Expanded: {expanded_query} | Domain: {chosen_domain} | Dynamic: {is_dynamic}")
        
        # CLEAR vector store BEFORE DB search -> evitiamo contaminazioni dato che è un singleton condiviso, va svuotato ad ogni richiesta
        # altrimenti i chunk estratti da utenti precedenti rimangono erroneamente in memoria
        
        self.vector_store.clear()   
        print("[CLEAR] Vector store cleared before DB search")
        
        # 3. GET QUERY EMBEDDING FOR DB SEARCH, lo usiamo per il metodo che controlla la pertinenza di url nel db
        query_emb_2d = self.vector_store.encode([expanded_query], is_query=True)

        # 4. CHECK DB FOR RELEVANT URLS
        yield sse_format("status", "Verifica cache del sistema")
        all_db_chunks = await asyncio.to_thread(db.get_all_chunks_with_urls)
        
        relevant_urls_db = self._check_db_relevance(query_emb_2d, all_db_chunks, top_k=MAX_URLS, threshold=0.82)
        urls_to_use = []
        sources_info = {}
        
        # Process DB URLs
        for url, relevance_score in relevant_urls_db:
            if len(urls_to_use) >= MAX_URLS_FROM_DB: 
                break 
            doc_info = await asyncio.to_thread(db.get_document_info, url)   #per gli ul pertinenti nel db, ne prendo il testo parsato
            if doc_info:
                parsed_at_timestamp = doc_info.get("created_at")
                days_old = (time.time() - parsed_at_timestamp) / (24 * 3600) if parsed_at_timestamp else 999
                
                needs_reparse = True if is_dynamic else (days_old > REPARSE_THRESHOLD_DAYS)
                
                urls_to_use.append(url)
                sources_info[url] = {
                    "domain": doc_info.get("domain"),
                    "needs_reparse": needs_reparse
                }
                
                print(f"[DB] Using {url} (age={days_old:.1f}d, reparse={needs_reparse}, score={relevance_score:.3f})")
        
        # 5. FILL REST WITH WEB SEARCH
        remaining = MAX_URLS - len(urls_to_use)
        if remaining > 0:
            print(f"[WEB SEARCH] Need {remaining} more URLs ({len(urls_to_use)} from DB)")
            yield sse_format("status", f"Ricerca web ({remaining} fonti aggiuntive)")
            search_results = await asyncio.to_thread(self.web_searcher.get_search_data, expanded_query, chosen_domain) #motore di ricerca in un thread separato
            
            # Prioritize chosen domain
            if chosen_domain:
            # Filtriamo separando chi contiene il dominio scelto da chi non lo contiene
                chosen_domain_results = [r for r in search_results if chosen_domain.lower() in r['url'].lower()]
                other_results = [r for r in search_results if chosen_domain.lower() not in r['url'].lower()]
            else:
                # Se non c'è dominio, tutti i risultati sono "generici"
                chosen_domain_results = search_results
                other_results = []
            all_res = chosen_domain_results + other_results
            
            for res in all_res:
                if len(urls_to_use) >= MAX_URLS:
                    break
                url = res['url']
                if url not in urls_to_use:
                    urls_to_use.append(url)
                    sources_info[url] = {
                        "domain": urlparse(url).hostname,
                        "needs_reparse": True   #perchè sono quelli nuovi, che ovviamente devono essere parsati
                    }
                    print(f"[WEB SEARCH] Added {url}")
        
        if not urls_to_use:
            yield sse_format("error", "Non ho trovato fonti per rispondere.")
            return
        
        print(f"[SOURCES] Using {len(urls_to_use)} URLs")
        
        # 6. PARSE/REPARSE URLS
        yield sse_format("status", "Elaborazione delle fonti")
        self.vector_store.clear()

        # Pre-load cached embeddings
        cached_data = await asyncio.to_thread(db.get_multiple_cached_embeddings, urls_to_use)   #prendiamo per tutti gli url della lista, chunk + embedding di quegli url

        async def process_single_url(url):  #funzione interna asincrona, attivata per permettere il parsing in parallelo
            info = sources_info[url]    #dizionario fonti usate, ogni url è salvato col suo dominio + variabie di reparse
            #i nuovi url hanno "needs_reparse" a true, quindi saltano questo if
            if not info.get("needs_reparse", True) and url in cached_data:
                for item in cached_data[url]:
                    self.vector_store.add_to_index(item["text"], item["embedding"])
                return

            #solo i nuovi url
            parsed = await asyncio.to_thread(self.minerva_client.get_parsed_text_from_urls, [url])
            for u, text in parsed:
                if text and text.strip(): 
                    await asyncio.to_thread(self._get_or_create_embeddings, u, text)    #metodo che salva url, chunk e i rispettivi vettori

        # Processiamo tutti gli url in parallelo, li passiamo alla funzione che calcola i parsing asincronamente
        tasks = [process_single_url(url) for url in urls_to_use]
        for finished_task in asyncio.as_completed(tasks):
            try:
                await finished_task
            except Exception as e:
                print(f"[PARSE ERROR] {e}")

        # 7. RAG RETRIEVAL
        top_chunks = self.vector_store.search(expanded_query, top_k=3)
        if not top_chunks:
            yield sse_format("token", "Mi dispiace, non sono riuscito a reperire informazioni aggiornate per rispondere alla tua domanda.")
            return
        context = "\n\n---\n\n".join(top_chunks)
        print("[CHAT LOGIC] Ecco il context passato al rag prompt", context[:4080])
        
        # 8. GENERATE RESPONSE
        full_prompt = self.prompt_manager.get_rag_prompt(expanded_query, context)
        print(f"[GENERATION] Starting...")
        llm_response: str = ""
        
        yield sse_format("status", "Generazione della risposta")

        stream_sync = self.ollama_client.stream(full_prompt)

        for token in stream_sync:   #consuma i singoli caratteri/parole man mano che i parametri probabilistici del modello llam_cpp li calcolano
            llm_response += token  
            yield sse_format("token", token)
        
        # 9. APPEND SOURCES
        used_domains = list(set([sources_info[url]["domain"] for url in urls_to_use]))
        
        sources_data = {
             "domains": used_domains,
             "urls": urls_to_use
         }
        
        yield sse_format("sources", json.dumps(sources_data))
        final_res = llm_response #+ fonti_formattate

        # 10. SAVE TO DB
        try:
            await asyncio.to_thread(db.save_chat_message, user_session_id, "user", user_query_input, None)
            await asyncio.to_thread(db.save_chat_message, user_session_id, "assistant", final_res, urls_to_use)
            print("[DB SAVE] Messaggi salvati in ordine cronologico perfetto.")
        except Exception as e:
            print(f"[DB SAVE ERROR] Errore nel salvataggio della chat: {e}")

        yield sse_format("complete", "Terminato")
