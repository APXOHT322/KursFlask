(ns ^{:doc    "File handling functions for webd"
      :author "Anton Andreev"}
  webd.files
  (:require [webd.parsing :as parse]
            [clojure.java.io :as io]
            [clojure.tools.logging :as log])
  (:import [java.time Instant]
           [java.io IOException FileNotFoundException File FileInputStream]))

(defmacro ^:private safe-file-operations [path username & operations]
  `(try
     ~@operations
     :success
     (catch IOException e#
       (log/error e# "IO failed during file operation for user `"
                  ~username "` in " ~path)
       :eio)
     (catch SecurityException e#
       (log/error e# "Permission exception during user file operation for user '"
                  ~username "' in " ~path)
       :eperm)
     (catch FileNotFoundException e#
       (log/error e# "File not found during file operation for user '"
                  ~username "' in " ~path)
       :enotfound)
     (catch Exception e#
       (log/error e# "Failed file operation for user '"
                  ~username "' in " ~path)
       :error)))

(defn save-user-data!
  "Stores passed data about user in user's directory if such exists.
   `user-params` must also contain data about user (:name, :title, etc.).
   `data` is a data to store in index file.
   Owerwrites previous .clj file or creates new.
   Returnes true on success, false on failure and nil on exception"
  [cfg {username :logins :as user-params} data]
  (when-let [student (parse/get-student cfg user-params)]
    (let [path (str (:projects-root cfg) "/" (:path student) "/"
                    (:index-file-name cfg) ".clj")]
      (safe-file-operations
        path username
        (let [file (io/file path)]
          (with-open [w (io/writer file)]
            (.write w
                    (prn-str (assoc data :identity-time
                                         (str (or (:identity-time student)
                                                  (Instant/now)))
                                         :files (reduce
                                                  #(assoc-in
                                                     %1 [%2 :creation-time]
                                                     (when-let [t (get-in student
                                                                          [:files %2
                                                                           :creation-time])]
                                                       (str t)))
                                                  {} (keys (:inner-structure cfg)))))))
          (.setExecutable file false))))))                  ;kostyl' for server issue with group exection perm

(defn append-user-data!
  [cfg {username :logins :as user-params} data]
  (when-let [student (parse/get-student cfg user-params)]
    (save-user-data! cfg user-params
                     (merge-with #(cond
                                    (map? %2) (merge %1 %2)
                                    :default %2)
                                 (reduce #(assoc %1 %2 (%2 student))
                                         {} (:index-file-content cfg))
                                 data))))

(defn copy-user-data!
  [cfg {username :logins :as user-params}]
  (let [students (sort-by :years (parse/query cfg {:logins username}))]
    (when-let [prev-stud (when (< 1 (count students))
                           (nth students (- (count students) 2)))]
      (save-user-data! cfg user-params
                       (reduce #(assoc %1 %2 (%2 prev-stud))
                               {} (:index-file-content-copyable cfg))))))

(defn- check-if-pdf [^File file]
  (try
    (let [header (byte-array 4)]
      (with-open [is (FileInputStream. file)]
        (.read is header 0 4))
      (and (= 0x25 (get header 0)) (= 0x50 (get header 1))
           (= 0x44 (get header 2)) (= 0x46 (get header 3))))
    (catch Exception _ false)))

(defn store-doc-file!
  "Stores file (suppose the pdf) passed in `params/:doc-file/:tempfile`
   into corresponding user's directory described by
   `:years`, `:courses` and `:groups` in `params`.
   Doc-type specified in `params/:for-doc`.
   Returnes true on success, false on failure and nil on exception"
  [cfg {username :logins :as user-params} for file]
  (when-let [student (parse/get-student cfg user-params)]
    (when file
      (let [new-path (str (:projects-root cfg) "/"
                          (:path student) "/"
                          (get-in cfg [:inner-structure for :path]) "/"
                          (get-in cfg [:inner-structure for :file-name]) "."
                          (get-in cfg [:inner-structure for :file-ext]))
            new-file (io/file new-path)]
        (if (check-if-pdf file)
          (let [result (safe-file-operations new-path username
                                             (io/make-parents new-path)
                                             (io/copy file new-file))]
            (when (= :success result)
              (when-not (get-in student [:files for :creation-time])
                (append-user-data!
                  cfg user-params
                  {:files {for {:creation-time
                                (.toString (Instant/now))}}})))
            result)
          (do (log/warn (str "Loaded by " username " file is not a PDF"))
              :enotpdf))))))

(defn delete-doc-file!
  "Deletes doc file (if exists) of user
   for specified `:years`, `:courses` and `:groups` in `params`.
   Doc specified in `:for-doc` in `params`
   Returnes true on success, false on failure and nil on exception"
  [cfg {username :logins :as user-params} for]
  (when-let [student (parse/get-student cfg user-params)]
    (when-let [doc (get-in student [:files for :path])]
      (let [path (str (:projects-root cfg) "/" doc)]
        (safe-file-operations path (:logins user-params)
                              (io/delete-file path)
                              (append-user-data!
                                cfg user-params
                                {:files {for {:creation-time nil}}}))))))

(defn init-directory-structure!
  ([cfg username usergroup year]
   (let [usergroup (str usergroup)
         initials {:years   year
                   :courses (str (get usergroup 2))
                   :groups  usergroup
                   :logins  username}
         root-path (str (:projects-root cfg) "/" (clojure.string/join "/" (map initials (:path-structure cfg))))
         lg1 (log/info root-path)
         f1 (str root-path "/" (get-in cfg [:inner-structure :int-report :path]) "/dummy")
         f2 (str root-path "/" (get-in cfg [:inner-structure :int-slides :path]) "/dummy")
         f3 (str root-path "/" (get-in cfg [:inner-structure :fin-report :path]) "/dummy")
         f4 (str root-path "/" (get-in cfg [:inner-structure :fin-slides :path]) "/dummy")
         f5 (str root-path "/" (get-in cfg [:inner-structure :fin-review :path]) "/dummy")
         f6 (str root-path "/" (get-in cfg [:inner-structure :fin-sup-review :path]) "/dummy")
         f7 (str root-path "/" (get-in cfg [:inner-structure :fin-vkr :path]) "/dummy")
         f8 (str root-path "/" (get-in cfg [:inner-structure :fin-antiplagiat :path]) "/dummy")]
     (log/info "Creating" f1 f2 f3 f4)
     (safe-file-operations root-path username
                           (io/make-parents f1)
                           (io/make-parents f2)
                           (io/make-parents f3)
                           (io/make-parents f4)
                           (io/make-parents f5)
                           (io/make-parents f6)
                           (io/make-parents f7)
                           (io/make-parents f8))
     true))
  ([cfg username usergroup]
   (init-directory-structure! cfg username usergroup (:current-year cfg))))

(defn- delete-directory-recursive
  "Recursively delete a directory."
  [^java.io.File file]
  ;; when `file` is a directory, list its entries and call this
  ;; function with each entry. can't `recur` here as it's not a tail
  ;; position, sadly. could cause a stack overflow for many entries?
  (when (.isDirectory file)
    (doseq [file-in-dir (.listFiles file)]
      (delete-directory-recursive file-in-dir)))
  ;; delete the file or directory. if it it's a file, it's easily
  ;; deletable. if it's a directory, we already have deleted all its
  ;; contents with the code above (remember?)
  (io/delete-file file))

(defn delete-user-dir!
  "Deletes doc file (if exists) of user
   for specified `:years`, `:courses` and `:groups` in `params`.
   Doc specified in `:for-doc` in `params`
   Returnes true on success, false on failure and nil on exception"
  [cfg student]
      (let [path (str (:projects-root cfg) "/" (clojure.string/join "/" (map student (:path-structure cfg))))]
        (safe-file-operations path (:logins student)
                              (delete-directory-recursive (io/file path)))))


