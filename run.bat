@echo off
chcp 65001 > nul
title 한국 주식 대시보드
echo.
echo  ====================================
echo   한국 주식 대시보드 시작
echo  ====================================
echo.
cd /d "%~dp0"

echo  [1/2] 패키지 설치 확인 중...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo.
    echo  오류: pip 설치 실패. Python이 설치되어 있는지 확인하세요.
    pause
    exit /b
)

echo  [2/2] 서버 시작 중...
echo.
echo  브라우저에서 아래 주소로 접속하세요:
echo  http://localhost:5000
echo.
echo  종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.
echo.
python app.py

pause
