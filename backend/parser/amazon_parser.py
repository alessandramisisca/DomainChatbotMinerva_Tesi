from parser.parser_base import BaseParser
from bs4 import BeautifulSoup
from typing import List, Dict 
from crawl4ai import AsyncWebCrawler, CrawlResult, BrowserConfig, CacheMode
import re



class AmazonParser(BaseParser):
    """
     Ogni sottoclasse presenta 4 variabili, ciascuna contenente elementi specifici per il dominio assegnato:
    
    - targets: è una lista di specifici tag, contenenti i blocchi di informazioni principali da estrarre dalla pagina html.
    - css_exclusions: è una stringa di tag che rappresentano i selettori contenenti gli elementi superflui (banner pubblicitari, menù di navigazione, riferimenti, fonti esterne e così via).
    - general_markdown_options : è un dizionario che indica al motore di generazione quali elementi eliminare o mantenere nel testo.
    - markdown_inutile: è una lista di eventuali elementi residui nel testo utile.
    
    In ogni sottoclasse, tramite il metodo costruttore, viene dunque implementato un crawler apposito per ogni dominio di riferimento. 
    """

    AMAZON_TARGETS : List [str] = ["#productDescription", "#feature-bullets", "#detailBullets_feature_div", "#productDetails_db_sections", "#productDetails_feature_div",
                "#importantInformation_feature_div", "#detailBulletsWrapper_feature_div", "#bookDescription_feature_div", "#importantInformation_feature_div", "#buffet-disclaimer-content", 
                "#whatsInTheBoxDeck", "#bylineInfo_feature_div", "#a-truncate-cut"]


    AMAZON_EXCLUSIONS : str = '''
        #nav-belt, #nav-main, #footer, #rightCol, .a-carousel-container,
        .ad-container, #upsell_variables, #action-panel-container, #desktop-dp-ads_res, #shareLink_feature_div, #customerReviews, #averageCustomerReviews, .a-icon-star, #acrCustomerReviewText, .a-icon-alt,
        #SalesRank, .a-price, #submit.add-to-cart, #attach-desktop-sideSheet, #ask_lazy_load_div, .a-form-actions, .a-popover-preload
        '''
    
    AMAZON_MARKDOWN_OPTIONS : Dict[str, bool]= {
        'ignore_images': True, 
        'escape_html': True,
        'ignore_links': False
    }

    AMAZON_MARKDOWN_INUTILE  : List [str] = ["## Descrizione prodotto", "## Recensioni clienti", "## I clienti dicono", "## Prodotti correlati a questo articolo", "## Recensisci questo prodotto", "## Recensioni migliori da Italia", "## Del marchio"]

    AMAZON_GEN_EXCLUDED_TAGS : List[str] = ['nav', 'script', 'style', 'img', 'noscript', 'figure', 'meta', 'cite', 'link', 'audio']
    
    AMAZON_MODE : CacheMode = CacheMode.BYPASS
    

    def __init__(self):
        super().__init__(
            targets = self.AMAZON_TARGETS,
            css_exclusions = self.AMAZON_EXCLUSIONS,
            gen_excluded_tags = self.AMAZON_GEN_EXCLUDED_TAGS,
            general_markdown_options = self.AMAZON_MARKDOWN_OPTIONS,
            markdown_inutile = self.AMAZON_MARKDOWN_INUTILE,
            
        )
        self.browser_cfg = BrowserConfig(headless = True,
                                         user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                         extra_args=["--lang=it-IT,it;q=0.9"],
                                         headers={"Accept-Language":"it-IT,it;q=0.9"})
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
        remove : List[str] = self.markdown_inutile
        
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

        elem_titolo = soup.find('span', id='productTitle') #se trova il tag html h1 usa questo, altrimenti
        if elem_titolo:
           return elem_titolo.get_text(strip=True) #.get_text estrae solo il testo che sta nei tag html <title>, strip=True rimuove spazi, \n o \t
        h1= soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
    
        return "Titolo Unknown"
    
    def clean_raw_html(self, raw_html: str) -> str:
        """
        Input: prende la stringa contenente il codice HTML della pagina (raw_html).
        Output: restituisce una versione 'alleggerita' e filtrata dell' HTML, per evitare che il crawler elabori inutilmente elementi non importanti.
        
        Questo metodo elimina pezzi interi di codice HTML per facilitare il lavoro del crawler, che, in questo modo, evita di 'vedere' parti di pagina non utili.
        L'abbiamo implementato per gestire, in particolare, il testo HTML di Wikipedia e di Amazon, molto pesante e 'sporco', per alleggerirlo e filtrarlo un po' prima ancora 
        di darlo in input al crawler.
        
        """

        raw_html = re.sub(r'<head>.*?</head>', '', raw_html, flags=re.DOTALL)
        raw_html = re.sub(r'<script.*?>.*?</script>', '', raw_html, flags=re.DOTALL)
        raw_html = re.sub(r'<style.*?>.*?</style>', '', raw_html, flags=re.DOTALL)
        raw_html = re.sub(r'', '', raw_html, flags=re.DOTALL)
        return raw_html
        

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
        

        target_to_crawl : str= url 

        if self.html_local:
            print("\nUSO LA STRINGA HTML LOCALE")
            target_to_crawl = f"raw:{self.html_local}"
            

        else:
            target_to_crawl = url

        async with AsyncWebCrawler(config = self.browser_cfg) as crawler:
                self.crawler_cfg.wait_for="body"
                self.crawler_cfg.delay_before_return_html= 2.0
                cleaned_html : str = self.clean_raw_html(target_to_crawl)
                result : CrawlResult = await crawler.arun(url=cleaned_html, config=self.crawler_cfg)

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