FROM python:3.11

WORKDIR /app

COPY . .

# создаём виртуальное окружение через python3
RUN python3 -m venv venv

# активируем и ставим зависимости
RUN . venv/bin/activate && pip install --no-cache-dir -r requirements.txt

# чтобы команды использовали venv
ENV PATH="/app/venv/bin:$PATH"

# переменные Flask
ENV FLASK_APP=app.app
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

# запуск Flask
CMD ["flask", "run"]
