FROM python:3.11

WORKDIR /app

COPY . .

# создаём venv через python3
RUN python3 -m venv venv

# ставим зависимости через venv
RUN . venv/bin/activate && pip install --no-cache-dir -r requirements.txt

# чтобы команды использовали venv
ENV PATH="/app/venv/bin:$PATH"

# Flask
ENV FLASK_APP=app
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

CMD ["flask", "run"]
