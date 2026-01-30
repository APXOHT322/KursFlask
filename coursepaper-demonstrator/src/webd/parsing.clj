(ns ^{:doc    "Functions that are seeks files of students, parses them
            and queryes results."
      :author "Anton Andreev"}
  webd.parsing
  (:require [webd.auth :as auth]
            [clojure.xml :as xml]
            [clojure.java.io :as io]
            [clojure.string :as s]
            [clojure.zip :as zip]
            [clojure.tools.logging :as log]
            [clojure-watch.core :as clj-watch])
  (:import [clojure.lang PersistentHashMap Keyword PersistentVector IFn]
           [java.io File FileNotFoundException]
           [java.nio.file Paths Files LinkOption]
           [java.nio.file.attribute FileTime]
           [java.time LocalDateTime Instant]))

(defmulti parse-index
          "Parses index file in path `root/path/filename`.
           Chooses parser basing on file extension."
          (fn [^String root ^String path ^String filename]
            (when filename
              (last (re-seq #"[\\.][a-z]*" filename))))
          :default nil)

(defmethod parse-index nil [_ ^String path _]
  {:path path :error :no-index-file})

(defn- parse-file-times [path]
  (try
    (let [attrs (Files/readAttributes
                  (Paths/get path (into-array String []))
                  "*"
                  ^"[Ljava.nio.file.LinkOption;" (into-array LinkOption []))]
      {:creation-time  (.plusSeconds
                         (.toInstant ^FileTime (get attrs "creationTime"))
                         10800)
       :modifying-time (.plusSeconds
                         (.toInstant ^FileTime (get attrs "lastModifiedTime"))
                         10800)})
    (catch Exception _
      (log/warn "Cannot get times for file " path)
      {})))

(defn- parse-index-file-times [^String root ^String path ^String filename]
  (let [times (parse-file-times (str root "/" path "/" filename))]
    {:index-creation-time  (:creation-time times)
     :index-modifying-time (:modifying-time times)}))

(defn- parse-base
  "Parses file with `filename` at given `path` in `root` folder.
   Parses it with `parser` function that takes one argument - fullpath.
   In result map `{:format format}` will be added."
  [^String root ^String path ^String filename
   ^Keyword format ^IFn parser]
  (let [parsed (parser (str root "/" path "/" filename))]
    (merge {:path path :format format :error :none}
           (if (keyword? parsed) {:error parsed}
                                 (merge (parse-index-file-times root path filename) parsed)))))

(defn- assert-map [val]
  (if (map? val) val
                 (do (log/error "Index file contains not a map object")
                     (throw (Exception. "Not a map")))))

(defn- stringify-vals
  ([except associative]
   (reduce (fn [m [k v]] (assoc m k (if (except k) v (str v))))
           {} associative))
  ([associative]
   (stringify-vals associative #{})))

(defmacro ^:private safe-parse [^String path parse-expr & transform-fns]
  `(try
     (-> ~parse-expr ~@transform-fns)
     (catch FileNotFoundException e1#
       (log/warn "index file at " ~path " not found")
       :file-not-found)
     (catch Exception e2#
       (log/warn "Failed parsing index file at " ~path)
       :parse-failed)))

(defmethod parse-index ".clj" [^String root ^String path ^String filename]
  (parse-base root path filename :clj
              (fn [path]
                (safe-parse path (read-string (slurp path))
                            assert-map
                            ((partial stringify-vals #{:files}))))))

(defn- xml-get-inner-element-content
  "Returnes content of `tag` element that is placed
   into content of `root` element (that should be XML-map)"
  [root tag]
  (when-let [res (-> (filter #(= tag (:tag %)) (:content root))
                     first :content first)]
    (str res)))

(defn- xml-extract-content
  "Extracts info about student from parsed XML. Returnes map."
  [parsed]
  (let [adviser (first (filter #(= :adviser (:tag %))
                               (:content parsed)))]
    {:name           (xml-get-inner-element-content parsed :name)
     :adviser-name   (xml-get-inner-element-content adviser :name)
     :adviser-status (xml-get-inner-element-content adviser :status)
     :department     (xml-get-inner-element-content parsed :department)
     :title          (xml-get-inner-element-content parsed :title)}))

(defmethod parse-index ".xml" [^String root ^String path ^String filename]
  (parse-base root path filename :xml
              (fn [path]
                (safe-parse path (xml/parse path) xml-extract-content))))

(defn- get-dir-names
  "Returnes list of directories on path"
  [^String path]
  (map #(.getName ^File %) (filter #(.isDirectory ^File %)
                                   (.listFiles ^File (io/file path)))))

(defn- get-file-names
  "Returnes list of non-directory files on path"
  [^String path]
  (map #(.getName ^File %) (filter #(.isFile ^File %)
                                   (.listFiles ^File (io/file path)))))

(defn get-first-index-file
  "Returns name of first index file on path.
   `i-f-name` contains string with possible filename.
   `i-f-exts` is a collection of possible file extensions
    (strings without dots!)."
  [^String path ^String i-f-name ^PersistentVector i-f-exts]
  (first (filter (partial re-matches
                          (re-pattern (str i-f-name "[\\.]" "(?:"
                                           (s/join "|" i-f-exts) ")")))
                 (sort (get-file-names path)))))

(defn- if-doc-exists
  "Compiles path to document described by `for` exlusively for student,
   checks if this file exists. Returnes compiled path if document exists,
   `:not-exists` otherwise."
  [^String root ^String path-to-student ^Keyword for ^PersistentHashMap inner-struct]
  (let [p (str (get-in inner-struct [for :path]) "/"
               (get-in inner-struct [for :file-name]) "."
               (get-in inner-struct [for :file-ext]))]
    (when (.exists (io/as-file (str root "/" path-to-student "/" p)))
      (let [path-to-doc (str path-to-student "/" p)]
        (merge {:path path-to-doc} (parse-file-times (str root "/" path-to-doc)))))))

(defn- add-paths-to-docs
  "Check for existence all student's documents and adds to user-map
   paths to them (or sets them to `:not-exists`)"
  [^PersistentHashMap student ^String root ^PersistentHashMap inner-struct]
  (assoc student :files
                 (reduce (fn [files for]
                           (merge-with #(if (:creation-time %1)
                                          (merge %2 %1)
                                          (merge %1 %2))
                                       files {for (if-doc-exists root (:path student)
                                                                 for inner-struct)}))
                         (:files student {})
                         (keys inner-struct))))

(defn- prefilter
  "Filters out directories and files that should not be handled
   as noted in `prefilter-map`.
   Names of files are passed in `dirs` arg.
   prefilter-map can include two maps: :include and :exclude
   with keywords and regexes. Keywords must correspond with
   directory-roles (i.e. :logins or :years).
   At first, all dirs that not matches `:include` map are removed.
   Then from remaining list all dirs that matches `:exclude` map are removed."
  [^PersistentHashMap {incl-m :include
                       excl-m :exclude
                       :as    prefilter-map} ^Keyword dir-role dirs]
  (let [included (if-let [incl (incl-m dir-role)]
                   (filter (partial re-matches incl) dirs)
                   dirs)]
    (if-let [excl (excl-m dir-role)]
      (remove (partial re-matches excl) included)
      included)))

(defn- get-all-students-local
  "Seeks all students in `root` folder with use of `path-structure`.
   `inner-struct` must contain fields for paths to documents.
   And prefilter map must be such as in cfg.
   All other arguments must be also as in cfg.
   Returns seq of maps representing students.
   Uses zipper to traverse folders."
  [{root            :projects-root
    path-structure  :path-structure
    inner-structure :inner-structure
    prefilter-map   :prefilter
    i-f-n           :index-file-name i-f-x :index-file-exts
    :as             cfg}]
  (->> (zip/zipper #(not (empty? (:roles %)))
                   (fn [{path :path [role & rem-roles] :roles :as node}]
                     (map #(merge node {role   %
                                        :roles rem-roles
                                        :path  (str path "/" %)})
                          ;; before we go in folders we must filter out some that
                          ;; had been placed in `prefilter` argument
                          (prefilter prefilter-map role
                                     (get-dir-names (str root "/" path)))))
                   nil
                   {:path nil :roles path-structure})
       (iterate zip/next)
       (take-while (complement zip/end?))
       (filter (complement zip/branch?))
       (map #(dissoc (zip/node %) :roles))
       (remove nil?)
       (pmap (fn [{path :path :as s}]
               (merge
                 s (-> (parse-index root path (get-first-index-file
                                                (str root "/" path)
                                                i-f-n i-f-x))
                       (add-paths-to-docs root inner-structure)))))))

(defn- get-names-with-ldap
  [cfg]
  (reduce (fn [m nm]
            (assoc m (:uid nm) {:name      (str (:initials nm) " " (:sn nm))
                                :full-name (str (:cn nm))}))
          {}
          (auth/get-names-ldap (:ldap-server cfg)
                               (:ldap-search-string cfg))))

(defn- filter-departments
  "Checks if departments of students are included in allowed-map,
   if not - replaces them by default department"
  [{deps :departments def-dep :default-department
    :as  cfg} student]
  (if (or (not= (:error student) :none) (contains? deps (:department student)))
    student (assoc student :department def-dep)))

(defn- parse-date [student ^String date ^Instant alternative]
  (try
    (Instant/parse date)
    (catch Exception e
      (format "Time '%s' of student '%s' in year '%s' is bad-formatted"
              date (:logins student) (:years student))
      alternative)))

(defn- parse-dates [cfg student]
  (reduce #(let [prev (get-in %1 [:files %2 :creation-time])]
             (assoc-in %1 [:files %2 :creation-time]
                       (if (instance? Instant prev) prev
                                                    (parse-date student prev nil))))
          (assoc student
            :identity-time (parse-date student
                                       (:identity-time student)
                                       (:index-creation-time student)))
          (keys (:inner-structure cfg))))

(defn- format-name [student name]
  (when-not (nil? name)
    (try
      (s/join
        ", "
        (map (fn [single-name]
               (let [[i o f :as nms]
                     (sort-by count (re-seq #"[А-ЯЁ|A-Z][А-ЯЁ|а-яё]{0,20}" single-name))
                     nms (remove nil? nms)]
                 (when (not-every? #(not= nil %) nms) (throw (Exception.)))
                 (if (or (every? #(< 1 (count %)) nms) (> 3 (count nms)))
                   single-name                              ; kostyl'
                   (format "%c. %c. %s" (first i) (first o) f))))
             (s/split name #",[\s]*")))
      (catch Exception _
        (log/warn (format "Name '%s' of student '%s' in year '%s' is bad-formatted"
                          name (:logins student) (:years student)))))))

(defn- format-student [{name  :name adv-name :adviser-name
                        login :logins :as student}]
  (assoc student
    :name (if-let [n (format-name student name)] n login)
    :adviser-name-formatted (format-name student adv-name)))

(defn get-all-students
  "Function for searching data about students.
   `cfg` is the same as in config-file.
   Returnes seq of maps representing students"
  [cfg]
  (let [names (get-names-with-ldap cfg)]
    (->> (get-all-students-local cfg)
         (map (fn [{login :logins :as student}]
                (-> student
                    (merge (names login {:name      (:name student login)
                                         :full-name (:name student login)}))
                    ((partial filter-departments cfg))
                    format-student
                    ((partial parse-dates cfg)))))
         ;; Taking only last student record in a year
         (group-by #(list (:logins %) (:years %)))
         (map #(last (sort-by :courses (second %))))
         flatten
         )))

(defn- to-pattern
  "Transforms passed values to regex pattern.
   Single value or collection could be passed."
  [vals]
  (re-pattern (cond
                (empty? (str vals)) ".*"
                (coll? vals) (s/join "|" vals)
                :default (str vals))))

(defn get-all-students-prefiltered
  "Same as `get-all-students` but will be parsed only such directories that
   are included in `q-cfg` param. Function just transforms passed in `q-cfg`
   values or collections to regex-patterns and passes it to `get-all-students`
   as `:prefilter` in `cfg`"
  [cfg {years   :years
        groups  :groups
        courses :courses
        logins  :logins
        :as     q-cfg}]
  (get-all-students
    (assoc-in cfg [:prefilter :include]
              {:years   (if years (to-pattern years)
                                  (get-in cfg [:prefilter :include :years]))
               :groups  (if groups (to-pattern groups)
                                   (get-in cfg [:prefilter :include :groups]))
               :courses (if courses (to-pattern courses)
                                    (get-in cfg [:prefilter :include :courses]))
               :logins  (if logins (to-pattern logins)
                                   (get-in cfg [:prefilter :include :logins]))})))

;;TODO: better cache, f.e. always when something is done on file (without watch)
(defonce students-cache (atom {:watched? false
                               :cached?  false
                               :changed? true
                               :students nil
                               :watcher  nil}))

(defn clear-cache []
  (when-let [watcher (:watcher @students-cache)]
    (log/info "Stop watching")
    (watcher))
  (swap! students-cache assoc :watched? false :cached? false :changed? true :students nil :watcher nil))

(defn get-all-students-cached [cfg]
  (swap! students-cache assoc :cfg cfg)
  (when-not (:watched? @students-cache)
    (let [watcher
          (clj-watch/start-watch
            (for [dir (prefilter (:prefilter cfg) :years
                                 (get-dir-names (:projects-root cfg)))]
              {:path        (str (:projects-root cfg) "/" dir)
               :event-types [:create :modify :delete]
               :callback    (fn [event filename]
                              (swap! students-cache assoc :changed? true)
                              (log/info (str "Operation " event " detected on " filename)))
               :options     {:recursive true}}))]
      (swap! students-cache assoc :watched? true :watcher watcher)))
  (when (:changed? @students-cache)
    (swap! students-cache assoc :students (get-all-students cfg) :changed? false))
  (:students @students-cache))

(defn get-all-students-cached-last-year [cfg {years   :years
                                              groups  :groups
                                              courses :courses
                                              logins  :logins
                                              :as     q-cfg}]
  (swap! students-cache assoc :cfg cfg)
  (when-not (:cached? @students-cache)
    (swap! students-cache assoc :cached? true
           :students (get-all-students (assoc-in cfg [:prefilter :exclude] {:years (to-pattern (str (:current-year cfg)))}))))
  (concat (:students @students-cache)
          (get-all-students-prefiltered cfg (assoc q-cfg :years (str (:current-year cfg))))
          #_(get-all-students (assoc-in cfg [:prefilter :include]
                                        {:years   (to-pattern (str (:current-year cfg)))
                                         :groups  (if groups (to-pattern groups)
                                                             (get-in cfg [:prefilter :include :groups]))
                                         :courses (if courses (to-pattern courses)
                                                              (get-in cfg [:prefilter :include :courses]))
                                         :logins  (if logins (to-pattern logins)
                                                             (get-in cfg [:prefilter :include :logins]))}))))

(defn query
  "Queries passed students-collection with `q-cfg` map.
   `q-cfg` must be a map with keys-keywords that might present
   in students-map. And its values could be either IFns (sets
   for example) or distinct values (strings or keywords).
   IFn possibilities of Keywords here are ignored.
   Returns filtered students collection.
   If last argument absent then project directory will be parsed
   with use of config in `cfg`."
  ([cfg q-cfg students]
   (filter (fn [stud]
             (every? #(true? (boolean %))
                     (map (fn [[^Keyword k v]]
                            (cond
                              (empty? (str v)) true         ;; nothing to compare with
                              (coll? v) ((set v) (k stud))
                              (instance? java.util.regex.Pattern v)
                              (when (k stud) (re-find v (s/lower-case (k stud))))
                              :default (= v (k stud))))
                          q-cfg)))
           students))
  ([cfg q-cfg]
   (query cfg q-cfg (condp = (:query-optimization cfg)
                      :none (get-all-students cfg)
                      :last-year-only (get-all-students-cached-last-year cfg q-cfg)
                      :cached (get-all-students-cached cfg)
                      :prefiltered (get-all-students-prefiltered cfg q-cfg)
                      (get-all-students cfg)))))

(defn get-student
  "Returns user-map for params that must contain valid `:logins`,
   `:years`, `:courses` and `:groups`.
   If such user exists - map will be returned. Otherwise returns nil.
   Returns user of lats available year"
  ([cfg {username :logins years :years courses :courses groups :groups}]
   (last (sort-by (juxt :years :courses) (query cfg {:logins  username
                                                     :years   years
                                                     :courses courses
                                                     :groups  groups}))))
  ([cfg {username :logins courses :courses groups :groups} year]
   (last (sort-by (juxt :years :courses)
                  (filter #(= year (:years %))
                          (query cfg {:logins  username
                                      :years   year
                                      :courses courses
                                      :groups  groups}))))))

(defn get-active-students-users-with-ldap
  [cfg]
  (reduce (fn [l u]
            (conj l {:logins    (:uid u)
                     :name      (str (:sn u) " " (:initials u))
                     :full-name (str (:cn u))
                     :groups    (clojure.string/replace (re-find #"ou=22[\d\-А-ЯZzа-я]{3,6}" (:dn u)) "ou=" "")
                     :dn        (:dn u)}))
          []
          (filter (fn [u] (and (:uid u) (re-find #"ou=students" (:dn u)) (not (re-find #"ou=delete" (:dn u)))))
                  (auth/get-names-ldap (:ldap-server cfg)
                                       (:ldap-search-string cfg)))))

(defn get-not-registered-users-with-ldap
  [cfg groups]
  (let [users (get-active-students-users-with-ldap cfg)
        filtered (set (prefilter (:prefilter cfg) :groups (map :groups users)))
        groups-filtered (if (empty? groups) filtered (set (filter (set (if (vector? groups) groups (vector groups))) filtered))) ;todo: improve! forgot how to clojure
        studs (set (map :logins (query cfg {:years (str (:current-year cfg))})))]
    (remove #(or (studs (:logins %)) (not (groups-filtered (:groups %)))) users)))
