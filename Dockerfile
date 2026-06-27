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

# Install Cython first, then the project (with all its dependencies)  --no-cache-dir
RUN pip install  cython \
    && pip install  .

# Compile all .py → .so (except entry points kept as .py)
RUN python scripts/compile_cython.py

# Copy variable font files to a dedicated directory for the runtime stage.
# We use a shell command because Docker COPY treats [wght] as a glob character class,
# which prevents matching the literal filename "NotoSansSC[wght].ttf".
# Use find+cp to avoid shell glob issues with brackets in filenames.
RUN mkdir -p /fonts \
    && find /build -maxdepth 1 -name 'NotoSansSC*.ttf' -exec cp -t /fonts/ {} + 2>/dev/null || true \
    && find /build -maxdepth 1 -name 'NotoSansCJKsc*.ttf' -exec cp -t /fonts/ {} + 2>/dev/null || true \
    && touch /fonts/.keep

# Pre-instantiate variable fonts at weights 400 (Regular) and 700 (Bold).
# This avoids a ~15s delay on the first PDF export in the runtime container
# (fontTools instantiation is slow; caching the result at build time means
# the runtime container can load the static fonts in ~0.2s instead).
# inplace=True is critical — without it the original variable font is saved
# unchanged (see comment in web/pdf_export.py:_instantiate_variable_font).
RUN mkdir -p /font_cache \
    && python scripts/preinstantiate_fonts.py /fonts /font_cache

# ── Stage 2: Runtime ──────────────────────────────────────────────────
# Slim image with only compiled .so modules — no Python source code
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy the venv (contains compiled .so modules in site-packages)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CJK fonts so PDF export (fpdf2) can render Chinese reports inside the container
# Install system fonts as fallback, then copy bundled variable font for better quality
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Copy bundled variable font files from build stage.
# These TTF variable fonts produce CIDFontType2 embedding in PDFs which renders
# correctly in ALL viewers (Chrome, Firefox, Acrobat). The system-installed
# NotoSansCJK-Regular.ttc uses CFF outline (CIDFontType0) which causes garbled
# text in browser-based PDF viewers.
# The font files were copied to /fonts/ in the builder stage to avoid Docker COPY
# glob issues with [wght] in the filename.
COPY --from=builder /fonts/ /usr/share/fonts/truetype/noto/

# Rebuild font cache to recognize newly copied fonts
RUN fc-cache -f -v || true

# Create appuser and set up working directory (before COPY so files are owned by appuser)
RUN useradd --create-home appuser \
    && mkdir -p /home/appuser/app/.streamlit

# Copy pre-instantiated static fonts into appuser's font cache.
# This lets the first PDF export skip the ~15s fontTools instantiation
# (web/pdf_export.py reads from ~/.cache/tradingagents/fonts/).
COPY --from=builder /font_cache/ /tmp/font_cache/
RUN mkdir -p /home/appuser/.cache/tradingagents/fonts \
    && cp /tmp/font_cache/*.ttf /home/appuser/.cache/tradingagents/fonts/ 2>/dev/null || true \
    && rm -rf /tmp/font_cache \
    && chown -R appuser:appuser /home/appuser/.cache

# Streamlit config (theme + WebSocket keep-alive for Docker)
# Copy before USER switch so we can set ownership
COPY --from=builder --chown=appuser:appuser /build/.streamlit /home/appuser/app/.streamlit
COPY --from=builder /build/scripts/docker_entrypoint.sh /usr/local/bin/docker_entrypoint.sh
RUN chmod +x /usr/local/bin/docker_entrypoint.sh

WORKDIR /home/appuser/app

# Streamlit server config for Docker
# APP_ROOT tells web/app.py where to find .env (persisted via volume mount)
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    APP_ROOT=/home/appuser/app \
    HOME=/home/appuser

EXPOSE 8501

ENTRYPOINT ["/usr/local/bin/docker_entrypoint.sh"]
