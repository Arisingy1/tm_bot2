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


def _get_worksheet(credentials_file, spreadsheet_url):
    """Авторизуемся и возвращаем первый лист таблицы."""
    google_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

    if google_json:
        # Для Railway: читаем из переменной окружения
        creds_dict = json.loads(google_json)
        credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # Для локального запуска: читаем из файла
        credentials = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)

    gc = gspread.authorize(credentials)
    sh = gc.open_by_url(spreadsheet_url)
    return sh.sheet1


def _append_row_sync(credentials_file, spreadsheet_url, row_data):
    """Синхронная функция добавления строки (работает под капотом)"""
    worksheet = _get_worksheet(credentials_file, spreadsheet_url)
    worksheet.append_row(row_data)


async def append_row(credentials_file, spreadsheet_url, row_data):
    """
    Асинхронная обертка для отправки данных,
    чтобы не блокировать цикл событий бота (event loop).
    """
    await asyncio.to_thread(_append_row_sync, credentials_file, spreadsheet_url, row_data)


def _get_completed_user_ids_sync(credentials_file, spreadsheet_url, user_id_col):
    """Читаем колонку с Telegram ID и возвращаем множество строковых id."""
    worksheet = _get_worksheet(credentials_file, spreadsheet_url)
    values = worksheet.col_values(user_id_col)
    return set(v.strip() for v in values if v.strip())


async def get_completed_user_ids(credentials_file, spreadsheet_url, user_id_col):
    """
    Асинхронная обертка: возвращает множество Telegram ID,
    которые уже есть в таблице (т.е. уже прошли квиз).
    Если удалить строку из таблицы — id пропадёт и человек сможет пройти заново.
    """
    return await asyncio.to_thread(
        _get_completed_user_ids_sync, credentials_file, spreadsheet_url, user_id_col
    )
