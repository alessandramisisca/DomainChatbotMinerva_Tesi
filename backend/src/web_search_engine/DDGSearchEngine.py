import json
import os
from typing import List
from dotenv import load_dotenv
from ddgs import DDGS # type: ignore
from .base_searcher import BaseSearcher

load_dotenv()
class DuckDuckGoSearcher(BaseSearcher):
    EXCLUDED_DOMAINS : List[str] = ["www.youtube.com", "www.tiktok.com", "www.instagram.com", "www.facebook.com", "www.spotify.com"]        

    def __init__(self, whitelisted_domains: list):
        """
        Inizializziamo la lista di domini supportati in "whitelisted_domains" chiamando il metodo costruttore della 
        classe padre, e istanzia una lista di domini da evitare nella selezione dei siti web da usare per il successivo parsing
        
        """
        super().__init__(whitelisted_domains)
        self.blacklist : List= self.EXCLUDED_DOMAINS       

    def get_search_data(self, query: str, domain: str):
        """
        Input : query dell'utente e dominio da prioritizzare nella ricerca sul web
        Output: lista di dizionari, ogni dizionario contiene l'url scelto, il dominio corrispondente e un estratto del testo corrispondente.

        Se il dominio è definito, viene fatta la rierca sul web utilizzado il costrutto "site: domain" per selezionare i primi 2 url contenenti 
        appartenenti al dominio da prioritizzare. Successivamente, viene fatta anche una ricerca per selezionare altri url aggiuntivi, in modo da fornire poi alla 
        LLM un buon quantitativo di materiale da processare per la risposta. Tutti gli url selezionati vengono poi restituiti in un'unica lista di
        dizionari che segue un ordine gerarchico, partendo dagli url appartenenti al dominio e successivamente quelli aggiuntivi.
        """
        # Chiamata alla libreria DuckDuckGo (DDGS) 
        print(f"DEBUG: CACHE MISS, chiamata reale a DuckDuckGo...")
        results_formatted = []
        raw_with_domain = []
        try:
            if domain:
                search_with_domain: str = f"site:{domain} {query}"
                print("[DUCKDUCKGO SEARCH ENGINE] Searching with domain: ", search_with_domain)
                raw_with_domain = list(DDGS().text(search_with_domain, max_results=2))
            
            search_query = query
            raw_generic = list(DDGS().text(search_query, max_results=4))
            for r in (raw_with_domain + raw_generic):
                url = r.get("url") or r.get("href")
                if any(blocked in url for blocked in self.blacklist):
                    continue
                title = r.get("title", "No Title")
                content = r.get("body") or r.get("text") or ""
                if url:
                    # Evitiamo duplicati (se un URL esce in entrambe le ricerche)
                    if not any(res['url'] == url for res in results_formatted):
                        results_formatted.append({
                            "url": url,
                            "title": title,
                            "content": content
                        })
            
        except Exception as e:
            print(f"DEBUG: Errore durante la chiamata a DuckDuckGo: {e}")
        
        # Filtro Gerarchico
        preferred = [r for r in results_formatted if any(d in r['url'] for d in self.whitelist)]
        final_data = preferred + [r for r in results_formatted if r not in preferred]

        # Unione dei risultati
        print("Ecco gli url selezionati: ", final_data)
        return final_data