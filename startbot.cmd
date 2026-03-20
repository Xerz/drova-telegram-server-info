@echo off

set TELEGRAM_BOT_TOKEN=REPLACE-TO-YOUR-TELEGRAM-BOT-TOKEN
rem Optional. Proxy only for Telegram Bot API traffic.
rem set TELEGRAM_HTTP_PROXY=http://user:pass@127.0.0.1:8080

echo module ERRORS install commands:
echo No module named 'telegram' = pip install "python-telegram-bot[socks]>=21,<22"
echo No module named 'requests' = pip install requests
echo No module named 'geoip2' = pip install geoip2
echo No module named 'openpyxl' = pip install openpyxl
echo No module named 'dotenv' = pip install python-dotenv

python.exe bot.py

pause
