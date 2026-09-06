FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY crunchy_calendar /app/crunchy_calendar
COPY data /app/data

USER 65532:65532
ENTRYPOINT ["python", "-m", "crunchy_calendar.batch"]
