(ns ^{:doc    "Functions for student-control-documents creation."
      :author "Anton Andreev"}
webd.doc
  (:use [clj-pdf.core :only [pdf]]
        [clojure.java.io :only [writer]]
        [clojure.string :only [join]])
  (:require [clojure.tools.logging :as log])
  (:import (com.tutego.jrtf Rtf RtfPara RtfText RtfUnit RtfTextPara RtfInfo RtfDocfmt RtfRow RtfTextPara$BorderStyle)
           (java.io Writer FileInputStream)
           (java.text SimpleDateFormat)
           (java.util Date)))

(defn- make-table-row-pdf
  "Creates row (a vector) for pdf-table. 
   `tbl-struct` must be a vector with keywords of table columns. 
   `n` must be index of the student.
   `student` must be map with data about student."
  [tbl-struct n student]
  (let [stud-with-num (assoc student :number (inc n))
        stud-with-name (if-not (:name student)
                         (assoc stud-with-num :name (:logins student))
                         stud-with-num)
        with-doc-existence (reduce #(if (get-in %1 [:files %2 :path])
                                      (assoc %1 %2 "Есть")
                                      (assoc %1 %2 "Нет"))
                                   stud-with-name
                                   [:int-report :int-slides
                                    :fin-report :fin-slides])
        with-checked (assoc with-doc-existence :checked "")]
    (vec (map #(str (with-checked % "Не указано")) tbl-struct))))

(defn- make-table-pdf
  "Creates table (a vector) for clj-pdf document with info about students.
   `student` must be map with data about student.
   `tbl-struct` must be a vector with keywords of table columns. 
   `tbl-titles` must be a map with keywords and table-column titles.
   `tbl-widths` must be a map with keywords and table-column widths in percents."
  [students tbl-struct tbl-titles tbl-widths]
  ;; take table width from cfg (`tbl-widths`)
  (apply vector :table {:widths (map #(tbl-widths % 1) tbl-struct)}
         ;; header for table with styling 
         ;; taking titles from cfg (`tbl-titles`)
         (vec (map #(vector :cell {:color [100 10 200] :style :bold}
                            (tbl-titles % "")) tbl-struct))
         ;; here goes table content
         (map-indexed (partial make-table-row-pdf tbl-struct) students)))

(defn- letterhead
  "Creates letterhead that would appear at top of the first page"
  [students]
  [[:table {:widths [10 90] :border false}
    [[:image {:width 30 :height 30} (-> "cs_logo.png" clojure.java.io/resource
                                        clojure.java.io/file
                                        javax.imageio.ImageIO/read)]
     [:phrase {:encoding :unicode :style :bold :ttf-name "times.ttf"}
      (let [years (sort (set (map :years students)))
            groups (count (set (map :groups students)))
            stud-c (count students)]
        (str "Учет студенческих работ за "
             (join ", " years)
             (if (= 1 (count years)) " год. " " года. ")
             stud-c (let [rem (mod stud-c 10)
                          sec (-> stud-c (mod 100) (quot 10))]
                      (cond
                        (= sec 1) " студентов"
                        (= rem 1) " студент"
                        (#{2 3 4} rem) " студента"
                        :default " студентов"))
             " из " groups (if (= 1 groups) " группы." " групп.")))]]]])

(defn- letterhead-missing
  "Creates letterhead that would appear at top of the first page"
  [year]
  [[:table {:widths [10 90] :border false}
    [[:image {:width 30 :height 30} (-> "cs_logo.png" clojure.java.io/resource
                                        clojure.java.io/file
                                        javax.imageio.ImageIO/read)]
     [:phrase {:encoding :unicode :style :bold :ttf-name "times.ttf"}
      (str "Список студентов, не зарегистрировавших работы в "
           (str year "-" (inc (read-string (str year))))
           " уч.г. на "
           (.format (SimpleDateFormat. "dd.MM.yyyy") (new Date)))
      ]]]])

(defn- make-paragraph [& contents]
  [:paragraph {:encoding :unicode :style :bold :ttf-name "times.ttf"}
   (join contents)])

(defn- make-tables-pdf
  "Create sequence of clj-pdf tables (that are vectors)
   for students`. Groups it in some manner, one table for group.
   Table columns, their titles and widths passed in corresponding 
   arguments. Keys in them must be as in students maps."
  [students tbl-struct tbl-titles tbl-widths]
  (apply
    concat
    (for [[year y-studs] (reverse (sort-by first (group-by :years students)))]
      (cons
        (make-paragraph "Студенты " year " года")
        (apply concat
               (for [[dep d-studs] (group-by :department y-studs)]
                 (cons
                   (make-paragraph (if dep (str "Кафедра " dep)
                                           "Неизвестная кафедра"))
                   (apply concat
                          (for [[group g-studs] (sort-by first
                                                         (group-by :groups d-studs))]
                            (list (make-paragraph "Группа " group)
                                  (make-table-pdf g-studs tbl-struct
                                                  tbl-titles tbl-widths)))))))))))

(defn to-pdf
  "TODO: doc
   TODO: error handling?"
  ([students tbl-struct tbl-titles tbl-widths]
   (to-pdf students tbl-struct tbl-titles tbl-widths
           "resources/public/temp/doc.pdf"))
  ([students tbl-struct tbl-titles tbl-widths stream]
   (pdf
     (concat
       [{:font       {:encoding :unicode
                      :ttf-name "times.ttf"}
         :size       :a4
         :title      "Учет студенческих работ"
         :letterhead (letterhead students)}]
       (make-tables-pdf students tbl-struct tbl-titles tbl-widths))
     stream)))

(defn to-pdf-missing
  "TODO: doc
   TODO: error handling?"
  [students year stream]
  (pdf
    (concat
      [{:font       {:encoding :unicode
                     :ttf-name "times.ttf"}
        :size       :a4
        :title      "Учет студенческих работ"
        :letterhead (letterhead-missing year)}]
      (cons (make-paragraph "Всего: " (count students))
            (for [[group g-studs] (sort-by first
                                           (group-by :groups students))]
              (list (make-paragraph "Группа " group ", количество: " (count g-studs))
                    (make-table-pdf (sort-by :name g-studs)
                                    [:number :full-name]
                                    {:number "№"
                                     :full-name   "ФИО"}
                                    {:number 5
                                     :full-name   95})))))
    stream))

(defn text ^RtfText [^String txt] (RtfText/text txt))
(defn bold ^RtfText [^String txt] (-> txt text (RtfText/bold)))
(defn italic ^RtfText [^String txt] (-> txt text (RtfText/italic)))

(defn text-p ^RtfTextPara [& txts] (RtfPara/p (into-array txts)))
(defn centered-p ^RtfTextPara [txt] (-> txt text-p (.alignCentered)))
(defn justified-p ^RtfTextPara [txt] (-> txt text-p (.alignJustified)))
(defn linebreak ^RtfTextPara [] (text-p (text "")))

(defn row ^RtfRow [& txts] (-> (RtfPara/row (into-array txts))
                               (.topCellBorder)
                               (.leftCellBorder)
                               (.rightCellBorder)
                               (.bottomCellBorder)))

(defn row-wb ^RtfRow [& txts] (-> (RtfPara/row (into-array txts))))

(defn th [txt width] (.cellWidth (centered-p (bold txt)) width RtfUnit/CM))

(defn sec ^Rtf [^Rtf rtf paras] (.section rtf (into-array RtfPara paras)))

(defn- study-year [^String year]
  (str year "/" (inc (read-string year))))

(defn rtf-directive
  "TODO: doc
   TODO: error handling?"
  [cfg students stream]
  (with-open [wrt (writer stream)]
    (try
      (let [rtf (Rtf/rtf)
            f (first students)
            dep (:department f "ИМО")
            year (study-year (str (:years f 2017)))
            forMag? (> (read-string (:courses f "4")) 4)
            by-supervisor (sort-by first (group-by :adviser-name students))
            index-start (atom 1)]

        (-> rtf
            #_(.info (into-array RtfInfo [(RtfInfo/title "Распоряжение")]))
            (.documentFormatting (into-array RtfDocfmt [(RtfDocfmt/leftMargin 3 RtfUnit/CM)
                                                        (RtfDocfmt/rightMargin 1 RtfUnit/CM)
                                                        (RtfDocfmt/topMargin 1 RtfUnit/CM)
                                                        (RtfDocfmt/bottomMargin 1 RtfUnit/CM)
                                                        (RtfDocfmt/paper 21 29.7 RtfUnit/CM)]))
            (sec
              (concat
                [(-> (bold "Приложение 6")
                     (RtfText/italic)
                     text-p
                     (.alignRight))
                 (linebreak)
                 (centered-p (bold "Министерство образования и науки Российской Федерации"))
                 (centered-p (bold "федеральное государственное бюджетное образовательное учреждение"))
                 (centered-p (bold "высшего образования"))
                 (centered-p (bold "«ПЕТРОЗАВОДСКИЙ ГОСУДАРСТВЕННЫЙ УНИВЕРСИТЕТ»"))
                 (centered-p (bold "(ПетрГУ)"))
                 (linebreak)
                 (centered-p (text "Институт математики и информационных технологий"))
                 (linebreak)
                 (centered-p (bold "Р А С П О Р Я Ж Е Н И Е"))
                 (linebreak)
                 (linebreak)
                 (text-p (text "«_____» ______________ 201__ г.\t\t\t\t\t\t\t      № _______"))
                 (linebreak)
                 (text-p (italic "О назначении руководителей выпускных квалификационных работ (ВКР)"))
                 (text-p (italic "и закреплении тем ВКР за обучающимися"))
                 (linebreak)
                 (justified-p (str "Назначить руководителями выпускных квалификационных работ по кафедре "
                                   (get-in cfg [:departments-full dep] "???")
                                   " на "
                                   year
                                   " учебный год по направлению подготовки "
                                   (if forMag? "магистратуры" "бакалавриата")
                                   " очной формы обучения:"))
                 (linebreak)

                 ;table header
                 (row (th "№ п/п" 1) (th "ФИО студента" 6) (th "Группа" 3) (th "Тема ВКР" 7))]

                ;table body starts
                (mapcat (fn [[adviser stds]]
                          (let [sorted-stds (sort-by :name stds)
                                adv-pos (:adviser-position (first stds))
                                adv-rank (:adviser-rank (first stds))
                                index-buf @index-start]
                            (swap! index-start #(+ % (count sorted-stds)))
                            (concat [(row-wb (text-p (text ""))
                                             (centered-p (bold (str adviser (when adv-rank (str ", " adv-rank)) (when adv-pos (str ", " adv-pos)))))
                                             (text-p (text "")) (text-p (text "")))]
                                    (map-indexed #(row (str (+ index-buf %1)) (:full-name %2) (:groups %2) (:title %2)) sorted-stds))))
                        by-supervisor)
                ;table ends

                [(linebreak)
                 (linebreak)
                 (text-p (text "Директор института МиИТ\t\t             ___________________________ Н.Ю. Светова"))
                 #_(text-p (text "\t\t\t\t\t\t\t\t       (подпись)"))
                 (linebreak)
                 (linebreak)
                 (text-p (text (str "Заведующий кафедрой "
                                    dep
                                    "\t   ___________________________ "
                                    (get-in cfg [:departments-directors dep] "???"))))]
                ))
            (.out wrt)))
      (catch Exception e (log/error "Failed generating directive " e)))))
