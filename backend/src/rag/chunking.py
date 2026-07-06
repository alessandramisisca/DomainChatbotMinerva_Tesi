from langchain_text_splitters import RecursiveCharacterTextSplitter

class TextChunker:
    def __init__(self, chunk_size: int= 800, chunk_overlap: int = 100):
        # Evita di tagliare frasi a metà usando i separatori naturali
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ".", " ", ""]
        )

    def split(self, text: str) -> list[str]:
        """E' il metodo che prende una stringa di testo e restituisce una lista di chunk."""
        if not text:
            return []
        return self.splitter.split_text(text)