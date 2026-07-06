import json
import os
from typing import List, Dict, Any
from dotenv import load_dotenv
from tavily import TavilyClient
from .base_searcher import BaseSearcher

load_dotenv()
API_KEY = os.getenv("TAVILY_API_KEY")


class TavilySearchEngine(BaseSearcher):
    EXCLUDED_DOMAINS : List[str] = ["www.youtube.com", "www.tiktok.com", "www.instagram.com", "www.facebook.com", "www.spotify.com"]

    def __init__(self, whitelisted_domains: list):
        """
        Inizializziamo la lista di domini supportati in "whitelisted_domains" chiamando il metodo costruttore della 
        classe padre, una lista di domini da evitare nella selezione dei siti web da usare per il successivo parsing, il client Tavily con la corrispettiva
        chiave API definita nel file env.

        
        """
        super().__init__(whitelisted_domains)        
        self.api_key = os.getenv("TAVILY_API_KEY")
        self.client : TavilyClient = TavilyClient(api_key=self.api_key)
        self.blacklist : List[str] = self.EXCLUDED_DOMAINS

    def get_search_data(self, query: str, domain: str):
        """
        Input : query dell'utente e dominio da prioritizzare nella ricerca sul web
        Output: lista di dizionari, ogni dizionario contiene l'url scelto, il dominio corrispondente e un estratto del testo corrispondente.

        Se il dominio è definito, viene fatta la rierca sul web utilizzado il costrutto "site: domain" per selezionare i primi 2 url contenenti 
        appartenenti al dominio da prioritizzare. Successivamente, viene fatta anche una ricerca per selezionare altri url aggiuntivi, in modo da fornire poi alla 
        LLM un buon quantitativo di materiale da processare per la risposta. Tutti gli url selezionati vengono poi restituiti in un'unica lista di
        dizionari che segue un ordine gerarchico, partendo dagli url appartenenti al dominio e successivamente quelli aggiuntivi.
        """
        print(f"[TAVILY SEARCH ENGINE] Ricerca: '{query}' | Dominio: {domain}")
        results_formatted: List[Dict[str, Any]] = []

        if domain:
            print(f"[TAVILY] Ricerca specifica site:{domain}")
            # Includiamo il dominio nella query per Tavily
            search_specific = self.client.search(query=f"site:{domain} {query}", max_results=2)
            for r in search_specific.get("results", []):
                results_formatted.append({
                    "url": r["url"],
                    "title": r.get("title", "No Title"),
                    "content": r.get("content", "")
                })
        
        search_generic = self.client.search(query=query, max_results=4)
        for r in search_generic.get("results", []):
            url: str = r["url"]
            # Controllo blacklist e duplicati
            if not any(blocked in url for blocked in self.blacklist):
                if not any(res['url'] == url for res in results_formatted):
                    results_formatted.append({
                        "url": url,
                        "title": r.get("title", "No Title"),
                        "content": r.get("content", "")
                    })
        preferred = [r for r in results_formatted if any(d in r['url'] for d in self.whitelist)]
        final_data = preferred + [r for r in results_formatted if r not in preferred]

        print(f"[TAVILY] Totale risultati unificati: {len(final_data)}")
        return final_data