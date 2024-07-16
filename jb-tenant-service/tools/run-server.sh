#!/bin/bash

poetry run uvicorn --port 8080 --host 0.0.0.0  --workers 4 tenant.server:app 
