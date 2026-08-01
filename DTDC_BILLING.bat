@echo off

echo Starting DTDC_BILLING Django Server...
echo.

cd %USERPROFILE%\Desktop\DTDC_BILLING

call venv\Scripts\activate

python manage.py runserver

pause