FROM postgres:16-alpine

LABEL maintainer="DragonBank Team"
LABEL description="DragonBank PostgreSQL Database"

# Copie du script d'initialisation
COPY init.sql /docker-entrypoint-initdb.d/

# Exposition du port
EXPOSE 5432

# Healthcheck intégré
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD pg_isready -U dragonadmin -d dragonbank || exit 1