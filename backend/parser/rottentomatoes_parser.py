from backend.parser.parser_base import BaseParser
from bs4 import BeautifulSoup
from typing import List, Dict
from crawl4ai import AsyncWebCrawler, CrawlResult, CacheMode



class RottenTomatoesParser(BaseParser):
    """
     Ogni sottoclasse presenta 4 variabili, ciascuna contenente elementi specifici per il dominio assegnato:
    
    - targets: è una lista di specifici tag, contenenti i blocchi di informazioni principali da estrarre dalla pagina html.
    - css_exclusions: è una stringa di tag che rappresentano i selettori contenenti gli elementi superflui (banner pubblicitari, menù di navigazione, riferimenti, fonti esterne e così via).
    - general_markdown_options : è un dizionario che indica al motore di generazione quali elementi eliminare o mantenere nel testo.
    - markdown_inutile: è una lista di eventuali elementi residui nel testo utile.
    
    In ogni sottoclasse, tramite il metodo costruttore, viene dunque implementato un crawler apposito per ogni dominio di riferimento. 
    """

    RT_TARGETS : List[str] = [ ".article", ".article_body", "div.content-body", "h2.content-subtitle", "figure-wp-block-table", "table", "tr", "td" ]
    RT_EXCLUSIONS: str = ''' 
            footer, nav, header, rt-ads, .ad-unit, #top-navigation, .article_sidebar, .social-share, 
            .editorial-video-player, .newsletter-signup, .media-credit.image-text,  post-meta,
            a[href*="apple.com"], a[href*="tiktok.com"], a[href*="instagram.com"], a[href*="spotify.com"], a[href*="itunes.com"], a[href*="youtube.com"],
            a[href*="iheartradio.com"], a[href*="castbox.com"], a[href*="castro.com"], a[href*="deezer.com"], a[href*="goodpods.com"], a[href*="listennotes.com"], a[href*="overcast.com"],
            a[href*="pandora.com"], a[href*="pocketcasts.com"], a[href*="podcastaddict.com"], a[href*="podcast.com"], h1[style*='center'], div[style*='center'], span.media-credit, div[class*="sidebar-section"],
            div.nav-layout, rt-trending-bar
            '''
    RT_MARKDOWN_OPTIONS : Dict[str, bool] = { 
        'ignore_images': True, 
        'escape_html': True,
        'ignore_links': True}

    RT_MARKDOWN_INUTILE : List[str]= [ 
        "## ADVERTISEMENT", "## RELATED NEWS", "## MORE WEEKEND BOX OFFICE", " ## MOVIE & TV NEWS", "## MORE NEWS",
        "Seen on the Screen is a Universal Entertainment", "Claim your ticket to witness the personal narratives",
        "Get the freshest reviewes", "On an Apple Device?", "Follow Seen on the Screen"
    ]

    RT_GEN_EXCLUDED_TAGS : List[str] = ['nav', 'script', 'style', 'img', 'noscript', 'figure', 'meta', 'cite', 'link', 'audio']

    RT_MODE : CacheMode = CacheMode.BYPASS

    def __init__(self):
        super().__init__(
            targets = self.RT_TARGETS,
            css_exclusions = self.RT_EXCLUSIONS,
            gen_excluded_tags = self.RT_GEN_EXCLUDED_TAGS,
            general_markdown_options = self.RT_MARKDOWN_OPTIONS,
            markdown_inutile = self.RT_MARKDOWN_INUTILE,
            mode = self.RT_MODE
        )
        self.html_local : str = None
        
                
    
    def clean_text(self, markdown_text: str) -> str:
        """
        Input: Il testo converitto in Markdown dal crawler, che può ancora contenere bibliografie o footer non filtrati dei selettori CSS.
        Output: Il corpo del testo pulito, pronto per l'analisi.

        Questo metodo prende in input il testo in formato markdown e lo pulisce da eventuali elementi residui non catturati dalle esclusioni css coerenti con la lista 
        'markdown_inutile'.
        """

        if not markdown_text:
            return ""
        remove : list[str] = self.markdown_inutile
        
        for elem in remove:
            if elem in markdown_text:
                markdown_text= markdown_text.split(elem)[0] #prendo utto cio che viene prima
        return markdown_text.strip()


    def extract_title(self, soup: BeautifulSoup) -> str:
        """
        Input: L'oggetto BeautifulSoup generato dall'HTML, che permette una navigazione strutturata dei tag.
        Output : restituisce il titolo estratto dalla pagina html.

        Questo metodo prende in input un oggetto della classe BeautifulSoup, che cattura la pagina html caricata dal crawler, e tramite il metodo “soup.find” estrae 
        il tag specifico, diverso per ogni dominio, contenente il titolo della pagina web corrente.
        """

        elem_titolo = soup.find('h1', class_='article_title') 

        if not elem_titolo:
            elem_titolo = soup.find('h1', attrs={"slot": "title"})
        
        if elem_titolo:
            return elem_titolo.get_text(strip=True)
        
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        
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

                result_value : bool = result.success

                if (not result.markdown.raw_markdown or not result_value):
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

       
        