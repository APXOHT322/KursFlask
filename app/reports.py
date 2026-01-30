from flask import Blueprint, render_template, send_file, request
from app.models import User, ElectiveCourse, StudentElectiveCourse
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab import rl_config

reports_bp = Blueprint('reports_bp', __name__)

@reports_bp.route('/reports', methods=['GET', 'POST'])
def generate_reports():
    if request.method == 'POST':
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter

        # Регистрация шрифта, поддерживающего кириллицу
        rl_config.warnOnMissingFont = 0
        pdfmetrics.registerFont(TTFont('FreeTTF', r'D:\Downloads\Telegram Desktop\KursFlask-main\KursFlask-main\fonts\DejaVuSans.ttf'))
        c.setFont("FreeTTF", 12)

        c.drawString(100, height - 40, "Отчет по дисциплинам и студентам")

        elective_courses = ElectiveCourse.query.all()

        y_position = height - 60
        for course in elective_courses:
            student_courses = StudentElectiveCourse.query.filter_by(elective_course_id=course.id).all()
            if student_courses:
                if y_position < 80:
                    c.showPage()
                    c.setFont("FreeTTF", 12)
                    y_position = height - 60

                c.drawString(100, y_position, f"Дисциплина: {course.name}")
                y_position -= 20

                for student_course in student_courses:
                    student = student_course.user
                    c.drawString(100, y_position, f"ФИО: {student.fio}, Группа: {student.group_number}")
                    y_position -= 20

                y_position -= 20

        c.save()
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name="report.pdf", mimetype='application/pdf')

    return render_template('reports.html')
