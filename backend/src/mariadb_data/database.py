import mariadb
import sys
import os
import json
import numpy as np

""" usiamo tabelle per lo storico della chat, per salvale i link gia parsti del nostro gs, per salvare info? per eliminare dopo un tot le fo piu veccie """

# CONFIGURAZIONE E INIZIALIZZAZIONE DEL CONNECTION POOL (GLOBAL SINGLETON)
_pool = None
_active_connections_count = 0  # Contatore manuale per monitorare i thread attivi

def _get_pool():
    """
    Implementa il pattern Singleton. Verifica se esiste già un pool di connessioni: in caso contrario, ne crea uno nuovo collegato a MariaDB. 
    Il pool_size=10 è un parametro critico: limita il numero di connessioni simultanee aperte verso il server, prevenendo errori di "too many connections" se c'è alto traffico.
    Garantisce che il pool venga istanziato una sola volta (Lazy Initialization)
    """
    global _pool
    if _pool is None:
        user = os.getenv("MARIADB_USER", "admin")
        password = os.getenv("MARIADB_PASSWORD", "password_tesi")
        host = os.getenv("MARIADB_HOST", "mariadb")
        port = int(os.getenv("MARIADB_PORT", "3306"))
        database = os.getenv("MARIADB_DATABASE", "chatbot")
        
        try:
            # Creiamo il pool globale con una dimensione massima di 10 connessioni
            _pool = mariadb.ConnectionPool(
                pool_name="minerva_pool",
                user=user,
                password=password,
                host=host,
                port=port,
                database=database,
                pool_size=10
            )
            print("\n" + "="*60)
            print(f"[DATABASE POOL] Pool istanziato con successo!")
            print(f"[DATABASE POOL] Dimensione massima allocata: 10 connessioni riutilizzabili.")
            print("="*60 + "\n")
        except mariadb.Error as e:
            print(f"[DATABASE POOL] Errore critico di inizializzazione: {e}")
            sys.exit(1)
    return _pool

def get_connection():
    """
    Estrae una connessione dal pool. Include un meccanismo di Monkey Patching: sovrascrive il metodo .close() originale della connessione per sostituirlo con monitored_close(). 
    Questo permette di aggiornare automaticamente il contatore _active_connections_count ogni volta che una connessione viene restituita al pool, evitando perdite di memoria/connessioni.
    """
    global _active_connections_count
    pool = _get_pool()
    try:
        conn = pool.get_connection()
        _active_connections_count += 1
        print(f"[ POOL GET] Connessione estratta dal Pool. (Connessioni in uso concorrente: {_active_connections_count})")
        
        original_close = conn.close
        # Usiamo un flag interno alla connessione per evitare doppi conteggi
        conn._already_logged_release = False 
        
        def monitored_close():
            global _active_connections_count
            if not conn._already_logged_release:
                conn._already_logged_release = True
                original_close()
                _active_connections_count -= 1
                print(f"[POOL RELEASE] Connessione riposta nel Pool. (Connessioni rimaste in uso: {_active_connections_count})")
            else:
                # Se viene richiamato un secondo close(), eseguiamo quello nativo senza toccare i contatori
                original_close()
        
        conn.close = monitored_close
        return conn
    except mariadb.Error as e:
        print(f"[DATABASE POOL] Errore nel prelievo della connessione dal pool: {e}")
        raise e

def init_db():
    """
    Definisce la struttura relazionale del database. Utilizza CREATE TABLE IF NOT EXISTS e creaiamo le tabelle documents (per il contenuto), 
    document_chunks (per la segmentazione RAG), chat_sessions e chat_messages (per la memoria storica), stabilendo le relazioni tramite FOREIGN KEY ... ON DELETE CASCADE, 
    che garantisce che eliminando una sessione chat, tutti i messaggi associati vengano rimossi automaticamente dal DB.
    """

    conn = get_connection()
    # Cursore per poter eseguire i comandi SQL sul db
    cur = conn.cursor()
    try:
        #Query SQL pura per creare la tabella documenti (Caching degli URL del web e del Gold Standard)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents ( 
                id INT AUTO_INCREMENT PRIMARY KEY,
                url VARCHAR(255) UNIQUE,
                domain VARCHAR(50),
                content_clean LONGTEXT NULL,
                noise_score FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        #tabella con gli url dei nostri gs e tabella con gli url parsati al momento dalla ricerca e data di inserimento nel database
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS document_chunks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    document_id INT,
                    chunk_index INT,
                    chunk_text TEXT NOT NULL,
                    embedding_json LONGTEXT NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                )
        """)

        # ID utente per tracciare la sua sessione, con la data di creazione

        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ID utente id chat e messaggi di quella chat
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(255),
                role ENUM('user', 'assistant', 'system') NOT NULL,
                content TEXT NOT NULL,
                fonti TEXT NULL,
                created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE 
            )
        """)

        # Conferma e rende definitive sul db tutte le operazioni strutturali eseguite nella transazione
        conn.commit()
        print("Database inizializzato con successo!")
    except mariadb.Error as e:
        # Gestisce i fallimenti stampando a schermo l'errore generato dallo schema SQL
        print(f"Errore inizializzazione schema: {e}")
    finally:
        # Chiude in ogni caso il cursore per liberare le risorse interne del database
        cur.close()
        # Chiude la connessione di rete verso il server MariaDB per evitare connection leaks
        conn.close()

# OPERAZIONI DI LETTURA/SCRITTURA DOCUMENTI

# Insert nuovo url + testo parsato
def save_document_with_chunks(url: str, domain: str, content: str, noise: float, chunk_list: list, embedding_list: list):
    """
    Gestisce l'inserimento di un documento e della sua frammentazione in chunks, ci permette di salvare all'interno del database i contenuti parsati dal web. 
    Usiamo INSERT IGNORE per evitare duplicati sugli URL. Se il documento esiste già, recupera il suo ID e aggiorna i suoi chunk (cancellando i vecchi e riscrivendo i nuovi) 
    per garantire che la cache sia sempre aggiornata con i contenuti più recenti. Prima di salvare nuovi chunk, eseguiamo una DELETE mirata (WHERE document_id = ...) per assicurarci 
    che non ci siano frammenti vecchi associati a quell'URL.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Usiamo INSERT IGNORE: se l'URL esiste già, non va in crash ma passa oltre
        cur.execute(
            "INSERT IGNORE INTO documents (url, domain, content_clean, noise_score) VALUES (?, ?, ?, ?)", 
            (url, domain, content, noise)
        )
        
        document_id = cur.lastrowid

        # Se document_id è 0 o None (perché INSERT IGNORE ha saltato l'inserimento), 
        # recuperiamo l'ID del documento già esistente per agganciarci i chunk
        if not document_id:
            cur.execute("SELECT id FROM documents WHERE url = ?", (url,))
            res = cur.fetchone()
            if res:
                document_id = res[0]

        # Prima di inserire i nuovi chunk per questo URL, puliamo quelli vecchi 
        # per evitare di accumulare duplicati nella tabella dei frammenti
        cur.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))

        for idx, (chunk_text, emb) in enumerate(zip(chunk_list, embedding_list)):
            if isinstance(emb, np.ndarray):
                emb = emb.tolist()
            emb_json = json.dumps(emb)

            cur.execute(
                """ INSERT INTO document_chunks (document_id, chunk_index, chunk_text, embedding_json)
                    VALUES (?, ?, ?, ?)""",
                (document_id, idx, chunk_text, emb_json)
            )
        conn.commit()
    except mariadb.Error as e:
        print(f"Errore nel salvataggio: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

# Delete url e testo parsato
def erase_history():
    """
    Elimina i dati appartenenti a domini che cambiano frequentemente (come www.nba.com) o documenti più vecchi di 7 giorni, mantenendo le dimensioni del database contenute 
    ed evitando che il sistema operi su informazioni obsolete.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Elimina tutti i documenti appartenenti all'ambito NBA (dati instabili ad alta variabilità)
        cur.execute("DELETE FROM documents WHERE domain LIKE '%nba%'")
        # Elimina tutti i documenti il cui timestamp di inserimento supera una soglia massima di obsolescenza (7 giorni)
        cur.execute("DELETE FROM documents WHERE created_at < NOW() - INTERVAL 7 DAY")
        conn.commit()
        print("Cache ripulita secondo i criteri di obsolescenza.")
    except mariadb.Error as e:
        print(f"Errore durante il clean della cronologia cache: {e}")
    finally:
        cur.close()
        conn.close()


# OPERAZIONI DI GESTIONE CHAT / MESSAGGI

# insert nuovo utente + nuova sessione
def chat_new_session(session_id: str, user_id: str):
    """
    Crea una nuova onversazione, associando un session_id univoco a un user_id.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Esegue una INSERT parametrizzata e protetta per salvare la nuova sessione agganciandola all'utente
        cur.execute("INSERT INTO chat_sessions (session_id, user_id) VALUES (?, ?)", (session_id, user_id))
        conn.commit()
    except mariadb.Error as e:
        print(f"Errore inserimento sessione: {e}")
    finally:
        cur.close()
        conn.close()

# Select utente + tutte le sue sessioni + select utente + ultima sessione
def chat_all_session(user_id: str):
    """
    Recupera lo storico delle sessioni di un utente, ordinate dalla più recente alla più vecchia. 
    È il metodo utilizzato dall'interfaccia UI per popolare il menu laterale della chat.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Legge le sessioni dell'utente ordinandole in modo decrescente (la più recente appare per prima)
        cur.execute("SELECT session_id, created_at FROM chat_sessions WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        # Costruisce e restituisce una lista di dizionari mappando le righe trovate
        return [{"session_id": row[0], "created_at": row[1]} for row in cur.fetchall()]
    except mariadb.Error as e:
        print(f"Errore lettura sessioni: {e}")
        # Restituisce un elenco vuoto per prevenire blocchi logici nel backend
        return []
    finally:
        cur.close()
        conn.close()

# Insert aggiunta di un nuovo messgagio + insert utente + nuovo messaggio ma nella stessa chat
def save_chat_message(session_id: str, role: str, content: str, sources: list = None):
    """
    Salva un singolo messaggio della conversazione. Serializza il parametro sources in formato JSON, permettendo di memorizzare quali siti sono stati usati 
    dal sistema per rispondere a quella specifica domanda.
    """
    conn = get_connection()
    cur = conn.cursor()

    fonti_json = json.dumps(sources) if sources else None
    try:
        # Inserisce un record nella cronologia messaggi
        cur.execute(
            "INSERT INTO chat_messages (session_id, role, content, fonti) VALUES (?, ?, ?, ?)", 
            (session_id, role, content, fonti_json))
        conn.commit()
    except mariadb.Error as e:
        print(f"Errore salvataggio messaggio: {e}")
    finally:
        cur.close()
        conn.close()


def get_chat_history(session_id: str):
    """
    Recupera l'intera cronologia dei messaggi di una sessione specifica. Ordina i messaggi per ID (sequenza temporale di creazione), affinché l'LLM possa comprendere il contesto 
    precedente della conversazione nel caso di "follow-up" queries in cui necessita la risoluzione del contesto e del soggetto.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Legge ruolo e testo filtrando sulla sessione e ordinando in ordine temporale crescente (dal primo messaggio all'ultimo)
        cur.execute("SELECT role, content, fonti FROM chat_messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
        history= []
        for row in cur.fetchall():
            # Deserializza le fonti (se presenti), altrimenti array vuoto
            fonti_list = json.loads(row[2]) if row[2] else []
            history.append({
                "role": row[0], 
                "content": row[1],
                "fonti": fonti_list
            })
        return history
    except mariadb.Error as e:
        # Registra sul log del terminale l'eventuale errore di vincolo o inserimento
        print(f"Errore caricamento history: {e}")
        return []
    finally:
        cur.close()
        conn.close()

# delete pulizia singola sessione
def erase_session(session_id: str):
    """
    Funzione di eliminazione di una singola sessione. Sfrutta il vincolo ON DELETE CASCADE del database per pulire sia la sessione che tutti i messaggi associati 
    con un unico comando, mantenendo l'integrità referenziale
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Rimuove la sessione specificata; il database applicherà in automatico il CASCADE sui messaggi figli
        cur.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    except mariadb.Error as e:
        print(f"Errore rimozione sessione: {e}")
    finally:
        cur.close()
        conn.close()

# delete pulizia di tutte le sessioni     
def erase_all_sessions(user_id: str):
    """
    Funzione di eliminazione di tutte le sessioni di un utente specifico. Sfrutta il vincolo ON DELETE CASCADE del database per pulire sia la sessione che tutti i messaggi associati 
    con un unico comando, mantenendo l'integrità referenziale
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    except mariadb.Error as e:
        print(f"Errore rimozione globale: {e}")
    finally:
        cur.close()
        conn.close()


def get_all_chunks_with_urls():
    """
    Esegue una JOIN tra la tabella dei chunk (document_chunks) e quella dei documenti (documents).
    Converte gli embedding (memorizzati come stringhe JSON nel DB) in array numpy.float32, così da poter essere utilizzati per il calcolo della cosine similarity.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT c.chunk_text, c.embedding_json, d.url 
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
        """)
        rows = cur.fetchall()
        return [
            {
                "text": row[0],
                "embedding": np.array(json.loads(row[1]), dtype=np.float32),
                "url": row[2]
            }
            for row in rows
        ]
    except mariadb.Error as e:
        print(f"Errore recupero chunks: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def get_document_info(url: str):
    """
    Recupera i dati relativi a un documento specifico identificato dal suo URL. Ci permette di sapere quando un documento è stato inserito (created_at) 
    e a quale dominio appartiene.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT domain, created_at FROM documents WHERE url = ?
        """, (url,))
        row = cur.fetchone()
        if row:
            import time as time_module
            created_at_dt = row[1]
            created_at_timestamp = time_module.mktime(created_at_dt.timetuple())
            return {"domain": row[0], "created_at": created_at_timestamp}
        return None
    except mariadb.Error as e:
        print(f"Errore recupero info documento: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def reset_all_tables():
    """Svuota tutte le tabelle resettando anche gli ID progressivi."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Disabilita i controlli delle chiavi esterne per evitare errori di vincolo
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        
        # Elenco delle tue tabelle
        tables = ['chat_messages', 'chat_sessions', 'document_chunks', 'documents']
        
        for table in tables:
            cur.execute(f"TRUNCATE TABLE {table}")
            print(f"Tabella {table} svuotata.")
            
        # Riabilita i controlli
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
        print("Database resettato con successo!")
    except mariadb.Error as e:
        print(f"Errore durante il reset del DB: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def get_multiple_cached_embeddings(urls: list):
    """
    Esegue un recupero dei chunk e dei vettori embedding per una lista di URL fornita in input.
    Invece di eseguire una query SQL separata per ogni URL, recupera tutti i chunk relativi a tutti gli URL richiesti con un'unica chiamata.
    I risultati vengono raggruppati in un dizionario dove la chiave è l'URL e il valore è la lista dei chunk/embedding associati.
    """
    if not urls:
        return {}
    
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Costruisce la query con il numero corretto di placeholder
        placeholders = ', '.join(['?'] * len(urls))
        query = f"""
            SELECT d.url, c.chunk_text, c.embedding_json 
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.url IN ({placeholders})
        """
        cur.execute(query, tuple(urls))
        
        rows = cur.fetchall()
        results = {}
        for url, text, emb_json in rows:
            if url not in results:
                results[url] = []
            results[url].append({
                "text": text, 
                "embedding": np.array(json.loads(emb_json), dtype=np.float32)
            })
        return results
    except mariadb.Error as e:
        print(f"Errore recupero batch cache: {e}")
        return {}
    finally:
        cur.close()
        conn.close()