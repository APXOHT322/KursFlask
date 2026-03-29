from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from app.models import db, User, ElectiveCourse, StudentElectiveCourse, Settings, Direction
from app.manage_courses import manage_courses_bp
from app.student_courses import student_courses_bp
from app.reports import reports_bp
from app.ldap_auth import ldap_authenticate, ldap_get_user_info
from sqlalchemy import text
from functools import wraps
from datetime import datetime
import logging

log = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)

    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:OoRa2Oob@localhost/Kurs'
    app.config['SECRET_KEY'] = 'your_secret_key'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    bcrypt = Bcrypt(app)
    jwt = JWTManager(app)

    try:
        app.register_blueprint(manage_courses_bp, url_prefix='/')
    except Exception:
        pass
    try:
        app.register_blueprint(student_courses_bp, url_prefix='/')
    except Exception:
        pass
    try:
        app.register_blueprint(reports_bp, url_prefix='/')
    except Exception:
        pass

    AVAILABLE_ROLES = ['Студент', 'Преподаватель', 'Специалист дирекции']

    # ── Декоратор проверки ролей ──────────────────────────────────────────────
    def roles_required(*role_names):
        def decorator(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                user_id = session.get('user_id')
                if not user_id:
                    return redirect(url_for('login'))
                user = User.query.get(user_id)
                if not user:
                    return redirect(url_for('login'))
                if not any(user.has_role(r) for r in role_names):
                    abort(403)
                return f(*args, **kwargs)
            return wrapper
        return decorator

    # ── Маппинг суффикса группы → код направления ────────────────────────────
    #
    # Формат группы бакалавров: 22XYY
    #   22   — год поступления (2022)
    #   X    — курс (3-я цифра)
    #   YY   — суффикс направления (последние 2 цифры)
    #
    # Формат группы магистров: 5NN (3 символа, начинается с 5)
    #
    _BACHELOR_SUFFIX_TO_CODE = {
        '01': '01.03.01',   # Математика
        '03': '01.03.02',   # Прикладная математика и информатика
        '04': '01.03.02',   # Прикладная математика и информатика
        '05': '09.03.02',   # Информационные системы и технологии
        '06': '09.03.02',   # Информационные системы и технологии
        '07': '09.03.04',   # Программная инженерия
    }

    _MASTER_GROUP_TO_CODE = {
        '501': '01.04.01',  # Математика магистры
        '503': '01.04.02',  # Прикладная математика и информатика магистры
        '505': '09.04.02',  # Информационные системы и технологии магистры
    }

    def _resolve_direction(group_number: str, admission_year: int):
        """
        По номеру группы и году поступления возвращает direction_id или None.

        Логика:
          - Если группа начинается с '5' и длина 3 — магистратура (_MASTER_GROUP_TO_CODE)
          - Иначе — бакалавриат: берём последние 2 символа как суффикс направления
        """
        if not group_number:
            return None

        # Магистратура: группы вида 501, 503, 505
        if len(group_number) == 3 and group_number.startswith('5'):
            direction_code = _MASTER_GROUP_TO_CODE.get(group_number)
        else:
            # Бакалавриат: последние 2 цифры — суффикс направления
            suffix = group_number[-2:]
            direction_code = _BACHELOR_SUFFIX_TO_CODE.get(suffix)

        if not direction_code:
            log.warning("_resolve_direction: неизвестная группа '%s'", group_number)
            return None

        # Ищем направление с нужным кодом и годом учебного плана
        direction = Direction.query.filter_by(
            code=direction_code,
            year=admission_year
        ).first()

        if not direction:
            # Запасной вариант: берём любое направление с этим кодом
            direction = Direction.query.filter_by(code=direction_code).first()
            if direction:
                log.warning(
                    "_resolve_direction: не нашли direction code=%s year=%s, "
                    "используем year=%s (id=%s)",
                    direction_code, admission_year, direction.year, direction.id
                )

        return direction.id if direction else None

    # ── Вспомогательная функция: создать/обновить пользователя из LDAP ────────
    def _provision_user(ldap_info: dict) -> User:
        uid  = ldap_info["uid"]
        user = User.query.filter_by(login=uid).first()

        if user is None:
            group_number   = ldap_info.get("group")
            admission_year = None
            direction_id   = None

            if ldap_info["is_student"] and group_number:
                try:
                    year_short     = int(group_number[:2])
                    admission_year = 2000 + year_short
                except (ValueError, IndexError):
                    admission_year = datetime.now().year

                direction_id = _resolve_direction(group_number, admission_year)

            user = User(
                fio            = ldap_info["fio"],
                login          = uid,
                password       = bcrypt.generate_password_hash("__ldap__").decode("utf-8"),
                role           = ldap_info["role"],
                group_number   = group_number,
                direction_id   = direction_id,
                admission_year = admission_year,
            )
            db.session.add(user)
            db.session.commit()
        else:
            user.fio = ldap_info["fio"]
            db.session.commit()

        return user

    # ── Маршруты ──────────────────────────────────────────────────────────────

    @app.route('/')
    def index():
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))
        user = User.query.get(user_id)
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))
        return redirect(url_for('dashboard'))

    @app.route('/dashboard')
    def dashboard():
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))
        user = User.query.get(user_id)
        if not user:
            return redirect(url_for('login'))
        return render_template('dashboard.html', user=user)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            uid      = request.form.get('login', '').strip()
            password = request.form.get('password', '')

            if not ldap_authenticate(uid, password):
                return render_template('login.html',
                                       error="Неверный логин или пароль")

            ldap_info = ldap_get_user_info(uid)
            if not ldap_info:
                return render_template('login.html',
                                       error="Не удалось получить данные пользователя из LDAP")

            user = _provision_user(ldap_info)
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.pop('user_id', None)
        return redirect(url_for('login'))

    # ── SSO: вход по одноразовому токену от Clojure ───────────────────────────

    @app.route('/sso')
    def sso_login():
        token = request.args.get('token', '')
        if not token:
            return redirect(url_for('login'))

        row = db.session.execute(
            text("SELECT uid FROM sso_tokens WHERE token=:t AND expires_at > NOW()"),
            {'t': token}
        ).fetchone()

        if not row:
            return render_template('login.html',
                                   error='Ссылка для входа недействительна или устарела')

        db.session.execute(text("DELETE FROM sso_tokens WHERE token=:t"), {'t': token})
        db.session.commit()

        uid = row[0]
        ldap_info = ldap_get_user_info(uid)
        if not ldap_info:
            return render_template('login.html',
                                   error='Не удалось получить данные пользователя')

        user = _provision_user(ldap_info)
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))


    # ── SSO: переход из Flask обратно в Clojure ───────────────────────────────

    @app.route('/goto/kurs')
    def goto_kurs():
        """
        Генерирует SSO-токен и перенаправляет пользователя в Clojure-приложение.
        Используется кнопкой "← Система Курс" на dashboard и других страницах.
        """
        user_id = session.get('user_id')
        if not user_id:
            return redirect('http://localhost:3000/')

        user = User.query.get(user_id)
        if not user:
            return redirect('http://localhost:3000/')

        import secrets
        from datetime import timedelta

        token = secrets.token_hex(32)
        expires_at = datetime.now() + timedelta(minutes=2)

        db.session.execute(
            text("INSERT INTO sso_tokens (token, uid, expires_at) VALUES (:t, :u, :e)"),
            {'t': token, 'u': user.login, 'e': expires_at}
        )
        db.session.commit()

        return redirect(f'http://localhost:3000/sso?token={token}')

    # ── Управление студентами (специалист дирекции) ───────────────────────────

    @app.route('/manage_students_courses', methods=['GET', 'POST'])
    @roles_required('Специалист дирекции')
    def manage_students_courses():
        if request.method == 'POST':
            student_id = request.form.get('student')
            course_id  = request.form.get('course')
            action     = request.form.get('action')

            if student_id and course_id:
                if action == 'assign':
                    db.session.execute(
                        text("INSERT INTO student_elective_courses (user_id, elective_course_id) VALUES (:s, :c)"),
                        {'s': student_id, 'c': course_id}
                    )
                elif action == 'remove':
                    db.session.execute(
                        text("DELETE FROM student_elective_courses WHERE user_id=:s AND elective_course_id=:c"),
                        {'s': student_id, 'c': course_id}
                    )
                db.session.commit()

        students = db.session.execute(
            text("SELECT id, fio FROM users WHERE role LIKE '%Студент%' ORDER BY fio")
        ).fetchall()
        courses  = db.session.execute(
            text("SELECT id, name FROM elective_course")
        ).fetchall()
        assigned = db.session.execute(text("""
            SELECT users.fio, elective_course.name AS course_name
            FROM student_elective_courses
            JOIN users           ON student_elective_courses.user_id           = users.id
            JOIN elective_course ON student_elective_courses.elective_course_id = elective_course.id
            ORDER BY users.fio
        """)).fetchall()

        return render_template('manage_students_courses.html',
                               students=students, courses=courses, assigned=assigned)

    @app.route('/director_dashboard')
    @roles_required('Специалист дирекции')
    def director_dashboard():
        user = User.query.get(session.get('user_id'))
        return render_template('director_dashboard.html', user=user)

    # ── Управление ролями пользователей ──────────────────────────────────────

    @app.route('/admin/users')
    @roles_required('Специалист дирекции')
    def admin_users():
        users = User.query.order_by(User.fio).all()
        return render_template('admin_users.html', users=users, available_roles=AVAILABLE_ROLES)

    @app.route('/admin/users/<int:uid>/set_role', methods=['POST'])
    @roles_required('Специалист дирекции')
    def admin_set_role(uid):
        user           = User.query.get_or_404(uid)
        selected_roles = request.form.getlist('roles')
        user.set_roles_from_list(selected_roles)
        db.session.commit()
        flash(f'Роли для {user.fio} обновлены', 'success')
        return redirect(url_for('admin_users'))

    # ── Обработчики ошибок ────────────────────────────────────────────────────

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('403.html'), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
