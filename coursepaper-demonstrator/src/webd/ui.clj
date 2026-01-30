(ns ^{:doc    "Templates, snippets and HTML-generation functions for webd"
      :author "Anton Andreev"}
  webd.ui
  (:require [clojure.data.xml :as xml]
            [clojure.string :as s]
            [clojure.java.io :as io]
            [clojure.tools.logging :as log]
            [selmer.parser :as selmer]
            [hiccup.core :as hiccup]
            [webd.parsing :as parse]
            [webd.files :as wf])
  (:import [clojure.lang PersistentHashMap Keyword PersistentVector
                         Sequential]
           [java.time LocalDateTime Instant]))

#_(selmer/cache-off!)

(defn- get-cs []
  (with-open [rdr (io/input-stream "https://www.cs.petrsu.ru/news/")]
    (try
      (-> (xml/parse rdr :validating false :support-dtd false)
          :content second :content first xml/emit-str
          (clojure.string/replace #"</br>" "")
          (clojure.string/replace #"<br>" "<br/>")
          (clojure.string/replace #"<\?xml.*\?>" ""))
      (catch Exception e (log/error (str "Failed parsing CS header"
                                         (.getMessage e)))
                         ""))))

(defn- study-year [^String year]
  (str year "-" (inc (if (string? year) (read-string year) year))))

(defn- make-select-list [list stud-val]
  (for [v list]
    {:value v :selected (= v stud-val)}))

(defn page-index [cfg students logged?]
  (let [years (reverse (sort (set (map :years students))))]
    (selmer/render-file "page_webd.html"
                        {:header      (get-cs)
                         :years       years
                         :last-year   (first years)
                         :groups      (sort (set (map :groups students)))
                         :departments (:departments cfg)
                         :logged?     logged?})))

(defn page-templates [cfg logged?]
  (selmer/render-file "page_templates.html" {:header         (get-cs)
                                             :logged?        logged?
                                             :page-templates true}))

(defn page-login
  ""
  [cfg response logged?]
  (selmer/render-file "page_login.html" {:header   (get-cs)
                                         :logged?  logged?
                                         :response response}))

(defn page-identity
  ([cfg students logged? result]
   (let [students (reverse (sort-by :years students))
         student (first students)]
     (selmer/render-file "page_identity.html"
                         {:header          (get-cs)
                          :logged?         logged?
                          :student         student
                          :page-identity   true
                          :success?        (= result "true")
                          :result          (condp = result
                                             "true" "Работа успешно зарегистрирована"
                                             "false" "Ошибка при регистрации работы!"
                                             "invalid" "Регистрационные данные введены неверно!"
                                             nil)
                          :departments     (make-select-list (:departments cfg)
                                                             (student :department))
                          :ranks           (make-select-list ["без звания" "доцент" "профессор"]
                                                             (student :adviser-rank))
                          :positions       (make-select-list
                                             ["преподаватель" "ст. преподаватель"
                                              "доцент" "профессор" "заведующий кафедрой" "другая"]
                                             (student :adviser-position))
                          :have-prev-year? (= :none (:error (second students)))
                          :study-year      (study-year (:years student "1"))
                          :is-editable?    true})))
  ([cfg students logged? result username year]
   (let [year (if (string? year) (read-string year) year)
         student1 (first (reverse (sort-by :years students)))
         last-student (if (nil? student1) (first (reverse (sort-by :years (parse/query cfg {:logins username})))))
         year-dif (if-not (nil? last-student) (- (read-string (:years last-student)) year))
         student (if (and (nil? student1) (not (nil? last-student)) (< year (:current-year cfg)))
                   {:years     (str year)
                    :username  username
                    :full-name (:full-name last-student)
                    :courses   (- (read-string (:courses last-student)) year-dif)
                    :groups    (let [spl (clojure.string/split (:groups last-student) #"")
                                     group-year (read-string (first (take-last 3 spl)))]
                                 (clojure.string/join (flatten [(take (- (count spl) 3) spl)
                                                                (- group-year year-dif)
                                                                (take-last 2 spl)])))}
                   student1)
         is-editable? (or
                        (nil? year-dif)
                        (and (>= (cfg :editable-previous-years) year-dif)
                             (>= year-dif 0)))]
     (when (and is-editable? (nil? student1))
       (log/info "Initializing " username " in year " (str year))
       (when (wf/init-directory-structure! cfg username (:groups student) (str year))
         (parse/clear-cache)))
     (selmer/render-file "page_identity.html"
                         {:header          (get-cs)
                          :logged?         logged?
                          :student         student
                          :page-identity   true
                          :success?        (= result "true")
                          :result          (condp = result
                                             "true" "Работа успешно зарегистрирована"
                                             "false" "Ошибка при регистрации работы!"
                                             "invalid" "Регистрационные данные введены неверно!"
                                             nil)
                          :departments     (make-select-list (:departments cfg)
                                                             (:department student))
                          :ranks           (make-select-list ["без звания" "доцент" "профессор"]
                                                             (:adviser-rank student))
                          :positions       (make-select-list
                                             ["преподаватель" "ст. преподаватель"
                                              "доцент" "профессор" "другая"]
                                             (:adviser-position student))
                          :have-prev-year? false
                          :study-year      (study-year year)
                          :is-editable?    is-editable?}))))

(defn page-upload
  ""
  [cfg student logged? admin? result op for-doc]
  (selmer/render-file "page_upload.html"
                      {:header      (get-cs)
                       :logged?     logged?
                       :admin?      admin?
                       :student     student
                       :page-upload true
                       :study-year  (study-year (:years student "1"))
                       :files       (let [files (or (:files (first (filter #(re-matches (:groups %) (:groups student)) (:file-set cfg))))
                                                    (:file-set-default cfg))
                                          files-filtered (if admin? files (remove (:files-only-for-admin cfg) files))]
                                      (for [f files-filtered]
                                        {:for      (name f)
                                         :name     (condp = f
                                                     :int-report "Промежуточный отчет"
                                                     :int-slides "Промежуточная презентация"
                                                     :fin-report (if (.contains files :fin-antiplagiat) "Текст ВКР" "Окончательный отчет") ;fixme: make more reliable
                                                     :fin-slides (if (.contains files :fin-antiplagiat) "Презентация ВКР" "Окончательная презентация")
                                                     :fin-review "Рецензия"
                                                     :fin-sup-review "Отзыв руководителя"
                                                     :fin-antiplagiat "Проверка на плагиат"
                                                     :fin-preport "Отчет по практике НИР"
                                                     "Неизвестный документ")
                                         :link     (when-let [p (get-in student [:files f :path])]
                                                     (str (:projects-server cfg) "/" p "?v=" (rand-int 9999999)))
                                         :success? (= result "true")
                                         :result   (when (= for-doc (name f))
                                                     (condp = result
                                                       "true" (str #_"Файл успешно "
                                                                (if (= "save-file" op)
                                                                  "Загружено" "Удалено"))
                                                       "false" (str "Ошибка при "
                                                                    (if (= "save-file" op)
                                                                      "загрузке" "удалении")
                                                                    " файла!")
                                                       "413" (str "Ошибка при загрузке файла: "
                                                                  " недопустимы файлы размером"
                                                                  " более 10мб!")
                                                       "enotpdf" (str "Загруженный файл имеет"
                                                                      " недопустимый формат")
                                                       nil))}))
                       }))

(defn- get-link-to-file
  ""
  [^PersistentHashMap student ^PersistentHashMap cfg ^Keyword for]
  (when-let [p (get-in student [:files for :path])]
    (let [d (get-in cfg [:inner-structure for :last-date (str (:years student "2012")) (str (:courses student "3"))]
                    (get-in cfg [:inner-structure for :last-date :default]))]
      {:link    (str (:projects-server cfg) "/" p "?v=" (rand-int 9999999))
       :in-time (.isBefore (get-in student [:files for :creation-time])
                           (.toInstant (LocalDateTime/of (+ (Integer/parseInt
                                                              (:years student "2012"))
                                                            (first d))
                                                         (second d) (nth d 2) 0 0)
                                       java.time.ZoneOffset/UTC))})))

(defn- format-student [cfg index student]
  (merge (assoc student
           :index (inc index)
           :adviser-name-formatted (:adviser-name-formatted student "Не указано")
           :department (:department student "Не указано")
           :title (:title student "Не указано")
           :name (:name student "Не указано"))
         (reduce #(assoc %1 %2 (get-link-to-file student cfg %2))
                 {} (keys (:inner-structure cfg)))))

(defn form-result-as-is [cfg students sort-fn with-caption? admin?]
  (str (when with-caption?
         (hiccup/html [:h2 (str "Всего " (count students) " раб.")]))
       (let [some-student (first students)
             non-standard (some #(re-matches (:groups %) (:groups some-student)) (:file-set cfg))
             file-set (or (:files (first (filter #(re-matches (:groups %) (:groups some-student)) (:file-set cfg))))
                          (:file-set-default cfg))
             file-names {:int-report      "Пр. отчет"
                         :int-slides      "Пр. ЭП"
                         :fin-report      (if non-standard "Текст<br/>ВКР" "Отчет")
                         :fin-slides      (if non-standard "Презент.<br/>ВКР" "ЭП")
                         :fin-review      "Рецензия"
                         :fin-sup-review  "Отзыв<br/>руковод."
                         :fin-antiplagiat "Проверка на<br/>плагиат"
                         :fin-preport     "Отчет по<br/>практике<br/>НИР"}]
         (selmer/render-file "result-table.html" {:admin? admin?
                                                  :students
                                                          (map (fn [student] (assoc student :sfiles (map (fn [filekw] {:name (file-names filekw) :kw filekw :file (filekw student)}) file-set)))
                                                               (map-indexed
                                                                 (partial format-student cfg)
                                                                 (sort-fn students)))
                                                  :files  (map (fn [filekw] {:name (file-names filekw) :kw filekw}) file-set)
                                                  }))))

(defn form-result-default [cfg students sort-fn admin?]
  (s/join
    (flatten
      (for [[year y-studs] (reverse (sort-by first (group-by :years students)))]
        (cons
          (hiccup/html [:h2 (str (study-year year) " уч. год"
                                 " (" (count y-studs) " раб.)")])
          (for [[dep d-studs] (group-by :department y-studs)]
            (cons
              (hiccup/html [:h3 (str "Кафедра: " (or dep "Не указана")
                                     " (" (count d-studs) " раб.)")])
              (for [[group g-studs] (sort-by first (group-by :groups d-studs))]
                (str (hiccup/html
                       [:b (str "Группа: " group
                                " (" (count g-studs) " раб.)")])
                     (form-result-as-is cfg g-studs sort-fn false admin?))))))))))

(defn- get-sort-fn [method order]
  (let [cmp (if (= order :ascending) compare #(compare %2 %1))]
    (condp = method
      :by-identity-date (partial sort-by :identity-time cmp)
      :by-student-name (partial sort-by :name cmp)
      :by-adviser-name (partial sort-by :adviser-name-formatted cmp)
      identity)))

(defn form-result [cfg students group-method sort-method sort-order admin?]
  (let [sort-fn (get-sort-fn sort-method sort-order)]
    (condp = group-method
      :flatten (form-result-as-is cfg students sort-fn true admin?)
      (form-result-default cfg students sort-fn admin?))))

(defn page-query
  ([cfg students logged? admin?]
   (selmer/render-file "page_query.html" {:header  (get-cs)
                                          :logged? logged?
                                          :admin?  :admin?
                                          :query-result
                                                   (form-result-default cfg students
                                                                        (get-sort-fn :by-student-name :ascending)
                                                                        admin?)})))

(defn page-query-adviser
  [cfg students logged? admin?]
  (selmer/render-file "page_query.html" {:header       (get-cs)
                                         :subtitle     "Ваши студенты:"
                                         :page-adviser true
                                         :logged?      logged?
                                         :query-result
                                                       (form-result-default cfg students
                                                                            (get-sort-fn :by-student-name :ascending)
                                                                            admin?)}))
