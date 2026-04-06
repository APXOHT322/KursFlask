FROM clojure:lein

WORKDIR /app
COPY . .

RUN lein deps

CMD ["lein", "ring", "server-headless"]
