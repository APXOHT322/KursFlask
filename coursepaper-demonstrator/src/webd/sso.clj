(ns ^{:doc    "SSO token generation and validation for seamless transition between apps"
      :author "webd"}
  webd.sso
  (:require [clojure.java.jdbc :as jdbc]
            [clojure.tools.logging :as log])
  (:import [java.util UUID]
           [java.time LocalDateTime]))

;; ── Конфигурация БД через прямой JDBC URL ────────────────────────────────────
(def ^:private db-host
  (or (System/getenv "DB_HOST") "host.docker.internal"))

(def ^:private db-spec
  {:connection-uri (str "jdbc:mariadb://" db-host ":3306/Kurs?user=root&password=OoRa2Oob")})

;; ── URL приложений ────────────────────────────────────────────────────────────
(def ^:private flask-base-url
  (or (System/getenv "FLASK_URL") "http://kurs2.ybgv.cs.prv:5000"))

;; ── Генерация токена (Clojure → Flask) ───────────────────────────────────────

(defn create-sso-token!
  "Создаёт одноразовый SSO-токен для uid. Живёт 2 минуты."
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
  "Возвращает URL Flask с SSO-токеном для пользователя uid."
  [uid]
  (if-let [token (create-sso-token! uid)]
    (str flask-base-url "/sso?token=" token)
    (str flask-base-url "/login")))

;; ── Валидация токена (Flask → Clojure) ────────────────────────────────────────

(defn validate-sso-token!
  "Проверяет токен в БД. Если валидный — удаляет и возвращает uid. Иначе nil."
  [token]
  (when (and token (not (empty? token)))
    (try
      (let [rows (jdbc/query db-spec
                             ["SELECT uid FROM sso_tokens WHERE token = ? AND expires_at > NOW()"
                              token])]
        (when-let [uid (:uid (first rows))]
          (jdbc/delete! db-spec :sso_tokens ["token = ?" token])
          (log/info "SSO token validated for" uid)
          uid))
      (catch Exception e
        (log/error e "Failed to validate SSO token")
        nil))))
