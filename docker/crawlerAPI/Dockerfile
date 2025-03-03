ARG PYTHON_VERSION=3.13.1-slim-bullseye

FROM python:${PYTHON_VERSION} AS python

FROM python AS builder

RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential

COPY ./requirements.txt ./requirements.txt

RUN pip wheel --wheel-dir /usr/src/app/wheels \
    -r requirements.txt

FROM python AS runner
ARG BUILD_ENVIRONMENT=prod
ARG APP_HOME=/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BUILD_ENV=${BUILD_ENVIRONMENT}

WORKDIR ${APP_HOME}

COPY --from=builder /usr/src/app/wheels /wheels/

RUN pip install --no-cache-dir --no-index --find-links=/wheels/ /wheels/* \
    && rm -rf /wheels/

EXPOSE 8080

COPY . ${APP_HOME}

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
