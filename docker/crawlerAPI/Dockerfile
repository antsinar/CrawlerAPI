ARG PYTHON_VERSION=3.13.1

FROM python:${PYTHON_VERSION}-bookworm AS python

FROM python AS builder

ARG APP_HOME=/app

RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    curl \
    ca-certificates && \
    apt clean && rm -rf /var/lib/apt/lists/*

ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"

WORKDIR ${APP_HOME}

COPY ./pyproject.toml .
COPY ./uv.lock .

RUN uv sync --frozen

FROM python:${PYTHON_VERSION}-slim-bookworm AS runner
ARG BUILD_ENVIRONMENT=prod
ARG APP_HOME=/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BUILD_ENV=${BUILD_ENVIRONMENT}

WORKDIR ${APP_HOME}

COPY . .

COPY --from=builder ${APP_HOME}/.venv .venv
ENV PATH="/${APP_HOME}/.venv/bin:$PATH"

EXPOSE 8000

RUN alembic upgrade head

CMD [ "python3", "runserver.py", "--profile", "prod" ]
