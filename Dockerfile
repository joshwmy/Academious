FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
# `.[embed]` and not `.` - the model stack is an optional extra in
# pyproject.toml, and without it this image can harvest but cannot embed, and
# cannot answer a semantic search either: retrieval/semantic.py encodes the
# query at request time, so the API needs the backend as much as the worker
# does. A bare `pip install -e .` produces a 96 MB image that runs, serves
# /health, ingests a corpus, and then returns nothing from /search.
#
# The cost is the ~2 GB torch brings, which docs/deployment.md already sizes
# the disk around. RETR-005 tracks moving inference to the ONNX graph, which
# needs ~350 MB instead - but exporting a graph requires torch, so that is a
# change to how the image is built, not a smaller argument here.
RUN pip install --no-cache-dir -e ".[embed]"

COPY alembic.ini ./
COPY migrations ./migrations

CMD ["uvicorn", "academious.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
