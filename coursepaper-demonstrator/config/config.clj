{
 ;; a projects folder root that would be prepended to html-links to files
 :projects-server             "https://kappa.cs.karelia.ru/p"
 ;; a local projects folder root
 :projects-root               "/srv/www/projects"
 ;; structure and roles of folders in projects root
 :path-structure              [:years :courses :groups :logins]
 ;; server for authentication with use of LDAP
 :ldap-server                 "ldap.cs.prv"
 ;; to make LDAP-bind it required to make LDAP-search before it
 ;; to find user's DN
 :ldap-search-string          "ou=people,dc=cs,dc=karelia,dc=ru"
 ;; a stuff that would be included or excluded before handling
 ;; must contain regexes
 ;; Example: if :years #"2013" passed to :include then only this year
 ;; would be handled
 :prefilter                   {:include {:years #"201[2-9]|202[0-9]" :groups #"22[ZzА-Яа-я\-0-9]{3,6}"}
                               :exclude {} #_{:groups #"(2210[0-9])"}}
 ;; current study year. e.g. for season 2021/2022 the value must be 2021
 :current-year                2024
 ;; how much years in the past should be editable to the users
 :editable-previous-years     2
 ;; optimization strategy for parsing the data (when the file system is read)
 ;; if `:prefiltered` then on every query will be parsed only that directories
 ;; that are included in query-map
 ;; if `:cached` then student data cache will be maintained and updated only
 ;; when some files are modified, deleted or created
 ;; if `:none` or absent then whole projects directory will be
 ;; parsed on every query
 ;; if `:last-year-only` then on each query the last year will be read again from the file system,
 ;; but all previous years will be taken from cache
 :query-optimization          :last-year-only               ;  :prefiltered                  ; :cached ;  :none
 ;; inner structure of bottom-layer folder of student
 ;; see one of the users files to make it clear
 ;; `:last-date` is a deadline configured for each study year
 :inner-structure             {:int-report      {:path      "interim/report"
                                                 :file-name "report"
                                                 :file-ext  "pdf"
                                                 :last-date {"2016"   {"2" [0 12 30]
                                                                       "3" [0 12 30]
                                                                       "4" [0 12 30]
                                                                       "5" [0 12 30]
                                                                       "6" [0 12 30]}
                                                             :default [0 12 30]}}
                               :int-slides      {:path      "interim/presentation"
                                                 :file-name "slides"
                                                 :file-ext  "pdf"
                                                 :last-date {"2016"   {"2" [0 12 30]
                                                                       "3" [0 12 30]
                                                                       "4" [0 12 30]
                                                                       "5" [0 12 30]
                                                                       "6" [0 12 30]}
                                                             :default [0 12 30]}}
                               :fin-report      {:path      "final/report"
                                                 :file-name "report"
                                                 :file-ext  "pdf"
                                                 :last-date {"2016"   {"2" [1 5 31]
                                                                       "3" [1 5 17]
                                                                       "4" [1 6 9]
                                                                       "5" [1 6 7]
                                                                       "6" [1 6 14]}
                                                             :default [1 6 1]}}
                               :fin-slides      {:path      "final/presentation"
                                                 :file-name "slides"
                                                 :file-ext  "pdf"
                                                 :last-date {"2016"   {"2" [1 5 31]
                                                                       "3" [1 5 17]
                                                                       "4" [1 6 9]
                                                                       "5" [1 6 7]
                                                                       "6" [1 6 14]}
                                                             :default [1 6 1]}}
                               :fin-review      {:path      "final/review"
                                                 :file-name "review"
                                                 :file-ext  "pdf"
                                                 :last-date {:default [1 5 31]}}
                               :fin-sup-review  {:path      "final/supreview"
                                                 :file-name "supreview"
                                                 :file-ext  "pdf"
                                                 :last-date {:default [1 5 31]}}
                               :fin-preport     {:path      "final/preport"
                                                 :file-name "preport"
                                                 :file-ext  "pdf"
                                                 :last-date {:default [1 5 31]}}
                               :fin-antiplagiat {:path      "final/antiplagiat"
                                                 :file-name "antiplagiat"
                                                 :file-ext  "pdf"
                                                 :last-date {:default [1 5 31]}}}

 ;; which files should be available for upload for which groups. `:groups` is a regexp
 :file-set                    [{:groups #"224[0-9]*" :files [:int-report :int-slides :fin-preport :fin-report :fin-slides
															 :fin-antiplagiat :fin-sup-review]}
                               {:groups #"22502" :files [:int-report :int-slides :fin-preport :fin-report :fin-slides
														 :fin-antiplagiat :fin-sup-review]}
							   {:groups #"225-ZИС" :files [:int-report :int-slides :fin-preport :fin-report :fin-slides
														 :fin-antiplagiat :fin-sup-review]}
                               {:groups #"226[0-9]*" :files [:int-report :int-slides :fin-preport :fin-report :fin-slides
															 :fin-antiplagiat :fin-sup-review :fin-review]}]
 :file-set-default            [:int-report :int-slides :fin-report :fin-slides]
 ;; which files should be available for upload only for admins
 :files-only-for-admin        #{}

 ;; allowed file names and extensions
 :index-file-name             "index"
 :index-file-exts             ["xml" "clj"]
 :index-file-content          [:title :name :department :adviser-name :adviser-status
                               :adviser-rank :adviser-position :files :identity-time]
 ;; which fields are copied if student is registering by clicking 'copy from previous year'
 :index-file-content-copyable [:title :department :adviser-name :adviser-status
                               :adviser-rank :adviser-position]

 ;; Allowed values for users departments, other will be ignored
 :departments                 #{"ИМО" "ТВиАД" "МА" "ГиТ" "ПМиК" "ТМОМИ"}
 :departments-full            {"ИМО"   "информатики и математического обеспечения"
                               "ТВиАД" "теории вероятностей и анализа данных"
                               "МА"    "математического анализа"
                               "ГиТ"   "геометрии и топологии"
                               "ПМиК"  "прикладной математики и кибернетики"
                               "ТМОМИ" "теории и методики обучения математике и информационно-коммуникационным технологиям в образовании"}
 :departments-directors       {"ИМО"   "Ю.А. Богоявленский"
                               "ТВиАД" "А.А. Рогов"
                               "МА"    "В.В. Старков"
                               "ГиТ"   "А.В. Иванов"
                               "ПМиК"  "А.В. Воронин"
                               "ТМОМИ" "Е.В. Филимонова"}
 :default-department          nil                           ; "ИМО"

 ;; ordered structure of pdf-table columns
 :pdf-table-struct            [:number :title :name :adviser-name-formatted
                               :int-report :int-slides :fin-report :fin-slides
                               :checked]
 ;; titles for pdf-table columns
 :pdf-table-titles            {:number                 "№"
                               :title                  "Название работы"
                               :name                   "ФИО студента"
                               :adviser-name-formatted "ФИО руководителя"
                               :int-report             "Пр. отчет"
                               :int-slides             "Пр. ЭП"
                               :fin-report             "отчет"
                               :fin-slides             "ЭП"
                               :checked                "Проверено. Подпись руководителя"}
 ;; widths for pdf-table columns
 :pdf-table-widths            {:number                 3
                               :title                  35
                               :name                   13
                               :adviser-name-formatted 13
                               :int-report             6
                               :int-slides             6
                               :fin-report             6
                               :fin-slides             5
                               :checked                11}
 }
