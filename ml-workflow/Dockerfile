# ml-workflow/Dockerfile (ersetzt Dockerfile.cpu und Dockerfile.gpu)

# Akzeptiert ein Build-Argument für das Basis-Image
ARG BASE_IMAGE=tensorflow/tensorflow:latest
FROM ${BASE_IMAGE}

# Arbeitsverzeichnis im Container setzen
WORKDIR /app

# Systempakete installieren (falls benötigt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Benötigte Python-Bibliotheken installieren
RUN pip install --no-cache-dir pandas requests scikit-learn openpyxl

# Kopiere die Skripte in das Arbeitsverzeichnis
COPY scripts/ .

# Standard-Befehl (kann im K8s-Job überschrieben werden)
CMD ["python", "preprocess.py"]
