
FROM python:3.11.4-bullseye

RUN pip install --upgrade pip \
    && pip install --upgrade poetry \
    && python3 -m poetry config virtualenvs.in-project true

WORKDIR /app
COPY ./packages/jb-tenant ./packages/jb-tenant
COPY ./packages/jb-document-collection ./packages/jb-document-collection
COPY ./packages/jb-core ./packages/jb-core
COPY ./packages/jb-storage ./packages/jb-storage

WORKDIR /app/jb-tenant-service

COPY jb-tenant-service/pyproject.toml jb-tenant-service/poetry.lock jb-tenant-service/README.md ./
COPY jb-tenant-service/tenant/__init__.py ./tenant/

RUN python3 -m poetry install --only main

COPY jb-tenant-service/ ./

CMD tools/run-server.sh
