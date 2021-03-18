#!/bin/bash

source env/bin/activate
exec celery -A fbone.ai.tasks worker -c 1 --max-tasks-per-child=1 --loglevel=info --workdir=/ai/PDF-OCR-RTP -Q pdf_request
