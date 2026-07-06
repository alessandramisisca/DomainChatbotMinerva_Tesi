from abc import ABC, abstractmethod
from typing import List
class BaseSearcher(ABC):
    def __init__(self, whitelisted_domains: List[str]):
        """
        Input: lista di domini supportati

        Metodo costruttore che istanzia la lista dei domini supportati: 
            -> en.wikipedia.org, www.nba.com, editorial.rottentomatoes.com, www.nba.com
        """
        self.whitelist : List[str] = whitelisted_domains

    @abstractmethod
    def get_search_data(self, query: str):
        """
        Metodo definito in ogni sottoclasse, delinea gli aspetti della ricerca sul web in base al motore di ricerca scelto
        
        """
        pass