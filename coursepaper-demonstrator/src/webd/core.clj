(ns ^{:doc    "Web app for distributed control for students coursepapers.
            This namespace contains all templates and controls for web-queryes"
      :author "Anton Andreev"}
  webd.core
  (:use [clojure.string :only [lower-case]]
        (ring.util [response :only [redirect]])
        (ring.middleware [keyword-params :only [wrap-keyword-params]]
                         [params :only [wrap-params]]
                         [multipart-params :only [wrap-multipart-params]]
                         [session :only [wrap-session]]))
  (:require (webd [parsing :as parse]
                  [doc :as doc]
                  [files :as wf]
                  [auth :as auth]
                  [ui :as ui])
            (ring.util [io :as rio])
            [clojure.java.io :as io]
            [clojure.tools.logging :as log]
            [compojure.core :refer [defroutes POST GET ANY]]
            [compojure.route :as croute])
  (:import [clojure.lang PersistentHashMap]))

(def cfg-file-name "config.clj")

(defn load-cfg
  "Seeks `config.clj` or passed filename on classpath
   and loads it with exception handling."
  []
  (try
    (read-string (slurp (io/file (io/resource cfg-file-name))))
    (catch java.io.FileNotFoundException _
      (throw (Exception. "No config file")))
    (catch Exception _
      (throw (Exception. "Config can't be parsed")))))

(defn- prepare-form-param
  "Prepares parameters that had been passed from query-form
   to be used in query.
   Removes empty lines in params and handles param about :have-index"
  [params param]
  (let [filtered-params (if (or (empty? (str (params param)))
                                (#{:sort-order :sort-method :group-method} param))
                          (dissoc params param) params)]
    (if-let [v (filtered-params param)]
      (letfn [(pattern [param]
                (assoc filtered-params param
                                       (re-pattern (str (lower-case v) ".*"))))]
        (condp = param
          :have-index (condp = (:have-index filtered-params)
                        "registered" (dissoc (assoc filtered-params :error :none)
                                             :have-index)
                        "unregistered" (dissoc (assoc filtered-params :error :no-index-file)
                                               :have-index)
                        "all" (dissoc filtered-params :have-index)
                        filtered-params)
          :name (pattern param)
          :adviser-name (pattern param)
          filtered-params))
      filtered-params)))

(defn- v-required [v]
  (if (empty? v) (throw (Exception.))
                 true))

(defn- v-pattern [pattern v]
  (if-not (re-matches pattern v) (throw (Exception.))
                                 true))

(def ^:private user-form-validator
  {:title            [v-required]
   :adviser-name     [v-required
                      (partial v-pattern #"([А-Я|A-Z]\.\s?){1,2}[А-Я|A-Z][А-Я|A-Z|а-я|a-z]{0,20}(,\s?([А-Я|A-Z]\.\s?){1,2}[А-Я|A-Z][А-Я|A-Z|а-я|a-z]{0,20})*")]
   :adviser-position [v-required]
   :department       [v-required]})

(defn- validate [params validator]
  (try
    (every? true?
            (flatten
              (map (fn [[param v-fns]]
                     (map #(% (param params)) v-fns))
                   validator)))
    true
    (catch Exception _ false)))

(defn- query-with-form
  "Queryes collection of students found on disk with use of
   params POSTed from form (webd.html). Handles passed params
   to make them correspond our students inner structure."
  [^PersistentHashMap params ^PersistentHashMap cfg]
  (parse/query cfg (reduce prepare-form-param params (keys params))))

(defn- student-identifiers
  ([student]
   {:logins  (:logins student)
    :years   (:years student)
    :courses (:courses student)
    :groups  (:groups student)})
  ([student year]
   (let [stud (parse/get-student (load-cfg) {:logins (:logins student) :years year} year)]
     (log/info student stud)
     {:logins  (:logins student)
      :years   year
      :courses (:courses stud)
      :groups  (:groups stud)})))

;; Here goes the handler-functions that are handlers of Ring-requests
;; all of them returnes or map (that is response), or string (that is content
;; of response). `*-get` handlers consumes HTTP GET request and `*-post` handlers
;; consumes HTTP POST request.
;; All of this functions are used in compojure's `defroutes`
(defn- handler-login-get [cfg logged? fail?]
  (if logged?
    (redirect (if (= logged? :rstudent) "/user/identity" "/"))
    (ui/page-login cfg (when fail? "Не удалось войти!") logged?)))

(defn- handler-login-post [cfg session username password]
  (log/info username " tried to log in")
  (let [correct? (auth/login? cfg username password)
        admin? (auth/login-test? cfg username password)
        student (parse/get-student cfg {:logins username})
        gn (or (auth/get-group-ldap cfg username) (:groups student))
        initialized (when (or (and correct? gn #_(not student) (not= (:groups student) gn))
                              (and correct? gn student))    ;;TODO: delete after 2020
                      (wf/init-directory-structure! cfg username gn))
        cleared (when initialized (parse/clear-cache))
        student (parse/get-student cfg {:logins username})
        ]
    (log/info "admin logged in?" admin?)
    (log/info "log in registered" student gn initialized)
    (-> (redirect (if (and correct? student) "/user/identity"
                                             (if correct?
                                               ;user is a lecturer, query for his students
                                               "/query-adviser"
                                               "/login?fail=t")))
        (assoc :session
               (merge session
                      {:logged? (if correct? (if student :rstudent :rother) false)
                       :admin?  admin?}
                      (student-identifiers student)
                      {:logins username})))))

(defn- handler-init-student [cfg logged? username]
  (if (and logged? username)
    (do
      (log/info "Initializing " username " in year " (str (:current-year cfg)))
      (let [student (parse/get-student cfg {:logins username})
            gn (auth/get-group-ldap cfg username)
            initialized (when (and gn (or (not= (:groups student) gn) (not= (str (:years student)) (str (:current-year cfg)))))
                          (wf/init-directory-structure! cfg username gn))
            cleared (when initialized (parse/clear-cache))
            student-y (:years (parse/get-student cfg {:logins username}))]
        (redirect (str "/?y=" student-y))))
    (redirect "/login")))

(defn- handler-delete-student [cfg logged-and-admin? username year]
  (if (and logged-and-admin? username year)
    (do
      (log/info "Deleting " username " in year " year)
      (let [student (parse/get-student cfg {:logins username :years year})
            initialized (when student
                          (wf/delete-user-dir! cfg student))
            cleared (when initialized (parse/clear-cache))]
        (redirect "/")))
    (redirect "/login")))

(defn- handler-file-post [cfg {for-doc :for-doc :as params}
                          logged? {username :logins year :years :as user-params} op]
  (if (= logged? :rstudent)
    (do
      (log/info username " requested " op " operation.")
      (let [result (condp = op
                     "delete-file" (wf/delete-doc-file!
                                     cfg user-params (keyword for-doc))
                     "save-file" (wf/store-doc-file!
                                   cfg user-params (keyword for-doc)
                                   (get-in params [:doc-file :tempfile]))
                     (log/error "Wrong file operation " op))
            cleared (when (= result :success) (parse/clear-cache))]
        (redirect (format "/user/file/%s?operation=%s&result=%s&for-doc=%s"
                          year
                          op (condp = result
                               :success true
                               :enotpdf "enotpdf"
                               false) for-doc))))
    (redirect "/login")))

(defn- handler-report-post [cfg params logged?]
  (log/info "Someone requested report document")
  (if logged?
    {:status  200
     :headers {"Content-Type" "application/pdf"}
     :body    (rio/piped-input-stream
                ;; to transfer a file
                (partial doc/to-pdf
                         (query-with-form params cfg)
                         (:pdf-table-struct cfg)
                         (:pdf-table-titles cfg)
                         (:pdf-table-widths cfg)))}
    (redirect "/login")))

(defn- handler-missing-post [cfg {groups :groups :as params} logged?]
  (log/info "Someone requested report (for missing) document")
  (if logged?
    {:status  200
     :headers {"Content-Type" "application/pdf"}
     :body    (rio/piped-input-stream
                ;; to transfer a file
                (partial doc/to-pdf-missing
                         (parse/get-not-registered-users-with-ldap cfg groups)
                         (:current-year cfg)))}
    (redirect "/login")))

(defn- handler-directive-post [cfg params logged?]
  (log/info "Someone requested directive document")
  (if logged?
    {:status  200
     :headers {"Content-Type" "application/rtf"}
     :body    (rio/piped-input-stream
                ;; to transfer a file
                (partial doc/rtf-directive
                         cfg
                         (query-with-form params cfg)))}
    (redirect "/login")))

(defn- handler-identity-post [cfg params logged?
                              {username :logins year :years :as user-params} copy?]
  (if (= logged? :rstudent)
    (let [result (if copy?
                   (do (log/info username " trying to copy data")
                       (wf/copy-user-data! cfg user-params))
                   (do (log/info username " trying to save data")
                       (if (validate params user-form-validator)
                         (wf/save-user-data! cfg user-params params)
                         :invalid)))
          cleared (when (= result :success) (parse/clear-cache))]
      (redirect (str "/user/identity/" year "?result=" (condp = result
                                                         :success "true"
                                                         :invalid "invalid"
                                                         "false"))))
    (redirect "/login")))

(defn- handler-identity-get
  ([cfg logged? page username result year]
   (if (= logged? :rstudent)
     (ui/page-identity cfg (parse/query cfg {:logins username :years year})
                       logged? result
                       username year)
     (redirect "/login")))
  ([cfg logged? page username result]
   (if (= logged? :rstudent)
     (ui/page-identity cfg (parse/query cfg {:logins username})
                       logged? result)
     (redirect "/login"))))

(defn- handler-file-get [cfg logged? admin? page user-params {result  :result
                                                              for-doc :for-doc
                                                              op      :operation}]
  (log/info user-params)
  (if (= logged? :rstudent)
    (let [std (parse/get-student cfg user-params)]
      (if (nil? std)
        (redirect "/user/identity")
        (ui/page-upload cfg (parse/get-student cfg user-params)
                        logged? admin? result op for-doc)))
    (redirect "/login")))


(defn- handler-query-post [cfg {sort-method  :sort-method
                                sort-order   :sort-order
                                group-method :group-method
                                :as          params}
                           logged? admin?]
  (if logged?
    (if-let [students (seq (query-with-form params cfg))]
      (ui/form-result cfg students (keyword group-method) (keyword sort-method) (keyword sort-order) admin?)
      "По вашему запросу ничего не найдено.")
    "Не авторизованный доступ"))

(defn- handler-query-get [cfg params logged? admin?]
  (if logged?
    (if-let [students (seq (query-with-form params cfg))]
      (ui/page-query cfg students logged? admin?)
      "По вашему запросу ничего не найдено.")
    "Не авторизованный доступ"))

(defn- handler-query-get-advisors-students [cfg uid logged? admin?]
  (if logged?
    (let [an (auth/get-sn-ldap cfg uid)]
      (log/info "Adviser name: " an)
      (if-let [students (seq (if an (query-with-form {:adviser-name an} cfg) []))]
        (ui/page-query-adviser cfg students logged? admin?)
        (redirect "/")))
    "Не авторизованный доступ"))

(defroutes
  router
  "Routing function for webd with all routes described."
  (GET "/" {{logged? :logged?} :session}
    (let [cfg (load-cfg)]
      (ui/page-index cfg (if logged? (parse/query cfg {}) []) logged?)))
  (POST "/query" {params                            :params
                  {logged? :logged? admin? :admin?} :session}
    (handler-query-post (load-cfg) params logged? admin?))
  (GET "/query" {params                            :params
                 {logged? :logged? admin? :admin?} :session}
    (handler-query-get (load-cfg) params logged? admin?))
  (GET "/query-adviser" {params                                             :params
                         {username :logins logged? :logged? admin? :admin?} :session}
    (handler-query-get-advisors-students (load-cfg) username logged? admin?))
  (POST "/query/report" {params             :params
                         {logged? :logged?} :session}
    (handler-report-post (load-cfg) params logged?))
  (POST "/query/missing" {params             :params
                          {logged? :logged?} :session}
    (handler-missing-post (load-cfg) params logged?))
  (POST "/query/directive" {params             :params
                            {logged? :logged?} :session}
    (handler-directive-post (load-cfg) params logged?))
  (GET "/templates" {{logged? :logged?} :session}
    (ui/page-templates (load-cfg) logged?))
  (GET "/login" {{fail? :fail}      :params
                 {logged? :logged?} :session}
    (handler-login-get (load-cfg) logged? fail?))
  (GET "/login/exit" {} (-> (redirect "/") (assoc :session {})))
  (GET "/user-init" {{username :uid}    :params
                     {logged? :logged?} :session}
    (handler-init-student (load-cfg) logged? username))
  (GET "/user-delete" {{username :uid year :year} :params
                       {logged? :logged? admin? :admin?}         :session}
    (handler-delete-student (load-cfg) (and logged? admin?) username year))
  (POST "/login" {{username :username password :password} :params
                  session                                 :session}
    (handler-login-post (load-cfg) session username password))
  (GET "/user/identity" {{username :logins logged? :logged?} :session
                         {result :result}                    :params}
    (handler-identity-get (load-cfg) logged? :identity username result))
  (POST "/user/identity" {params                         :params
                          {logged? :logged? :as session} :session}
    (handler-identity-post (load-cfg) params logged?
                           (student-identifiers session) false))
  (GET "/user/identity/:year" {{username :logins logged? :logged?} :session
                               {result :result year :year}         :params}
    (handler-identity-get (load-cfg) logged? :identity username result year))
  (POST "/user/identity/:year" {{year :year :as params}        :params
                                {logged? :logged? :as session} :session}
    (handler-identity-post (load-cfg) params logged?
                           (student-identifiers session year) false))
  (POST "/user/copy" {params                         :params
                      {logged? :logged? :as session} :session}
    (handler-identity-post (load-cfg) params logged?
                           (student-identifiers session) true))
  (GET "/user/file/" {} (redirect "/user/file"))
  (GET "/user/file" {{logged? :logged? admin? :admin? :as session} :session
                     params                                        :params}
    (handler-file-get (load-cfg) logged? admin? :upload
                      (student-identifiers session) params))
  (GET "/user/file/:year" {{logged? :logged? admin? :admin? :as session} :session
                           {year :year :as params}                       :params}
    (handler-file-get (load-cfg) logged? admin? :upload
                      (student-identifiers session year)
                      params))
  (POST "/user/file/:year/upload" {{year :year :as params}        :params
                                   {logged? :logged? :as session} :session}
    (handler-file-post (load-cfg) params logged?
                       (student-identifiers session year) "save-file"))
  (POST "/user/file/:year/delete" {{year :year :as params}        :params
                                   {logged? :logged? :as session} :session}
    (handler-file-post (load-cfg) params logged?
                       (student-identifiers session year) "delete-file"))
  (POST "/user/file/delete" {params                         :params
                             {logged? :logged? :as session} :session}
    (handler-file-post (load-cfg) params logged?
                       (student-identifiers session) "delete-file"))
  (POST "/user/file/upload" {params                         :params
                             {logged? :logged? :as session} :session}
    (handler-file-post (load-cfg) params logged?
                       (student-identifiers session) "save-file"))
  (croute/resources "/")
  (croute/not-found "not found"))

(defn destroy []
  (parse/clear-cache))

(def app (-> router
             (wrap-session {:cookie-attrs {:max-age 1800}})
             wrap-keyword-params
             wrap-params
             wrap-multipart-params))
