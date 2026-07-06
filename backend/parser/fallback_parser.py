"""parser generico per fare fallbacke della ricerca nel caso di dominio n on supportato"""
from parser.parser_base import BaseParser
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, DefaultMarkdownGenerator, CrawlResult
from bs4 import BeautifulSoup
from typing import List, Dict


class FallBackParser(BaseParser):
    """
     Ogni sottoclasse presenta 4 variabili, ciascuna contenente elementi specifici per il dominio assegnato:
    
    - targets: è una lista di specifici tag, contenenti i blocchi di informazioni principali da estrarre dalla pagina html.
    - css_exclusions: è una stringa di tag che rappresentano i selettori contenenti gli elementi superflui (banner pubblicitari, menù di navigazione, riferimenti, fonti esterne e così via).
    - general_markdown_options : è un dizionario che indica al motore di generazione quali elementi eliminare o mantenere nel testo.
    - markdown_inutile: è una lista di eventuali elementi residui nel testo utile.
    
    In ogni sottoclasse, tramite il metodo costruttore, viene dunque implementato un crawler apposito per ogni dominio di riferimento. 

    """
    FALLBACK_TARGETS: List[str] = [
        "main",
        "article",
        "div[class*='content']",
        "div[id*='content']",
        "body"
    ]

    FALLBACK_EXCLUSIONS: str = '''
        nav, footer, header, aside, .sidebar, #sidebar, .menu, #menu, .nav, .footer, .header, .ads,
        .advertising, .banner, .pop-up, .modal, [class*="cookie"], [id*="cookie"], [class*="share"], [class*="social"],
        script, style, noscript, iframe, .infobox, .sinottico, .mw-editsection, .mw-references-wrap, .mw-references-columns,
        .CdA, .mw-empty-elt, .hatnote, .avviso, .avviso-contenuto, .vedi-anche, .mw-file-description, .mw-file-element, .navigation-not-searchable, 
        .col-begin[role="presentation"], .unsortable, .flagicon, .noviewer, .box-Unreferenced_section, .ambox-Unreferenced, .gallery, .mw-gallery-traditional,
        .thumb, .audio-pronunciation, .media-player-container, .ext-mw-video-interface, .sinottico-divisione, .sinottico-testata, .sinottico-testo-centrale, .reflist,
        .navbox, .vertical-navbox, .side-box, .printfooter, .metadata, .catlinks, table.sidebar, table.infobox
    '''

    FALLBACK_MARKDOWN_OPTIONS: Dict[str, bool] = {
        "ignore_links": True,
        "ignore_images": True,
        'escape_html': True,
        "body_width": 0
    }

    FALLBACK_MARKDOWN_INUTILE: List[str] = [
        "Torna su",
        "Condividi su",
        "Cookie Policy",
        "Privacy Policy",
        "## Altri progetti"
    ]

    
    FALLBACK_GEN_EXCLUDED_TAGS: List[str] = ['footer', 'header', 'aside', 'nav', 'script', 'style', 'img', 'noscript', 'figure', 'meta', 'cite', 'link', 'audio']



    def __init__(self):
        # super().__init__(
        #     targets = self.FALLBACK_TARGETS,
        #     css_exclusions = self.FALLBACK_EXCLUSIONS,
        #     gen_excluded_tags= self.FALLBACK_GEN_EXCLUDED_TAGS,
        #     general_markdown_options = self.FALLBACK_MARKDOWN_OPTIONS,
        #     markdown_inutile = self.FALLBACK_MARKDOWN_INUTILE,
        #     mode = CacheMode.BYPASS
        # )

        self.crawler_cfg = CrawlerRunConfig(
            target_elements= self.FALLBACK_TARGETS,
            excluded_selector= self.FALLBACK_EXCLUSIONS,
            excluded_tags= self.FALLBACK_GEN_EXCLUDED_TAGS,
            markdown_generator= DefaultMarkdownGenerator(options= self.FALLBACK_MARKDOWN_OPTIONS),
            cache_mode = CacheMode.BYPASS,
            remove_forms= True, 
            only_text= False,
            remove_consent_popups= True,
            process_iframes=False,           
            remove_overlay_elements=True,    
            wait_for=None,                   
            page_timeout=30000,              
            word_count_threshold=10,
            js_code="window.stop();"
        )   

        self.browser_cfg = BrowserConfig(headless = True,
                                         user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                         extra_args=[
                                            "--disable-blink-features=AutomationControlled",
                                            "--disable-extensions",
                                            "--disable-gpu",              # Alleggerisce il rendering
                                            "--blink-settings=imagesEnabled=false", # NON caricare immagini (risparmia banda)
                                            "--disable-dev-shm-usage"
                                            "--proxy-server='direct://'"
                                            "--no-sandbox"
                                        ])
           
        self.html_local : str = ""
        
    def clean_text(self, markdown_text: str) -> str:
        """
        Input: Il testo converitto in Markdown dal crawler, che può ancora contenere bibliografie o footer non filtrati dei selettori CSS.
        Output: Il corpo del testo pulito, pronto per l'analisi.

        Questo metodo prende in input il testo in formato markdown e lo pulisce da eventuali elementi residui non catturati dalle esclusioni css coerenti con la lista 
        'markdown_inutile'.
        """

        if not markdown_text:
            return ""
        remove : List[str] = self.FALLBACK_MARKDOWN_INUTILE
        
        for elem in remove:
            if elem in markdown_text:
                markdown_text= markdown_text.split(elem)[0]
        return markdown_text.strip()
        

    def extract_title(self, soup: BeautifulSoup) -> str:
        """
        Input: L'oggetto BeautifulSoup generato dall'HTML, che permette una navigazione strutturata dei tag.
        Output : restituisce il titolo estratto dalla pagina html.

        Questo metodo prende in input un oggetto della classe BeautifulSoup, che cattura la pagina html caricata dal crawler, e tramite il metodo “soup.find” estrae 
        il tag specifico, diverso per ogni dominio, contenente il titolo della pagina web corrente
        """

        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text(strip=True)
        
        return "Titolo Unknown"
    
    
    async def parse_url(self, url: str) -> Dict[str, str] | None:
        """
        Input: prende l'indirizzo web da cui estrarre i dati.
        Output: restituisce in output un dizionario con tutte le informazioni che verranno poi restituite nell’endpoint “/parse”. 

        Questo metodo costruisce il testo finale estratto dalla pagina web.
        Naviga sulla pagina, esegue l’estrazione del testo utile utilizzando il crawler specifico per ogni sottoclasse, ed effettua un controllo sul 
        testo in formato markdown estratto. 
        
        Il risultato grezzo viene mandato in input al metodo extract_title per estrarre il titolo, che viene aggiunto al contenuto principale, e poi viene
        invocata la funzione di pulizia che applica la rimozione delle sezioni residue.
        Il metodo “parse_url” costruisce dunque il testo finale estratto dalla pagina web.
        """

        target_to_crawl : str = url 

        if self.html_local:
            print("\nUSO LA STRINGA HTML LOCALE")
            target_to_crawl = f"raw:{self.html_local}"

        else:
            target_to_crawl = url
        
        async with AsyncWebCrawler(config = self.browser_cfg) as crawler:
                result : CrawlResult = await crawler.arun(url=target_to_crawl, config=self.crawler_cfg)

                # Controlliamo subito se il crawler ha segnalato un fallimento drastico
                if not result or not result.success:
                    print(f"[FALLBACK PARSER] Errore di scraping sull'URL: {url}")
                    self.html_local = None 
                    return None

                # Controlliamo in sicurezza se l'oggetto markdown o il testo estratto sono vuoti
                if not result.markdown or not getattr(result.markdown, 'raw_markdown', None):
                    print(f"[FALLBACK PARSER] Contenuto Markdown assente o non estraibile per: {url}")
                    self.html_local = None 
                    return None

                soup = BeautifulSoup(result.html, 'html.parser')
                title : str = self.extract_title(soup)
                final_markdown : str = f"# {title}\n" + result.markdown.raw_markdown
                final_markdown = self.clean_text(final_markdown)

                self.html_local = None 
                


                res : dict [str, str] = {
                    "url": url,
                    "domain": url.split("/")[2],
                    "title" : title,
                    "html_text": result.html,
                    "parsed_text": final_markdown
                    }

                return res
