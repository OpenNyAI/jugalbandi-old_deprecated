#!/bin/bash

docker run -it --rm -p 8000:8000 \
  --env-file .env \
  tenant_service:latest
