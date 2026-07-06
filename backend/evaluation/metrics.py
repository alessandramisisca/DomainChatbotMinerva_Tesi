import re
import string
from typing import List, Dict, Set


class Metrics:
    """
    Classe necessaria per il calcolo delle metrice di valutazione di un parser testuale.
    Grazie ad essa, è possibile confrontare il testo estratto (parsed_text) con un riferimento (gold)
    """
    def tokenize(self, text: str):
        """
        Input: prende il testo grezzo che va a ripulire attraverso le regex, rimuovendo link Markdown, citazioni tecniche e URL.
        Output: restituisce una collezione ordinata di termini (token) in minuscolo, privi di punteggiatura, filtrati e pronti per l'analisi.
        
        Questa funzione assicura che le metriche misurino il contenuto semantico del testo e non le discrepanze di formattazione.
        """

        if not text: 
            return [] 
        
        text = re.sub(r'_', '', text)
        text = re.sub(r'\[\d+\]\(#cite_note-[^)]+\)', '', text)
        
        text = re.sub(r'\[\[[0-9]+\]\]', ' ', text)

        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1 ', text)
        text = re.sub(r'\(\s*https?://(?:[^()]|\([^()]*\))*\)', ' ', text)
        text = re.sub(r'\\n|\\r', ' ', text)
        s = string.punctuation.replace('+', '')
        for char in s:
            text = text.replace(char, ' ')

        text = re.sub(r'[^\w\s\+]', ' ', text)

        tokens = text.lower().split()

        
        inutile : Set[str] = {'https', 'http', 'wikipedia', 'org', 'wiki', 'thumb', 'alt'}
        clean : List[str]= []
        for token in tokens:
            if token not in inutile:
                clean.append(token)

        return clean 

    def calcola_accuratezza(self, parsed_text: str, gold_text: str) -> dict [str, float]:
        """
        Input: prende il contenuto testuale effettivamente ottenuto dal nostro algoritmo di pulizia (parsed_text) e il contenuto testuale di riferimento (gold_text).
        Output: restituisce un dizionario che mappa i nomi delle metriche (precision, recall, f1) ai rispettivi valori numerici calcolati sulla base dei True Positives.

        Questa funzione esegue il confronto matematico tra il testo del parser e quello ideale, producendo gli indici di Precision, Recall e F1

        Metriche:

        Precision: viene calcolata rapportando il numero di token corretti trovati rispetto al totale di quelli estratti dal parser. 
        Indica la "pulizia" dell'output,  rappresentando la percentuale di parole estratte che sono effettivamente corrette e non "rumore".

        Recall: viene calcolata rapportando i token corretti rispetto al totale di quelli che avrebbero dovuto essere estratti.
        Indica la capacità di "recupero" del sistema, rappresentando la percentuale di contenuto originale del Gold Standard che il parser è riuscito a salvare senza 
        dimenticare pezzi. 

        F1-Score: è la media armonica tra Precision e Recall.
        Rappresenta l'indice di accuratezza globale e l'equilibrio generale del sistema. 
        
        Il range ottimale di tutte e tre queste metriche è > 85%, e sta a indicare che il parser ha ricostruito fedelmente il testo originale.
        """
        
        p_tokens : list[str] = self.tokenize(parsed_text) 
        g_tokens : list[str] = self.tokenize(gold_text)

        pp= set(p_tokens)
        gg= set(g_tokens)
        #print("INTRUSI: \n", pp-gg)
        #print("PERSE: \n", gg-pp)

        tp : int = len(set(p_tokens) & set(g_tokens)) 
        false_positives : int = len(set(p_tokens) - set(g_tokens)) 
        false_negatives : int = len(set(g_tokens) - set(p_tokens)) 
        #print("Ecco false_positives: ", false_positives)
        #print("Ecco false_negatives: ", false_negatives)

        if len(pp) > 0:
            precision : float = tp / len(pp)
        else:
            precision = 0.0
        if len(gg) > 0 :
            recall : float = tp / len(gg)
        else:
            recall = 0.0
        if (precision + recall) > 0:
            f1: float = (2*precision*recall) / (precision + recall)
        else: f1 = 0.0

        #print("Ecco precision: ", precision)
        #print("Ecco recall: ", recall)
        #print("Ecco f1: ", f1)
        


        return {
            "precision": precision,
            "recall": recall,
            "f1": f1
        }

    
  
    def calcola_densita(self, parsed_text: str, html_raw: str): 
        """
        Input: prende il testo finale estratto, già ripulito da tag e script (parsed_text), e l'intero codice HTML della pagina (html_raw).
        Output: restituisce l'equilibrio tra il struttura HTML e testo informativo.

        Metrica:

        Content Density: misura il rapporto tra la stringa finale prodotta dal parsere l'intera stringa HTML scaricata (comprensiva di tutto). 
        Rappresenta quanto "rumore strutturale" è stato rimosso rispetto al testo utile.

        Il range ideale per questa metrica è è 10% - 25%, ed indica un equilibrio ideale tra struttura HTML e testo informativo.
        """
        density : float = 0.0
        src : str = "calcola_densita"
        if not html_raw or len(html_raw) == 0:
                density = 0.0
        else: 
            density = len(parsed_text) / len(html_raw)
        return {
            "density": density,
            "source" : src
        }


    def calcola_noise_ratio(self, parsed_text: str, gold_text: str):
        """
        Input: prende il testo finale estratto, che potrebbe contenere residui di "sporco" (parsed_text), ed il testo ideale, che sappiamo con certezza essere
        perfettamente pulito (gold_standard).
        Output: restituisce quanto "rumore" è ancora presente nel testo finale.

        Questa funzione calcola la quantità di informazioni errate o superflue che il parser potrebbe aver erroneamente incluso nell'output.

        Metrica:

        Noise Ratio: viene calcolata come il rapporto i token estratti che non trovano riscontro nel Gold Standard, i cosiddetti (false_positives), e il totale della 
        produzione (len(p_tokens)). 
        Serve a quantificare la presenza di "sporco" o residui di codice nel testo prodotto, validando la capacità del sistema di isolare il contenuto utile. 

        Il range ottimale di questa metrica è < 5%, ed indica che meno del 5% del testo estratto è "rumore".
        """

        noise_score : float = 0.0
        src : str = "calcola_noise_ratio"

        p_tokens = set(self.tokenize(parsed_text))
        g_tokens = set(self.tokenize(gold_text))

        if not p_tokens:
            noise_score = 0.0 
        
        else:
            false_positives = len(p_tokens - g_tokens)
            noise_score = false_positives / len(p_tokens)

        return {
            "noise_score" : noise_score,
            "source" : src
        }

 
    def calcola_coverage(self, parsed_text: str, gold_text: str):
        """
        Input: prende il testo finale estratto, già ripulito da tag e script (parsed_text), ed il testo ideale, che rappresenta l'obiettivo massimo di estrazione 
        (gold_standard).
        Output: restituisce il grado di copertura del contenuto utile del testo.

        Questa funzione valuta la completezza dell'estrazione, verificando quanta parte dell'informazione del Gold Standard è stata effettivamente catturata.

        Metrica:

        Coverage: Pur essendo calcolata allo stesso modo di Recall, questa metrica, anziché concentrarsi sull’accuratezza del parser del ‘copiare tutti i termini’ 
        (aspetto microscopico), si focalizza sull’estensione del documento finale (aspetto macroscopico), misurandone l’integrità.

        Il range ottimale di questa metrica è > 90%, e sta ad indicare che nessuna sezione macroscopica del Gold Standard è stata persa. 
        """
        coverage_score : float = 0.0
        src : str = "calcola_coverage"
        p_tokens = set(self.tokenize(parsed_text))
        g_tokens = set(self.tokenize(gold_text))

        if not g_tokens:
            coverage_score = 0.0 
        else: 
            coverage_score = len(g_tokens.intersection(p_tokens)) / len(g_tokens)
        return {
            "coverage_score": coverage_score,
            "source": src
        }

    