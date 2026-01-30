(defproject webd "0.2.9-SNAPSHOT"
  :description "A web application for view and control for student coursepapers."
  :url "http://kurs.cs.petrsu.ru/"
  :license {:name "Eclipse Public License"
            :url  "http://www.eclipse.org/legal/epl-v10.html"}
  :dependencies [[org.clojure/clojure "1.11.1"]
                 [org.clojure/data.xml "0.0.8"]
                 [org.clojure/tools.logging "1.2.4"]
                 [ring "1.9.5"]
                 [hiccup "1.0.5"]
                 [selmer "1.12.50"]
                 [compojure "1.7.0"]
                 [clj-pdf "2.6.1"]
                 [com.tutego/jrtf "0.7"]
                 [org.clojars.pntblnk/clj-ldap "0.0.17"]
                 [clojure-watch "0.1.14"]
                 [joda-time/joda-time "2.10.10"]
                 [log4j/log4j "1.2.17" :exclusions [javax.mail/mail
                                                    javax.jms/jms
                                                    com.sun.jmdk/jmxtools
                                                    com.sun.jmx/jmxri]]]
  :resource-paths ["resources" "config"]
  :plugins [[lein-ring "0.12.6"]
            [lein-asset-minifier "0.4.6" :exclusions [org.clojure/clojure]]]
  :ring {:handler webd.core/app
         :destroy webd.core/destroy}
  :aot :all
  :omit-source true
  ;; to make resources served by tomcat
  :war-resources-path "resources/public"
  ;; minification
  :minify-assets [[:css {:source "resources/webd.css" :target "resources/public/webd.min.css"}]
                  [:js {:source "resources/webd.js" :target "resources/public/webd.min.js"}]]
  ;; at first it will minify css and js files,
  ;; then compile .war file,
  ;; then pace it to server
  :aliases {"make-webd" ["do"
                         ["minify-assets"]
                         ["ring" "uberwar" "webd.war"]]})
