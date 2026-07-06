import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
import json
from fastapi import FastAPI, HTTPException, Path
from typing import List, Optional, Tuple, Dict

from pydantic import BaseModel
from backend.evaluation.metrics import Metrics
#tokenize, calcola_accuratezza, calcola_densita, calcola_noise_ratio, calcola_coverage


from urllib.parse import urlparse
from backend.parser.parser_base import BaseParser
from backend.parser.wiki_parser import WikipediaParser
from backend.parser.amazon_parser import AmazonParser
from backend.parser.nba_parser import NBAParser
from backend.parser.rottentomatoes_parser import RottenTomatoesParser
from backend.parser.fallback_parser import FallBackParser
#from backend.parser.fallback_parser import FallBackParser

#from mariadb_data.database import init_db, save_document, get_documents

"""devo aggiungere l'endpoint della chat  che prende in input una query 
chiama chunking e sciring da rag/methods.py => due metoidi per la divisione in chunks e per la selezione dei tok k chunks

passiamo ad ollama i pezzi migliori, tramite il modulo aollama_dta/ollama_script, in cui c'è il metodo di generazione della rispostsìa"""

"""endpoint chat
    - prende in input la query dell'utente
    - usa i domini definiti 
    - chiama il menìtodo di filtro delle domande in ollama_data.ollama_script.filtra_query
    - gestione delle risposte : accept, cralrify , regect
    - recupero delle fonti (magari possimo prima cercare nel database)
    - avviene la vera ricerca nel web => duckduckgo, startpage
    - si parsano i testi, iene chiamo il modulo che fa chunking e il metodo che restituisce i k paragrafi pertinenti
        definito in rag.methods.py
    - creazione della risposta, metodo definito in ollama_script per la risposta avvenuta dopo la rag
    restituiamo:
        risposta
        sources
        chunk analized 
        cama.2044010@studenti.uniroma1.it
        """

app=FastAPI()

PATH_GS_SANO = "gs_data/"
PATH_DOMAINS= "domains.json"


# Carico dinamicamente i domini supportati da domains.json
def loading_domains(PATH : str) -> List[str]:
    """Restituisce la lista dei domini supportati"""
    with open(PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data["domains"]
supported_domains : List[str] = loading_domains(PATH_DOMAINS)
print("supported: ", supported_domains)

GS_AND_HTML : Dict[str, str] = {}
URL_AND_HTML : Dict[str, str] = {}
def complete_gs():
    """Popola due dizionari che saranno le variabili globali contenenti le coppie chiave valore url - testo HTML del GoldStandard
    e le coppie chiave valore gold_text e testo HTML del Gold Standard"""
    for domain in supported_domains:
        corrected_domain = domain.replace(".", "_") + "_gs.json"
        path_file = PATH_GS_SANO + corrected_domain
        try:
            with open(path_file, "r", encoding="utf-8") as f:
                gs = json.load(f)
                for elem in gs:
                    # Salviamo url/gold_text -> html
                    URL_AND_HTML[elem["url"]] = elem["html_text"]
                    GS_AND_HTML[elem["gold_text"]] = elem["html_text"]
                    
        except Exception as e:
            print(f"Errore {domain}: {e}")

# Eseguiamo il caricamento all'avvio del server
complete_gs()


PARSERS : Dict[str, BaseParser] = {
    "en.wikipedia.org": WikipediaParser(),
    "www.amazon.it" : AmazonParser(),
    "www.nba.com" : NBAParser(),
    "editorial.rottentomatoes.com": RottenTomatoesParser()
}

#NUOVO
GENERIC_PARSER : BaseParser = FallBackParser();

METRICS : Metrics = Metrics()


class URLRequest(BaseModel):
    url : str
    domain : str
    title : str
    html_text : str
    parsed_text : str

#risultato di get domains -> una lista di stringhe per i domini supportati
class domainRequest(BaseModel):
    domains : List[str]

#risultato di get gold standard -> restituisce un'entry del Gold Standard
class goldStandardRequest(BaseModel): 
    url : str
    domain : str
    title : str
    html_text : str
    gold_text : str

#risultato di get full gold standard -> restituisce tutte le entry del Gold Standard
class fullGoldStandardRequest(BaseModel):
    gold_standard : List[goldStandardRequest]

#risultato del tokenizer
class tokenizedResult(BaseModel):
    precision : float
    recall : float
    f1 : float

# Definisce cosa deve inviare l'utente per fare la valutazione (testo parsato e testo gold)
class evaluateInputFormat(BaseModel):
    parsed_text : str
    gold_text : str


class postParseInputFormat(BaseModel):
    url : str
    html_text : str

class postParseResult(BaseModel):
    url : str
    domain : str
    title : str
    html_text : str
    parsed_text : str


#-----NUOVE METRICHE
class statisticalResult(BaseModel):
    density: float
    source: str

class noiseResult(BaseModel):
    noise_score: float
    source: str 

class coverageResult(BaseModel):
    coverage_score: float 
    source: str


#risultato di post evaluate 
class evaluationResult(BaseModel):
    token_level_eval : tokenizedResult
    statistical_eval: statisticalResult
    noise_eval: noiseResult
    coverage_eval: coverageResult 

@app.get("/parse")
async def parse(url : str) -> URLRequest:
    """
    Input : URL da cui si vuole effettuare il testo da parsare
    Output: oggetto JSON definito tramite modello Pydantic, contente url, dominio dell'url inserito, titolo del contenuto principale della pagina, HTML estratto dalla pagina web che viene fornito in
    input al parser e testo pulito restituito dal parser, pronto per essere processato da una LLM.

    Questo endpoint estrae il dominio dall'url inserito, verifica che sia uno dei domini supportati e, in caso contrario, gestisce l'errore.
    Tramite il dominio, accediamo alla variabile globale PARSER contenente le coppie chiave-valore che legano ogni dominio al suo parser specifico, definito
    nella corrispondente sottoclasse del modulo 'parser'. Accede al testo HTML locale corretto tramite la variabile globale URL_AND_HTML.

    Viene fatto il seguente controllo: match tra url di input e url trovato nel GS, e un ulteriore controllo sul dominio: se quest'ultimo
    non è en.wikipedia.org, viene fatto il parsing a partire dalla stringa HTML locale salvata nel GS, salvata come variabile locale del parser
    di riferimento. In questo modo, il parser controllera il suo valore e, se diverso da 'None', farà il parsing sulla stringa locale.

    Si opta per il controllo sul dominio invece che un semplice controllo sulla lunghezza della pagina HTML, poichè altrimenti verrebbe fatto lo scraping
    online anche per le pagine di Amazon, col rischio di essere identificati come bot dal sito. """

    domain : str = url.split("/")[2]
    if domain not in supported_domains:
        print("il problema è il dominio")
        raise HTTPException(status_code=400, detail=f"Domain '{domain}' is not a supported domain.")
    parser : BaseParser = PARSERS.get(domain)


    if url in URL_AND_HTML.keys():
        if domain != "en.wikipedia.org": #len(elem["html_text"]) < 1000000:
            parser.html_local = URL_AND_HTML.get(url)
        elif len(URL_AND_HTML.get(url)) < 1000000:
            parser.html_local = URL_AND_HTML.get(url)
    
    text : URLRequest = await parser.parse_url(url)
    if text is None:
        print("Errore durante il parsing: l'url inserito è irraggiungibile")
        raise HTTPException(status_code=400, detail="Unable to parse the URL inserted.") # se fallisce -> errore
    
    return URLRequest(
        url=url, 
        domain=text["domain"], 
        title=text["title"], 
        html_text=text["html_text"], 
        parsed_text=text["parsed_text"]
    )


@app.post("/parse")
async def parsed_output(input : postParseInputFormat) -> postParseResult:
    """ 
    Input: url su cui si vuole effettuare l'estrazione del testo e pagina HTML di riferimento.
    Output: oggetto JSON definito tramite modello Pydantic, contente url, dominio dell'url inserito, titolo del contenuto principale della pagina, HTML estratto dalla pagina web che viene fornito in
    input al parser e testo pulito restituito dal parser di riferimento, pronto per essere processato da una LLM.
    Seleziona il parser corretto in maniera automatica, in base al dominio estratto dall'url in input, ed esegue il parsing del testo
    direttamente sull'HTML fornito.
    
    Viene gestito il caso di dominio non supportato. Tramite il dominio, accediamo alla variabile globale PARSER contenente le coppie chiave-valore che legano ogni dominio al suo parser specifico, definito
    nella corrispondente sottoclasse del modulo 'parser', e otteniamo il parser corretto. 
    Tramite il suffisso 'raw', passiamo in input al parser di riferimento la stringa locale e la salviamo anche nella variabile locale 'local_html' dello stesso.
    In questo modo, il parser controllera il suo valore, diverso da 'None', farà il parsing sulla stringa locale come richiesto..
 
    """

    url_parse : str = input.url
    domain : str = input.url.split("/")[2]
    print("domain: ", domain)
    if domain not in supported_domains or not domain:
        raise HTTPException(status_code=400, detail=f"Domain '{domain}' is not a supported domain")
    parser : BaseParser = PARSERS.get(domain)

    try:
        raw_html_string : str = f"raw:{input.html_text}"
        parser.html_local = f"raw:{input.html_text}"
        res : URLRequest = await parser.parse_url(raw_html_string)

        return postParseResult(
            url = url_parse,
            domain = domain,
            title = res["title"],
            html_text = input.html_text,
            parsed_text= res["parsed_text"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Errore nel parsing da stringa html")



@app.get("/domains") 
async def get_domains() -> domainRequest: 
    """ 
    Input: ()
    Output: restituisce, sottoforma di modello Pydantic opportunamente definito, la lista dei domini supportati.

    Apre il file domains.json in lettura, ne carica il contenuto ed estrae i domini nell'entry 'domains', restituendola come lista.

    """
    with open(PATH_DOMAINS, 'r', encoding='utf-8') as f:
        data = json.load(f) 
    return domainRequest(domains=data["domains"])

@app.get("/gold_standard")
async def get_gold_standard(url : str) -> goldStandardRequest:
    """
    Input: url di cui si vuole ottenere il Gold Standard di riferimento.
    Output: oggetto JSON definito tramite modello Pydantic, contente url, dominio dell'url inserito, titolo del contenuto principale della pagina, 
    HTML della pagina web corrispondente nel GS e il 'gold_text', il testo di riferimento usato per il calcolo della precisione di estrazione del parser.

    Estrae il dominio di riferimento dall'url in input, costruisce il percorso al file JSON del Gold Standard corretto, gestendo l'errore di dominio non supportato.
    Apre il file JSON, caricandone i dati, e controlla per ogni entry del file se l'url in input vi appartiene.
    Se l'url inserito appartiene al Gold Standard, restituisce l'oggetto JSON dell corrispondete entry trovata. Altrimenti, gestisce l'errore
    di non appartenenza dell'url.
    """
    domain : str = url.split("/")[2]
    corrected_domain = domain.replace(".", "_") + "_gs.json" 
    path_file : str = PATH_GS_SANO + corrected_domain

    if domain not in supported_domains:
        raise HTTPException(status_code=400, detail=f"Domain '{domain}' is not a supported domain.")

    with open(path_file, "r", encoding="utf-8") as f:
        gold_standard_data = json.load(f)

    for entry in gold_standard_data:
        if entry["url"] == url:
            return goldStandardRequest(
                url=entry["url"], 
                domain=entry["domain"], 
                title=entry["title"], 
                html_text=entry["html_text"], 
                gold_text=entry["gold_text"]
            )
    raise HTTPException(status_code=404, detail=f"URL: '{url}' not found in the gold standard.")
            

@app.get("/full_gold_standard")
async def get_full_gold_standard(domain: str) -> fullGoldStandardRequest:
    """
    Input: dominio di riferimento
    Output: oggetto JSON definito con il corrispondente modello Pydantic, contenente tutte le entry del corrispondente Gold Standard per intero.

    Gestisce l'errore di dominio non supportato e di eventuale dominio appartenente ad un Gold Standard ma non presente tra quelli supportati. 
    Costruisce il percorso al corrispondente file del Gold Standard, e costruisce una lista contentente tutte le entry di quest'ultimo.
    """

    if domain not in supported_domains:
        raise HTTPException(status_code=400, detail=f"Domain '{domain}' is not a supported domain.")
    corrected_domain = domain.replace(".", "_") + "_gs.json"
    path_file : str = PATH_GS_SANO + corrected_domain

    with open(path_file, "r", encoding="utf-8") as f:
        gold_standard_data = json.load(f)

    risultati : List[goldStandardRequest] = []

    for entry in gold_standard_data:
        if entry["domain"] == domain and entry["domain"] not in supported_domains:
            raise HTTPException(status_code=400, detail=f"Domain '{domain}' is not a supported domain.")  
        domain_gold_standards = goldStandardRequest(
            url=entry["url"], 
            domain=entry["domain"], 
            title=entry["title"], 
            html_text=entry["html_text"], 
            gold_text=entry["gold_text"]
        )
        risultati.append(domain_gold_standards)

    return fullGoldStandardRequest(gold_standard=risultati)

@app.post("/evaluate")
async def evaluate(input : evaluateInputFormat) -> evaluationResult:
    """
    Input: tramite modello Pydantic definito, riceve l'oggetto JSON composto da testo restituito dalla pulizia del parser e testo di riferimento 
    del gold standard, pulito a mano.
    Output: restituisce per ognuna delle metriche di valutazione implementate il punteggio ottenuto, restituendo il modello Pydantic definito, contenente
    il nome della metrica utilizzata e il punteggio corrispondente.

    Per ogni dominio supportato, salviamo in una variabile locale il testo html di riferimento contenuto nel Gold Standard corrispondente al gold_text
    passato in input per poterlo utilizzare nel calcolo di una delle metriche presenti, 'calcola_densita', mentre per le altre viene utilizzato il 'gold_text'. 
    Tramite la variabile globale METRICS si accede alle metriche implementate e ne vengono salvati i risultati utilizzando, per ognuna di esse, il modello Pydantic corrispondente, 
    che permette di salvare il valore numerico di ognuno dei parametri definiti dalla metrica stessa.     
    """
    
    html_to_test : str = ""
    if input.gold_text in GS_AND_HTML.keys():
        html_to_test = GS_AND_HTML.get(input.gold_text)
    if not html_to_test:
        html_to_test = ""

    parsed_local : str = input.parsed_text
    
    result_tokenize : Dict [str, float] = METRICS.calcola_accuratezza(parsed_local, input.gold_text)
    res_stat : Dict [str, float] = METRICS.calcola_densita(parsed_local, html_to_test)
    res_noise : Dict [str, float] = METRICS.calcola_noise_ratio(parsed_local, input.gold_text)
    res_coverage : Dict [str, float] = METRICS.calcola_coverage(parsed_local, input.gold_text)
    

        

    precision : float = result_tokenize["precision"]
    recall : float = result_tokenize["recall"]
    f1 : float = result_tokenize["f1"]

    density : float = res_stat["density"]
    noise_score : float = res_noise["noise_score"]
    coverage_score : float = res_coverage["coverage_score"]
    
    t_res = tokenizedResult(precision = precision, recall=recall, f1=f1)
    s_res = statisticalResult(density=density, source= "calcola_densita - evaluate")
    n_res = noiseResult(noise_score=noise_score, source="calcola_noise_ratio - evaluate")
    c_res = coverageResult(coverage_score=coverage_score, source="calcola_coverage - evaluate")
    
    return evaluationResult(
        token_level_eval= t_res,
        statistical_eval= s_res,
        noise_eval= n_res,
        coverage_eval= c_res
    )
    

@app.get("/full_gs_eval")
async def full_gs_eval(domain : str) -> evaluationResult:
    """
    Input: dominio di riferimento per cui si vuole ottenere la valutazione completa di tutti i link del corrispondnete Gold Standard.
    Output: restituisce per ognuna delle metriche di valutazione implementate il punteggio ottenuto in media, cioè calcolato per tutti gli url di quel dominio contenuti 
    nel Gold Standard di riferimento, restituendo il modello Pydantic definito, contenente il nome delle metriche utilizzate e il punteggio medio ottenuto.

    Viene gestito il caso di dominio non supportato. Viene costruita una lista contenente, per ogni link di riferimento, l'ggetto JSON definito per contenere i risultati
    di tutte le metriche di valutazione.

    Per ogni dominio supportato, salviamo in una variabile locale il testo html di riferimento contenuto nel Gold Standard corrispondente per 
    poterlo utilizzare nel calcolo di una delle metriche presenti, 'calcola_densita', mentre per le altre viene utilizzato il 'gold_text'. 
    Tramite la variabile globale METRICS si accede alle metriche implementate e ne vengono salvati i risultati utilizzando, per ognuna di esse, il modello Pydantic corrispondente, 
    che permette di salvare il valore numerico di ognuno dei parametri definiti dalla metrica stessa.  

    Vengono creati due dizionari: gs, con chiave l'url e valore il testo 'gold', e gs_html, con chiave url e valore l'HTML della pagina, in modo da poterli utilizzare per le
    valutazioni. 
    Per ogni url nel Gold Standard viene effettuato il parsing tramite stringa html locale e viene chiamata 'evaluate', che calcola i risultati delle singole valutazioni 
    poi aggregate in apposite liste, su cui viene calcolata la media aritmetica.
    
    """

    if domain not in supported_domains:
        raise HTTPException(status_code=400, detail=f"Domain '{domain}' is not a supported domain.")
    
    all_eval : List[evaluationResult] = []
    gs : dict[str, str] = {}
    gs_html : dict[str, str] = {}
    corrected_domain= domain.replace(".", "_") + "_gs.json"
    path_file : str = PATH_GS_SANO + corrected_domain
    
    with open(path_file, "r", encoding="utf-8") as f:
        gold_standard_data = json.load(f)
        for entry in gold_standard_data:
            gs[entry["url"]] = entry["gold_text"]
            gs_html[entry["url"]]= entry["html_text"]

    parser : BaseParser = PARSERS.get(domain)
    
    for url in gs.keys():
        if domain != "en.wikipedia.org":
            parser.html_local = gs_html.get(url)
        elif len(gs_html.get(url)) < 1000000:
            parser.html_local = gs_html.get(url)

        p : URLRequest= await parser.parse_url(url)
        parsed : str = p["parsed_text"]#prendo il campo del testo parsato
        all_eval.append(await evaluate(evaluateInputFormat(parsed_text=parsed, gold_text=gs.get(url))))

    
    media_token : List[tokenizedResult] = [elem.token_level_eval for elem in all_eval]
    media_dens : List[statisticalResult] = [elem.statistical_eval for elem in all_eval]
    media_noise : List[noiseResult] = [elem.noise_eval for elem in all_eval]
    media_cov : List[coverageResult] = [elem.coverage_eval for elem in all_eval]
    
    media_precision : List[float] = [e.precision for e in media_token]
    media_recall : List[float] = [e.recall for e in media_token]
    media_f1 : List[float] = [e.f1 for e in media_token]

    m_density : List[float] = [e.density for e in media_dens]
    m_noise : List[float] = [e.noise_score for e in media_noise]
    m_cov: List[float] = [e.coverage_score for e in media_cov]

    final_token : tokenizedResult = tokenizedResult(precision=sum(media_precision)/len(media_precision), recall=sum(media_recall)/len(media_recall), f1=sum(media_f1)/len(media_f1))
    final_density = statisticalResult(density=sum(m_density)/len(m_density), source = "calcola_densita - average")
    final_noise = noiseResult(noise_score=sum(m_noise)/len(m_noise), source="calcola_noise_ratio - average")
    final_coverage = coverageResult(coverage_score=sum(m_cov)/len(m_cov), source="calcola_coverage - average")

    return evaluationResult(token_level_eval=final_token,
                            statistical_eval= final_density,
                            noise_eval= final_noise,
                            coverage_eval = final_coverage)

#nuovo endpoint
@app.get("/generic_parse")
async def generic_parse(url: str) -> URLRequest:
    """Endpoint di fallback nel generico parser se il dominio non è tra quelli supportati"""
    domain : str = url.split('/')[2];

    print(f"GENERIC PARSER | DOMAIN: '{domain}'");
    text : URLRequest = await GENERIC_PARSER.parse_url(url)
    if text is None:
        print("Errore durante il fallback parsing: l'url inserito è irraggiungibile")
        raise HTTPException(status_code=400, detail=f"Unable to parse the URL inserted [URL]: '{url}'") # se fallisce -> errore
    
    return URLRequest(
        url=url, 
        domain=text["domain"], 
        title=text["title"], 
        html_text=text["html_text"], 
        parsed_text=text["parsed_text"]
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8003)
