#!/bin/bash

poetry run uvicorn --port 8000 --host 0.0.0.0  --workers 4 tenant.api:app 
