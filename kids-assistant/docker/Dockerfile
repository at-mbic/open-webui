# Study Buddy: one self-contained container. Stock Open WebUI plus the kids'
# tutors, guardrails and locked-down settings, applied automatically at start.
#
# Build context is the kids-assistant/ folder:
#   docker build -f docker/Dockerfile -t study-buddy .
#
# Nothing is needed on the host except Docker. All data (accounts, chats,
# notes, the API key) lives in the volume mounted at /app/backend/data.

FROM ghcr.io/open-webui/open-webui:v0.6.18

# The tutor engine needs a newer Anthropic SDK than the base image ships.
# Installing it here also means Open WebUI never pip-installs at runtime.
# The optional "ca" build secret is only for building behind a TLS-inspecting
# proxy; it is never written into the image.
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir "anthropic==2.8.0"

COPY functions/ /app/kids-assistant/functions/
COPY prompts/ /app/kids-assistant/prompts/
COPY scripts/provision.py /app/kids-assistant/scripts/provision.py
COPY kids.config.example.json /app/kids-assistant/kids.config.json
COPY docker/entrypoint.sh docker/firstboot.py /app/kids-assistant/docker/

ENV KIDS_CONFIG=/app/kids-assistant/kids.config.json \
    # Keep the signing key in the data volume so logins survive upgrades.
    WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key \
    WEBUI_NAME="Study Buddy" \
    TZ=America/New_York \
    # First-boot defaults. provision.py enforces the same settings through
    # the API on every start, because Open WebUI stores config in its DB.
    ENABLE_SIGNUP=true \
    DEFAULT_USER_ROLE=pending \
    ENABLE_OLLAMA_API=false \
    ENABLE_OPENAI_API=false \
    ENABLE_DIRECT_CONNECTIONS=false \
    ENABLE_COMMUNITY_SHARING=false \
    ENABLE_WEB_SEARCH=false \
    ENABLE_IMAGE_GENERATION=false \
    ENABLE_CODE_EXECUTION=false \
    ENABLE_CODE_INTERPRETER=false \
    ENABLE_EVALUATION_ARENA_MODELS=false \
    ENABLE_ADMIN_CHAT_ACCESS=true \
    ENABLE_NOTES=true \
    USER_PERMISSIONS_CHAT_TEMPORARY=false \
    USER_PERMISSIONS_CHAT_DELETE=false \
    USER_PERMISSIONS_FEATURES_WEB_SEARCH=false \
    USER_PERMISSIONS_FEATURES_IMAGE_GENERATION=false \
    USER_PERMISSIONS_FEATURES_CODE_INTERPRETER=false \
    ANONYMIZED_TELEMETRY=false \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true

LABEL org.opencontainers.image.title="Study Buddy" \
      org.opencontainers.image.description="Open WebUI with locked-down kids' tutors"

CMD ["bash", "/app/kids-assistant/docker/entrypoint.sh"]
