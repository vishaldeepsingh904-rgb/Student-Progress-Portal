STUDENT PROGRESS PORTAL - SETUP

1. Install Python 3.10 or newer.
2. Open Command Prompt in this project folder.
3. Install dependencies:
   python -m pip install -r requirements.txt
4. Run the application:
   python -m streamlit run app.py
5. Browser should open at http://localhost:8501

DEMO LOGIN
Teacher:
  username: teacher
  password: teach123

Students:
  username: student01 through student20
  password: student123

DATABASE
The SQLite database file student_portal.db is created automatically
the first time the app starts. Keep this file if you want to preserve
attendance, marks and contact details between runs.

OPTIONAL GMAIL
Email sending is disabled by default. To enable it:
- Open the .streamlit folder.
- Copy secrets.toml.example and rename the copy to secrets.toml.
- Enter your Gmail address and a NEW Google App Password.
- Set AUTO_EMAIL_ENABLED = true.
- Never share secrets.toml or upload it publicly.
- Keep the computer and app running for scheduled email checks.

NOTE
The ML risk score is a demonstration trained on synthetic data. It is
not a validated prediction of real student outcomes.
