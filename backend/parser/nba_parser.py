from parser.parser_base import BaseParser
from bs4 import BeautifulSoup
from typing import List, Dict
import os
from crawl4ai import AsyncWebCrawler, CrawlResult, CacheMode


class NBAParser(BaseParser):
    """
     Ogni sottoclasse presenta 4 variabili, ciascuna contenente elementi specifici per il dominio assegnato:
    
    - targets: è una lista di specifici tag, contenenti i blocchi di informazioni principali da estrarre dalla pagina html.
    - css_exclusions: è una stringa di tag che rappresentano i selettori contenenti gli elementi superflui (banner pubblicitari, menù di navigazione, riferimenti, fonti esterne e così via).
    - general_markdown_options : è un dizionario che indica al motore di generazione quali elementi eliminare o mantenere nel testo.
    - markdown_inutile: è una lista di eventuali elementi residui nel testo utile.
    
    In ogni sottoclasse, tramite il metodo costruttore, viene dunque implementato un crawler apposito per ogni dominio di riferimento. 

    """
    
    NBA_TARGETS : List[str] = [ "article", "div[class*='ArticleText']", "div[class*='StoryText']", "section[class*='ArticleContent_article']"]      #con story text lakers passa da 6 a 8 false p,  con main article torna a 6
    
    NBA_EXCLUSIONS : str = '''
            nav, footer, div.wp-caption, [class*='latest'], [class*='Latest'],
            [class*='related'], [class*='Related'], [class*='ads'], [class*='Ads'], time, #onetrust-banner-sdk, [class*='Store'],
            aside, [class*='Injury'], [class*='Fantasy'], [class*='sidebar'], 
            [class*='Sidebar'], [class*='Scoreboard'], [class*='Scoreboard'],
            [class*='ArticleAuthor'], [class*='Breadcrumbs'], [class*='promo'], [class*='Promo'],
            [class*='ArticleHeader_ahCategory']
    '''

    NBA_MARKDOWN_OPTIONS : Dict[str, bool]= {
        'ignore_images': True, 
        'escape_html': True,
        'ignore_links': False
    }

    NBA_MARKDOWN_INUTILE : List[str] = [
        "## LATEST", "## RELATED", "## TOP STORIES", "## FANTASY", "## NBA NEWS"    
    ]

    NBA_GEN_EXCLUDED_TAGS : List[str] = ['nav', 'script', 'style', 'img', 'noscript', 'figure', 'meta', 'cite', 'link', 'audio']

    def __init__(self):
        super().__init__(
            targets = self.NBA_TARGETS,
            css_exclusions = self.NBA_EXCLUSIONS,
            gen_excluded_tags= self.NBA_GEN_EXCLUDED_TAGS,
            general_markdown_options = self.NBA_MARKDOWN_OPTIONS,
            markdown_inutile = self.NBA_MARKDOWN_INUTILE,
            mode = CacheMode.BYPASS
        )
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
        remove : List[str] = self.markdown_inutile
        
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

        elem_titolo = soup.select_one("h1[class*='ArticleHeader_headerTitle']")

        if elem_titolo:
           return elem_titolo.get_text(strip=True) #.get_text estrae solo il testo che sta nei tag html <title>, strip=True rimuove spazi, \n o \t
        h1= soup.find('h1')
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
