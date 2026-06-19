# ── Stage 1: Build ─────────────────────────────────────────────────────
# Install dependencies + compile Python source to .so extensions
FROM python:3.12 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# gcc is required by Cython to compile .c → .so
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY . .

# Install Cython first, then the project (with all its dependencies)
RUN pip install --no-cache-dir cython \
    && pip install --no-cache-dir .

# Compile all .py → .so (except entry points kept as .py)
RUN python scripts/compile_cython.py

# ── Stage 2: Runtime ──────────────────────────────────────────────────
# Slim image with only compiled .so modules — no Python source code
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy the venv (contains compiled .so modules in site-packages)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CJK fonts so PDF export (fpdf2) can render Chinese reports inside the container
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

#RUN useradd --create-home appuser
#USER appuser
WORKDIR /home/appuser/app

# Streamlit server config for Docker
# APP_ROOT tells web/app.py where to find .env (persisted via volume mount)
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    APP_ROOT=/home/appuser/app

EXPOSE 8501

ENTRYPOINT ["tradingagents-web"]
