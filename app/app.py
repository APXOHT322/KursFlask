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

    # ── Вспомогательная функция: создать/обновить пользователя из LDAP ────────
    def _provision_user(ldap_info: dict) -> User:
        """
        JIT-provisioning: при первом входе создаёт пользователя в БД,
        при повторных — обновляет ФИО из LDAP.

        Пароль не хранится (поле заполняется заглушкой — аутентификация
        всегда идёт через LDAP).
        """
        uid  = ldap_info["uid"]
        user = User.query.filter_by(login=uid).first()

        if user is None:
            # ── Первый вход: создаём запись ───────────────────────────────────
            # Для студентов пытаемся подобрать direction по группе
            direction_id   = None
            group_number   = ldap_info.get("group")
            admission_year = None

            if ldap_info["is_student"] and group_number:
                try:
                    # Первые две цифры группы — год поступления (напр. "2241" → 2024)
                    year_short     = int(group_number[:2])
                    admission_year = 2000 + year_short
                except (ValueError, IndexError):
                    admission_year = datetime.now().year

            user = User(
                fio           = ldap_info["fio"],
                login         = uid,
                # Пустой хэш — вход через LDAP не требует пароля в БД
                password      = bcrypt.generate_password_hash("__ldap__").decode("utf-8"),
                role          = ldap_info["role"],
                group_number  = group_number,
                direction_id  = direction_id,
                admission_year= admission_year,
            )
            db.session.add(user)
            db.session.commit()
        else:
            # ── Повторный вход: обновляем ФИО (могло измениться в LDAP) ───────
            # Роль НЕ обновляем автоматически — администратор мог её изменить в БД
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

            # ── Шаг 1: проверяем пароль через LDAP ────────────────────────────
            if not ldap_authenticate(uid, password):
                return render_template('login.html',
                                       error="Неверный логин или пароль")

            # ── Шаг 2: получаем атрибуты из LDAP ──────────────────────────────
            ldap_info = ldap_get_user_info(uid)
            if not ldap_info:
                return render_template('login.html',
                                       error="Не удалось получить данные пользователя из LDAP")

            # ── Шаг 3: JIT-provisioning ────────────────────────────────────────
            user = _provision_user(ldap_info)

            session['user_id'] = user.id
            return redirect(url_for('dashboard'))

        return render_template('login.html')

    # complete_student_profile убран — направление будет назначаться
    # автоматически по группе в отдельном модуле

    @app.route('/logout')
    def logout():
        session.pop('user_id', None)
        return redirect(url_for('login'))

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
            JOIN users          ON student_elective_courses.user_id          = users.id
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

    # ── Управление ролями пользователей (только для администратора) ───────────

    @app.route('/admin/users')
    @roles_required('Специалист дирекции')
    def admin_users():
        """
        Страница для ручного управления ролями пользователей.
        Роль "Специалист дирекции" можно назначить только здесь.
        """
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
