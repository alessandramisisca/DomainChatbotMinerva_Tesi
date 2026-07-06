from sentence_transformers import SentenceTransformer
import numpy as np
import threading

_EMBEDDING_INSTANCE = None  #conterrà l'istanza
_EMBEDDING_LOCK = threading.Lock() #threading.Lock Serve a bloccare temporaneamente l'accesso agli altri thread

#vector db in menmoria volatile + threadsafe, trasforma i chunk di testo in vettori matematici(embedding), memorizza nel db e
#ci permette di cercare testi piu rilevant rispetto alla domanda dell'utente usando la similarità del coseno

#garantiamo che il modello llm scelto venga caricato una volta sola all'inizio dell'applicazione
#Double-Checked Locking Singleton: quando un modulo richiede il database vettoriale, chiama questa funzione
def get_embedding_module():
    """Singleton for EmbeddingModule."""
    global _EMBEDDING_INSTANCE
    if _EMBEDDING_INSTANCE is None: #se l'istanza esiste, la restituisce subito, altrimenti entriamo nell'if
        with _EMBEDDING_LOCK:    #acquisiamo il lock per impedire a due thread diversi due istanze distinte del modello
            if _EMBEDDING_INSTANCE is None:
                _EMBEDDING_INSTANCE = EmbeddingModule()
    return _EMBEDDING_INSTANCE


class EmbeddingModule:
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small", threshold: float = 0.80):
        print(f"[EmbeddingModule] Loading model: {model_name}")
        self.model = SentenceTransformer(model_name) #per scaricare/caricare in memoria il modello di embedding
        print("[EmbeddingModule] Model loaded")
        self.threshold = threshold #soglia per la somiglianza
        self.vectors = [] #vettori numerici
        self.chunks = [] 
        self._lock = threading.Lock() #lucchetto locale alla classe per proteggere le liste vectors e chunks da modifiche simultanee

    def clear(self):
        """Svuota la memoria volatile (il vector db locale) prima di processare una nuova richiesta."""
        with self._lock:
            self.vectors = []
            self.chunks = []

    def encode(self, texts: list, is_query: bool = False) -> np.ndarray:
        """
        Trasforma i testi in vettori con il prefisso E5 appropriato (se il testo è una domanda dell'utente, va preceduto da "query: ".
        Se è un documento da indicizzare va preceduto da "passage: ".)
        Chiamata interna a SentenceTransformers che esegue il calcolo matematico vero e proprio, restituendo un array NumPy bidimensionale.
        """
        prefix = "query: " if is_query else "passage: "
        processed_texts = [f"{prefix}{t}" for t in texts]
        return self.model.encode(processed_texts)
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        Calcola la cosine similarity per due singoli vettori: misura l'angolo tra i vettori nello spazio multi-dimensionale. 
        Più l'angolo è "stretto", più i vettori sono vicini (valore vicino a 1.0).
        -> np.dot (prodotto scalare)
        -> np.linalg.norm (la lunghezza geometrica dei vettori)
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 * norm2 == 0:
            return 0.0
        return float(dot_product / (norm1 * norm2))
    
    def _calculate_cosine_similarity(self, all_vecs: np.ndarray, query_vec: np.ndarray) -> np.ndarray:
        """
        Versione più veloce: confronta l'intero blocco di tutti i vettori nel database (all_vecs) con il singolo vettore della domanda 
        (query_vec) in un colpo solo.
            -> np.dot(all_vecs, query_vec.T): Moltiplica la matrice dei documenti per il vettore query trasposto.
            -> np.linalg.norm(all_vecs, axis=1): Calcola la norma di tutti i vettori riga contemporaneamente.
            -> np.divide(..., where=denominator != 0): Esegue la divisione finale gestendo in modo sicuro l'eventualità che una norma sia zero (evitando il crash da DivisionByZero e inserendo uno 0.0 al suo posto). 
        Restituisce un array NumPy con tutti i punteggi di somiglianza.
        """
        dot_product = np.dot(all_vecs, query_vec.T).flatten()
        norm_a = np.linalg.norm(all_vecs, axis=1)
        norm_b = np.linalg.norm(query_vec)
        denominator = norm_a * norm_b
        return np.divide(dot_product, denominator, out=np.zeros_like(dot_product), where=denominator != 0)

    def add_documents(self, chunks: list):
        """
        Riceve una lista di chunks: calcola i loro embedding chiamando self.encode (operazione che richiede tempo ma fuori dal lock, così non blocca gli altri thread), 
        dopodiché entra nel blocco protetto "with self._lock" e appende in modo sincrono elementi e vettori nelle rispettive liste speculari -> evitiamo sovrapposizioni tra possibili scritture multiple
        """
        if not chunks: return
        embeddings = self.encode(chunks, is_query=False)
        with self._lock:
            for i, emb in enumerate(embeddings):
                self.vectors.append(emb)
                self.chunks.append(chunks[i])

    def search(self, query: str, top_k: int = 3) -> list:
        """
        La stringa viene trasformata in un vettore usando il prefisso query: . 
        I vettori in memoria vengono convertiti in un array strutturato NumPy (all_vectors). Viene invocata _calculate_cosine_similarity, e
        viene prodotta una lista di numeri decimali (es: [0.85, 0.43, 0.91, 0.12]). Con np.where(similarities >= self.threshold)[0], 
        vengono isolati gli indici dei soli documenti che superano il punteggio stabilito (0.80).
            -> np.argsort(similarities[valid_indices]) ordina i punteggi validi in ordine crescente e restituisce i loro indici.
            ->[-top_k:] prende gli ultimi top_k elementi (ovvero quelli con il punteggio più alto).
            ->[::-1] inverte l'ordine dell'array, trasformandolo in ordine decrescente (il più simile in assoluto diventa il primo).
        """
        if not self.vectors: return []
        #generiamo il vettore della query
        query_emb = self.encode([query], is_query=True)
        all_vectors = np.array(self.vectors)

        #calcolo similarity dei vettori in memoria
        similarities = self._calculate_cosine_similarity(all_vectors, query_emb)

        #applichiamo la soglia minima di similarità
        valid_indices = np.where(similarities >= self.threshold)[0]
        
        if len(valid_indices) == 0: return []
        #ordiniamo i risultati in ordine dal più al meno simile, ne prendiamo solo i primi top_k
        top_k_indices = valid_indices[np.argsort(similarities[valid_indices])[-top_k:][::-1]]
        
        #restituiamoi testi corrispondenti a quegli indici ordinati
        return [self.chunks[idx] for idx in top_k_indices]

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Metodo isolato per calcolare l'embedding di un singolo pezzo di testo.
        Prende una singola stringa, la inserisce in una lista, chiama il metodo encode impostandola come documento (is_query=False) 
        ed estrae il primo (e unico) vettore generato ([0]).
        """
        return self.encode([text], is_query=False)[0]

    def add_to_index(self, text: str, embedding: np.ndarray):
        """
        Aggiunge un chunk e il suo vettore già calcolato alla memoria volatile.
        Questo metodo viene usato quando l'embedding è già stato calcolato in precedenza (estratto dal database). 
        Acquisisce il lock e inserisce direttamente il testo e il vettore forniti in input.
        """
        with self._lock:
            self.vectors.append(embedding)
            self.chunks.append(text)