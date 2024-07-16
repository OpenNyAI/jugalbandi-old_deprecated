#!/bin/bash

docker run -it --rm -p 8080:8080 \
  --env-file .env \
  gcr.io/indian-legal-bert/tenant_service:latest
