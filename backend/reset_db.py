from src.mariadb_data import database as db

if __name__ == "__main__":
    print("--- ATTENZIONE: Stai per svuotare il database ---")
    conferma = input("Sei sicuro di voler resettare tutte le tabelle? (s/n): ")
    
    if conferma.lower() == 's':
        try:
            db.reset_all_tables()
            print("Database pulito correttamente.")
        except Exception as e:
            print(f"Errore durante il reset: {e}")
    else:
        print("Operazione annullata.")

        #docker-compose exec chatbot_backend python -c "from src.mariadb_data import database as db; db.reset_all_tables()"