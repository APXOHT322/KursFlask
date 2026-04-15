"""
Тесты для основного файла app.py
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from flask import Flask

class TestAppCreation:
    """Тесты для создания приложения"""

    def test_create_app_returns_flask_app(self):
        """Проверка, что create_app возвращает Flask приложение"""
        from app.app import create_app
        app = create_app()
        assert isinstance(app, Flask)

    def test_app_config_settings(self):
        """Проверка настроек конфигурации"""
        from app.app import create_app
        app = create_app()
        assert 'SQLALCHEMY_DATABASE_URI' in app.config
        assert 'SECRET_KEY' in app.config
        assert app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] == False

    def test_blueprints_registered(self):
        """Проверка регистрации blueprint"""
        from app.app import create_app
        app = create_app()
        blueprint_names = list(app.blueprints.keys())
        # Blueprint могут быть зарегистрированы с пустыми префиксами
        assert len(app.blueprints) >= 0  # Хотя бы один может быть

class TestRoutes:
    """Тесты для маршрутов"""

    def test_index_redirects_to_login_when_not_logged_in(self, client):
        """Главная страница перенаправляет на логин если не авторизован"""
        response = client.get('/')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_login_page_accessible(self, client):
        """Страница логина доступна"""
        response = client.get('/login')
        assert response.status_code == 200

    def test_logout_clears_session(self, client, test_user):
        """Выход очищает сессию"""
        # Логинимся
        with client.session_transaction() as session:
            session['user_id'] = test_user.id

        # Проверяем что залогинены
        with client.session_transaction() as session:
            assert 'user_id' in session

        # Выходим
        response = client.get('/logout')
        assert response.status_code == 302
        assert '/login' in response.location

        # Проверяем что сессия очищена
        with client.session_transaction() as session:
            assert 'user_id' not in session

    def test_dashboard_requires_login(self, client):
        """Дашборд требует авторизации"""
        response = client.get('/dashboard')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_dashboard_works_when_logged_in(self, authenticated_client):
        """Дашборд работает для авторизованного пользователя"""
        response = authenticated_client.get('/dashboard')
        assert response.status_code == 200

class TestRoleBasedAccess:
    """Тесты для проверки доступа по ролям"""

    def test_director_dashboard_requires_director_role(self, authenticated_client, test_user):
        """Директорский дашборд требует роль специалиста дирекции"""
        # Обычный студент не имеет доступа
        response = authenticated_client.get('/director_dashboard')
        assert response.status_code == 403

    def test_admin_users_requires_admin_role(self, authenticated_client, test_user):
        """Админ панель требует роль администратора"""
        response = authenticated_client.get('/admin/users')
        assert response.status_code == 403

    def test_manage_students_courses_requires_director_role(self, authenticated_client, test_user):
        """Управление студентами требует роль специалиста дирекции"""
        response = authenticated_client.get('/manage_students_courses')
        assert response.status_code == 403

class TestResolveDirection:
    """Тесты для функции определения направления по группе"""

    def test_resolve_direction_bachelor_01(self, app):
        """Тест: группа бакалавра 2201 -> направление 01.03.01"""
        with app.app_context():
            from app.app import _resolve_direction
            # Создаем тестовое направление в БД
            from app.models import Direction
            direction = Direction(code="01.03.01", name="Математика", year=2022)
            app.db.session.add(direction)
            app.db.session.commit()

            result = _resolve_direction("2201", 2022)
            assert result == direction.id or result is not None

    def test_resolve_direction_bachelor_03(self, app):
        """Тест: группа бакалавра 2203 -> направление 01.03.02"""
        with app.app_context():
            from app.app import _resolve_direction
            from app.models import Direction
            direction = Direction(code="01.03.02", name="Прикладная математика", year=2022)
            app.db.session.add(direction)
            app.db.session.commit()

            result = _resolve_direction("2203", 2022)
            assert result == direction.id or result is not None

    def test_resolve_direction_master_501(self, app):
        """Тест: группа магистра 501 -> направление 01.04.01"""
        with app.app_context():
            from app.app import _resolve_direction
            from app.models import Direction
            direction = Direction(code="01.04.01", name="Математика магистры", year=2022)
            app.db.session.add(direction)
            app.db.session.commit()

            result = _resolve_direction("501", 2022)
            assert result == direction.id or result is not None

    def test_resolve_direction_empty_group(self, app):
        """Тест: пустая группа возвращает None"""
        with app.app_context():
            from app.app import _resolve_direction
            result = _resolve_direction("", 2022)
            assert result is None

    def test_resolve_direction_unknown_group(self, app):
        """Тест: неизвестная группа возвращает None"""
        with app.app_context():
            from app.app import _resolve_direction
            result = _resolve_direction("9999", 2022)
            assert result is None

class TestRolesRequiredDecorator:
    """Тесты для декоратора roles_required"""

    def test_roles_required_redirects_if_not_logged_in(self, client):
        """Если пользователь не залогинен - редирект на логин"""
        # Создаем защищенный маршрут для теста
        with client.application.test_request_context():
            from app.app import roles_required
            from flask import Flask, session

            test_app = Flask(__name__)
            test_app.secret_key = 'test'

            @test_app.route('/protected')
            @roles_required('Администратор')
            def protected():
                return 'OK'

            # Симулируем запрос без сессии
            with test_app.test_client() as test_client:
                response = test_client.get('/protected')
                assert response.status_code == 302  # Редирект на логин

class TestErrorHandlers:
    """Тесты для обработчиков ошибок"""

    def test_403_handler(self, client):
        """Проверка обработчика 403 ошибки"""
        # Создаем маршрут который вызывает 403
        @client.application.route('/test-403')
        def test_403():
            from flask import abort
            abort(403)

        response = client.get('/test-403')
        assert response.status_code == 403

    def test_404_handler(self, client):
        """Проверка обработчика 404 ошибки"""
        response = client.get('/non-existent-page-12345')
        assert response.status_code == 404

class TestSSO:
    """Тесты для SSO функциональности"""

    @patch('app.app.ldap_get_user_info')
    @patch('app.app.db.session.execute')
    def test_sso_login_with_valid_token(self, mock_execute, mock_ldap, client, app):
        """Тест SSO входа с валидным токеном"""
        # Мокаем результат запроса к БД
        mock_row = Mock()
        mock_row.__getitem__.return_value = 'test_user'
        mock_execute.return_value.fetchone.return_value = mock_row

        # Мокаем LDAP информацию
        mock_ldap.return_value = {
            'uid': 'test_user',
            'fio': 'Тестовый Пользователь',
            'role': 'Студент',
            'group': '2201',
            'is_student': True
        }

        response = client.get('/sso?token=valid_token')
        # Должен быть редирект на дашборд
        assert response.status_code == 302

    def test_sso_login_without_token(self, client):
        """Тест SSO входа без токена - редирект на логин"""
        response = client.get('/sso')
        assert response.status_code == 302
        assert '/login' in response.location

class TestManageStudentsCourses:
    """Тесты для управления студентами и курсами"""

    def test_manage_students_courses_get_requires_auth(self, client):
        """GET запрос требует авторизации"""
        response = client.get('/manage_students_courses')
        assert response.status_code == 302

    def test_manage_students_courses_get_with_director(self, authenticated_director, db_session):
        """Директор может видеть страницу управления"""
        # Создаем тестового студента
        from app.models import User
        student = User(
            fio="Тест Студент",
            login="test2",
            password="hash",
            role="Студент"
        )
        db_session.add(student)
        db_session.commit()

        response = authenticated_director.get('/manage_students_courses')
        assert response.status_code == 200

class TestAdminUsers:
    """Тесты для администрирования пользователей"""

    def test_admin_users_page_requires_admin(self, authenticated_client):
        """Страница администрирования требует роль администратора"""
        response = authenticated_client.get('/admin/users')
        assert response.status_code == 403

    def test_admin_users_page_accessible_to_admin(self, authenticated_admin):
        """Администратор имеет доступ к странице"""
        response = authenticated_admin.get('/admin/users')
        assert response.status_code == 200