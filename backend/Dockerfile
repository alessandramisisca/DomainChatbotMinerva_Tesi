ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

WORKDIR /app

#per evitare blocchi
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

#installazione librerie runtime di base, lobgomp1 necessaria per fastembed
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

#build dependencies (strumenti di compilazione)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    cmake \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*
    
COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=1000 -r requirements.txt

RUN playwright install chromium && playwright install-deps chromium

#RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')
# Imposta la cartella di cache dove Docker metterà i modelli
ENV HF_HOME=/app/huggingface_cache

# Creiamo la cartella e diamo i permessi
RUN mkdir -p /app/huggingface_cache

# Scarichiamo il modello usando la cache di build di Docker per evitare errori
# Usiamo --mount=type=cache per evitare di scaricare tutto se la build fallisce
RUN --mount=type=cache,target=/app/huggingface_cache \
    python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"



# Rimozione compilatori che non servono più
RUN apt-mark manual libmariadb3 libgomp1 2>/dev/null; \
    apt-get purge -y gcc g++ cmake 2>/dev/null || true; \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*



COPY . .

EXPOSE 8003

#CMD ["uvicorn", "chatbot_logic:server_chatbot:app", "--host", "0.0.0.0", "--port", "8001"]