FROM python:3.11-slim

# hcxpcapngtool (paquet hcxtools) pour convertir les pcap en hash 22000, côté serveur.
RUN apt-get update && apt-get install -y --no-install-recommends hcxtools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Les secrets (tokens, mot de passe UI) sont injectés au run via environment: (jamais dans l'image).
ENV WIFITEST_DB=/data/jobs.db
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
