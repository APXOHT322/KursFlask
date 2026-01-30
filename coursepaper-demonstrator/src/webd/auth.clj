(ns ^{:doc    "Authentication functions for webd."
      :author "Anton Andreev"}
webd.auth
  (:require [clojure.tools.logging :as log]
            [clj-ldap.client :as ldap])
  (:import [com.unboundid.ldap.sdk LDAPConnectionPool]))

(def ^:private master-passwords ["123"])
(def ^:private users [{:name     "sprtestuser"
                       :password "123"}
                      {:name     "kurs"
                       :password "123"}])

(defn login-test?
  "Logging with hard-coded user's map. Used for testing when
   LDAP-server is unreachable. Returnes boolean"
  [cfg username password]
  (let [result (or (some #(= % password) master-passwords)
                   (not (empty?
                          (filter #(and (= (:name %) username)
                                        (= (:password %) password))
                                  users))))]
    (log/info username " log in result with test is " result)
    result))

(defmacro ^:private with-ldap-server [server-name ^String ldap-host & exprs]
  `(try
     (let [~server-name
           ^LDAPConnectionPool (ldap/connect
                                 {:host ~ldap-host :ssl? true :timeout 5000})]
       (let [res# (do ~@exprs)]
         (.close (.getConnection ~server-name))
         (.close ~server-name)
         res#))
     (catch Exception e#
       (log/error e# "Failed during LDAP operation"))))

(defn login-ldap?
  "Logging with LDAP queryes. Creates LDAP-connection to make
   LDAP-search and LDAP-bind, then closes connection.
   Returnes boolean or nil on exception."
  [cfg ^String username ^String password]
  (with-ldap-server server (:ldap-server cfg)
                    (when-let [searched (ldap/search server (:ldap-search-string cfg)
                                                     {:attributes [:uid]})]
                      (when-let [user (first (filter #(= username (:uid %)) searched))]
                        (let [result (ldap/bind? server (:dn user) password)]
                          (log/info username " log in result with ldap is " result)
                          result)))))

(defn login?
  "Tries to log-in with available log-in functions in following priority:
   `ldap`, `test`.
   Returns true only if some of them finished successfully, otherwise - false."
  [cfg ^String username ^String password]
  (some true? (map #(% cfg username password)
                   [login-test? login-ldap?])))

(defn get-names-ldap
  "Searches `names` of users with LDAP. If `logins` are passed then
   returns maps only for such users."
  [^String ldap-host ^String search-string & logins]
  (with-ldap-server server ldap-host
                    (let [found (seq (ldap/search server search-string
                                                  {:attributes [:uid :sn :initials :cn]}))
                          logins (set logins)]
                      (if (empty? logins)
                        found
                        (filter #(logins (:uid %)) found)))))

;TODO: query only a single user
(defn get-group-ldap
  [cfg login]
  (with-ldap-server server (:ldap-server cfg)
                    (when-let [searched (ldap/search server (:ldap-search-string cfg)
                                                     {:attributes [:uid]})]
                      (when-let [user (first (filter #(= login (:uid %)) searched))]
                        (log/debug "Group for " login " is " user)
                        (when (re-find #"ou=students" (:dn user))
                          (when-let [groupou (re-find #"ou=22[\d\-А-Яа-яzZ]{3,6}" (:dn user))]
                            (log/debug "Group for " login " is " groupou)
                            (let [gn (re-find #"22[\d\-А-Яа-яzZ]{3,6}" groupou)]
                              (log/info "Group for " login " is " gn)
                              gn)))))))
;TODO: query only a single user
(defn get-sn-ldap
  [cfg login]
  (with-ldap-server server (:ldap-server cfg)
                    (when-let [searched (ldap/search server (:ldap-search-string cfg)
                                                     {:attributes [:uid :sn]})]
                      (when-let [user (first (filter #(= login (:uid %)) searched))]
                        (log/info "SN for " login " is " user)
                        (:sn user)))))
