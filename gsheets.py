import gspread
import asyncio
from google.oauth2.service_account import Credentials

# Разрешения для работы с Google Таблицами
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

import os
import json

def _append_row_sync(credentials_file, spreadsheet_url, row_data):
    """Синхронная функция добавления строки (работает под капотом)"""
    google_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    
    if google_json:
        # Для Railway: читаем из переменной окружения
        creds_dict = json.loads(google_json)
        credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # Для локального запуска: читаем из файла
        credentials = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
        
    gc = gspread.authorize(credentials)
    
    # Открываем таблицу по ссылке
    sh = gc.open_by_url(spreadsheet_url)
    
    # Берем первый лист (sheet1)
    worksheet = sh.sheet1
    
    # Добавляем строку данных
    worksheet.append_row(row_data)

async def append_row(credentials_file, spreadsheet_url, row_data):
    """
    Асинхронная обертка для отправки данных, 
    чтобы не блокировать цикл событий бота (event loop).
    """
    await asyncio.to_thread(_append_row_sync, credentials_file, spreadsheet_url, row_data)
