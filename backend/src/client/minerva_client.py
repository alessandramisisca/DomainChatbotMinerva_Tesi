import requests
import logging
from typing import Optional, List, Set
from urllib.parse import urlparse
"""PROVA
    OGNI VOLTA CHE IL NUOVO SERVER_CHATBOT HA BISOGNO DI PARSARE I TESTI CHIAMANDO IL PARSER IN SERVER_CHATBOT.PY gli basta ciamare
    le funzioni definite ne file minerva_client.py
    Sa dove andare a cercare il parser (usando l'URL del servizio Docker http://minerva_old_parser:8003)
    Il parser risponde con dati grezzi (JSON). Il client riceve questi dati, estrae solo la parte che serve (il testo pulito) e la restituisce al chatbot in un formato pronto all'uso.
    Se il servizio di parsing è spento o non risponde, il client non lascia che il chatbot vada in crash. Invece, cattura l'errore (con un blocco try/except) e restituisce un valore "sicuro" (None), 
    permettendo al chatbot di gestire la situazione con un messaggio d'errore.
    Permette di testare il parsing in isolamento rispetto alla chat.
    """
   

class MinervaClient:
    def __init__(self, base_url: str = "http://minerva_old_parser:8003"):
        self.base_url = base_url
        # User-Agent specifico per evitare blocchi
        self.headers = {"User-Agent": "MinervaChatbot/1.0"}

        #creo un dizionario contenente come chiave i nostri domini supporatti, e come valore il tipo di parsing
        #nel caso dei domini supportati, viene usato il parsing già implementato, nel caso di url generici viene fatta la chiamata al nuovo endpoint che gestitsce ilparsing di url fupri dal dominio
        self.SUPPORTED_DOMAINS : Set[str] = {
            "en.wikipedia.org" : "parse",
            "editorial.rottentomatoes.com": "parse",
            "www.nba.com" : "parse",
            "www.amazon.it" : "parse"
        }
    
    def fetch_context_from_urls(self, urls: List[str], use_cache: bool = True) -> str:
        """
        Aggrega tutti i testi parsati in un unico contesto per la RAG.
        Metodo orchestratore per il ChatLogic.
        Integra parsing e eventuale logica di cache
        
        """
        results = self.get_parsed_text_from_urls(urls)
        # sto resttuendo l'elenco di fonte + url
        return "\n\n".join([f"Fonte: {u}\n{t}" for u, t in results])
    
    def get_parsed_text_from_urls(self, urls: list[str]) -> list[tuple[str, str]]:
        """Lo chiamo nel server chatbot per chiamare, per ogni url, il parser piu adeguato
        Results: è una lista vuota che conterrà le coppie formate da url e testo estratto dall'url
        
        Per ogni url di quelli in input, che sono quelli recuperti dalla ricerca web, controllo il dominio di appartenenza con il metodo in_supported_domains"""
        results :list[tuple[str, str]] = []
        for url in urls:
            # La logica del dominio è interna al client
            parsed_text : str = self.parse_url(url)
            if parsed_text:
                results.append((url, parsed_text))
        return results

    
    def parse_url(self, url: str) -> Optional[str]:
        """
        Esegue il parsing di un URL. In base al dominio estratto, scelgo il parser
        """
        domain : str = urlparse(url).hostname #estraggo l'hostname dell'url
        # Recupera l'endpoint da chiamare nel serve.py in base al dizionario dei domini supportati. Se il dominio non c'è, usa 'generic_parse', l'endpoint che chiama il parser generico
        endpoint_server = self.SUPPORTED_DOMAINS.get(domain, "generic_parse")
        if endpoint_server == "generic_parse":
            print(f"DEBUG: Uso parser generico per il dominio: {domain}")
        #costruisco l'url per chiamare il metodo parse o generic_parse dentro server.py (la chiamata api sostanzialmente)
        endpoint = f"{self.base_url}/{endpoint_server}"
        
        try:
            response = requests.get(
                endpoint, 
                params={"url": url}, 
                headers=self.headers, 
                timeout=120
            )
            
            if response.status_code == 200:
                return response.json().get("parsed_text")
            
            print(f"PARSER | Error {response.status_code} per {url}")
            return None
            
        except requests.exceptions.RequestException as e:
            print(f"Errore di connessione a PARSER: {e}")
            return None
