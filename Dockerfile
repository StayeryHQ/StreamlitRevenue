# Debian-slim statt Alpine (RAM-Postmortem F9).
#
# Alpine benutzt musl. musl's Allokator gibt bei genau diesem Lastprofil
# (Millionen kurzlebiger Python-String-Objekte + große Arrow-Puffer) freien
# Speicher schlechter ans OS zurück als glibc und kennt malloc_trim() gar
# nicht - der Prozess bleibt nach einem Refresh dauerhaft aufgebläht.
# Zusätzlich gibt es für pandas/pyarrow/numpy fertige manylinux-Wheels,
# unter Alpine wurde stattdessen aus dem Quellcode kompiliert.
# Das Image wird größer, das Speicherverhalten dafür planbar.
FROM python:3.12-slim AS builder

WORKDIR /app

# Build-Abhängigkeiten (die meisten Wheels sind vorkompiliert, gcc bleibt
# als Sicherheitsnetz für Pakete ohne manylinux-Wheel).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
 && rm -rf /var/lib/apt/lists/*

# Copy only requirements first
COPY requirements.txt .

# Install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# curl für den Healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY streamlit_app ./streamlit_app
COPY src ./src
COPY configs ./configs
COPY .streamlit ./.streamlit
COPY pyproject.toml ./
# F2: Die Seite „Daten aktualisieren" startet scripts/refresh_snapshot.py als
# eigenen Prozess. Ohne diese Zeile fehlt das Script im Image und der
# Refresh-Button scheitert mit FileNotFoundError.
COPY scripts ./scripts

# Set environment variables
#
# MALLOC_ARENA_MAX (F9): begrenzt die Zahl der glibc-malloc-Arenen und damit
# die Heap-Fragmentierung über Threads hinweg. Gemessener Effekt bei unserem
# Lastprofil: klein (96 MB -> 87 MB einbehalten), aber kostenlos und ohne
# Nachteil beim Peak.
#
# ARROW_DEFAULT_MEMORY_POOL wird BEWUSST NICHT gesetzt. Naheliegend wäre
# jemalloc, gemessen ist es hier aber schlechter als der mimalloc-Default
# (190 MB einbehalten statt 90 MB). Den Löwenanteil erledigt ohnehin
# ``helpers.release_memory()`` (578 MB -> 96 MB einbehalten).
#
# ACHTUNG: Kommentare NICHT in die ENV-Zeile mit Backslash-Fortsetzung
# schreiben - Docker behandelt sie dort nicht zuverlässig als Kommentar.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MALLOC_ARENA_MAX=2

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["streamlit", "run", "streamlit_app/Home.py", "--server.port=8501", "--server.address=0.0.0.0"]
