from abc import ABC, abstractmethod
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, DefaultMarkdownGenerator, CrawlResult
import json
import re
from bs4 import BeautifulSoup
from typing import List, Dict

class BaseParser(ABC):
    """
    La classe astratta BaseParser definisce la logica generale seguita nel parsing dei siti web dei domini assegnati. 
    
    Essa configura il WebBrowser in modo che si occupi della gestione della memoria e che eviti un eventuale rischio di essere identificati come “bot” da parte dei siti 
    web visitati e, in quanto tali, il blocco della visita stessa utilizzando un “User-Agent”.
    
    BaseParser delega ad ogni sottoclasse, una specifica per ogni dominio, la gestione delle relative pagine web.
    
    Ogni sottoclasse presenta 4 variabili, ciascuna contenente elementi specifici per il dominio assegnato:
    
    - targets: è una lista di specifici tag, contenenti i blocchi di informazioni principali da estrarre dalla pagina html.
    - css_exclusions: è una stringa di tag che rappresentano i selettori contenenti gli elementi superflui (banner pubblicitari, menù di navigazione, riferimenti, fonti esterne e così via).
    - general_markdown_options : è un dizionario che indica al motore di generazione quali elementi eliminare o mantenere nel testo.
    - markdown_inutile: è una lista di eventuali elementi residui nel testo utile.
    
    In ogni sottoclasse, tramite il metodo costruttore, viene dunque implementato un crawler apposito per ogni dominio di riferimento. 
    
    """
    def __init__(self, targets: List[str], css_exclusions: str, gen_excluded_tags: List[str], general_markdown_options: Dict[str, bool], markdown_inutile: List[str], mode : CacheMode = CacheMode.BYPASS):
        self.browser_cfg = BrowserConfig(headless = True,
                                         user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                         extra_args=[
                                        "--disable-gpu", 
                                        "--disable-http2", 
                                        "--disable-dev-shm-usage",  # Crucial for memory management
                                        "--no-sandbox",             # Reduces overhead
                                        "--disable-extensions",
                                        "--js-flags=--max-old-space-size=512" # Limits JS heap size
                                    ])

        self.markdown_inutile = markdown_inutile

        self.crawler_cfg = CrawlerRunConfig( 
            target_elements= targets,
            excluded_selector= css_exclusions,
            excluded_tags= gen_excluded_tags,
            markdown_generator= DefaultMarkdownGenerator(options= general_markdown_options),
            cache_mode = mode,
            remove_forms= True, 
            only_text= False,
            remove_consent_popups= True
        )
        
        self.html_local : str = ""
    
    @abstractmethod
    def extract_title(self, soup : BeautifulSoup) -> List[str]:
        """
        Input: L'oggetto BeautifulSoup generato dall'HTML, che permette una navigazione strutturata dei tag.
        Output : restituisce il titolo estratto dalla pagina html.

        Questo metodo prende in input un oggetto della classe BeautifulSoup, che cattura la pagina html caricata dal crawler, e tramite il metodo “soup.find” estrae 
        il tag specifico, diverso per ogni dominio, contenente il titolo della pagina web corrente.
        """
        pass
    
    @abstractmethod
    def clean_text(self, markdown_text: str) -> str:
        """
        Input: Il testo converitto in Markdown dal crawler, che può ancora contenere bibliografie o footer non filtrati dei selettori CSS.
        Output: Il corpo del testo pulito, pronto per l'analisi.

        Questo metodo prende in input il testo in formato markdown e lo pulisce da eventuali elementi residui non catturati dalle esclusioni css coerenti con la lista 
        'markdown_inutile'.
        """
        pass

    @abstractmethod
    async def parse_url(self, url : str) -> dict[str, str] | None:
        """
        Input: prende l'indirizzo web da cui estrarre i dati.
        Output: restituisce in output un dizionario con tutte le informazioni che verranno poi restituite nell’endpoint “/parse”. 

        
        Questo metodo costruisce il testo finale estratto dalla pagina web. 
        Naviga sulla pagina, esegue l’estrazione del testo utile utilizzando il crawler specifico per ogni sottoclasse, ed effettua un controllo sul 
        testo in formato markdown estratto. 
        
        Il risultato grezzo viene mandato in input al metodo extract_title per estrarre il titolo, che viene aggiunto al contenuto principale, e poi viene
        invocata la funzione di pulizia che applica la rimozione delle sezioni residue.
        
        """

        pass

    
    def clean_raw_html(self, raw_html: str) -> str:
        """
        Input: prende la stringa contenente il codice HTML della pagina (raw_html).
        Output: restituisce una versione 'alleggerita' e filtrata dell' HTML, per evitare che il crawler elabori inutilmente elementi non importanti.
        
        Questo metodo elimina pezzi interi di codice HTML per facilitare il lavoro del crawler, che, in questo modo, evita di 'vedere' parti di pagina non utili.
        L'abbiamo implementato per gestire, in particolare, il testo HTML di Wikipedia, molto pesante e 'sporco', per alleggerirlo e filtrarlo un po' prima ancora 
        di darlo in input al crawler.
        
        """
        pass
