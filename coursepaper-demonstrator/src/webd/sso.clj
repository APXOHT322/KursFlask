(ns ^{:doc    "SSO token generation for seamless transition to Flask app"
      :author "webd"}
  webd.sso
  (:require [clojure.java.jdbc :as jdbc]
            [clojure.tools.logging :as log])
  (:import [java.util UUID]
           [java.time LocalDateTime]))

;; ── Конфигурация БД (та же MariaDB что у Flask) ──────────────────────────────
(def ^:private db-spec
  {:dbtype   "mariadb"
   :dbname   "Kurs"
   :host     "localhost"
   :port     3306
   :user     "root"
   :password "OoRa2Oob"})

;; ── URL Flask-приложения ──────────────────────────────────────────────────────
(def ^:private flask-url "http://localhost:5000")

;; ── Генерация и сохранение токена ────────────────────────────────────────────

(defn create-sso-token!
  "Создаёт одноразовый SSO-токен для пользователя uid.
   Токен живёт 2 минуты. Возвращает строку токена или nil при ошибке."
  [uid]
  (try
    (let [token      (str (UUID/randomUUID))
          expires-at (.plusMinutes (LocalDateTime/now) 2)]
      (jdbc/insert! db-spec :sso_tokens
                    {:token      token
                     :uid        uid
                     :expires_at expires-at})
      (log/info "SSO token created for" uid)
      token)
    (catch Exception e
      (log/error e "Failed to create SSO token for" uid)
      nil)))

(defn flask-sso-url
  "Возвращает полный URL для перехода во Flask с SSO-токеном.
   Если токен создать не удалось — возвращает просто /login Flask."
  [uid]
  (if-let [token (create-sso-token! uid)]
    (str flask-url "/sso?token=" token)
    (str flask-url "/login")))
