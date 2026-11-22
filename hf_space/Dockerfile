# RIA Space (CPU Basic friendly): tiny stateless web front end. No model runs here by default.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --user -r requirements.txt
COPY --chown=user app.py .
COPY --chown=user static ./static

# Hugging Face Docker Spaces route traffic to port 7860 (app_port in README.md front matter)
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
