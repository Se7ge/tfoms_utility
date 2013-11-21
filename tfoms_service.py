# -*- coding: utf-8 -*-
from functools import wraps
import json
from datetime import datetime
import logging

import requests


class AnswerCodes(object):
    _codes = {
        0: u'Ошибка при работе с сервисом',
        1: u'По переданным данным пациент не найден в БД ТФОМС',
        2: u'Пациент найден в БД ТФОМС',
        3: u'Полис найден, несовпадение ФИО, даты рождения'
    }

    def __init__(self, code):
        if code not in self._codes:
            code = 0
        self.code = code
        self.message = self._codes[code]


class TFOMSClientException(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return u"<%s [%s] \"%s\">" % (self.__class__.__name__, self.code, self.message)


def ensure_can_connect(func):
    """Декоратор для методов TFOMSClient'а, выполняющий (при необходимости) проверки перед запросом"""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self.perform_checks()
        return func(self, *args, **kwargs)

    return wrapper


class TFOMSClient(object):
    def __init__(self, host, port, login, password, checkTimeout=0.5):
        self.service_url = 'http://{host}:{port}'.format(host=host, port=port)
        self.__timeout = checkTimeout
        self.__is_available = False
        self.__login = login
        self.__password = password
        self.cookies = None
        self.__is_logged_in = False
        self.__is_available = False

    def perform_checks(self):
        """Вспомогательная функция проверки всякой всячины прежде, чем мы сможем сделать запрос"""
        if not self.is_available:
            try:
                requests.get(self.service_url, timeout=self.__timeout)
            except requests.exceptions.Timeout, e:
                self.__is_available = False
                self.__is_logged_in = False
                raise TFOMSClientException(0, u"Служба получения данных из ТФОМС временно недоступна")
            except Exception, e:
                self.__is_available = False
                self.__is_logged_in = False
                raise TFOMSClientException(0, e.message)
            else:
                self.__is_available = True

        if not self.is_logged_in:
            try:
                r = requests.post(
                    '{0}/login'.format(self.service_url),
                    data=json.dumps({
                        'login': self.__login,
                        'password': self.__password,
                    }))
                if r.status_code == requests.codes.ok:
                    if r.cookies['session']:
                        logging.debug(r.cookies['session'])
                        self.cookies = dict(session=r.cookies['session'])
                elif r.status_code == requests.codes.unauthorized:
                    raise TFOMSClientException(requests.codes.unauthorized, u'Неверное имя пользователя или пароль')
                else:
                    raise TFOMSClientException(r.status_code, u'Ошибка HTTP')
            except Exception, e:
                self.__is_available = False
                raise TFOMSClientException(0, e.message)
            else:
                self.__is_logged_in = True

    @property
    def is_available(self):
        """Свойство доступности сервиса"""
        return self.__is_available

    @property
    def is_logged_in(self):
        """Свойство пройденности аутентификации у сервиса"""
        return self.__is_logged_in

    @ensure_can_connect
    def check_policy(self, policy):
        """Проверка полиса"""
        url = '{}/check'.format(self.service_url)
        r = requests.post(url, data=json.dumps(policy), cookies=self.cookies)
        if r.status_code == requests.codes.ok:
            if r.content == 'true':
                return True
            elif r.content == 'false':
                return False
        else:
            raise TFOMSClientException(r.status_code, u"Ошибка при выполнении проверки")

    @ensure_can_connect
    def search_policy(self, policy):
        """Поиск пациента/полиса"""
        url = '{}/search'.format(self.service_url)
        r = requests.post(url, data=json.dumps(policy), cookies=self.cookies)
        if r.status_code == requests.codes.ok:
            try:
                result = r.json()
            except ValueError, e:
                raise TFOMSClientException(0, e.message)
            else:
                return result
        else:
            raise TFOMSClientException(r.status_code, u"Ошибка при выполнении поиска")

    @staticmethod
    def __get_policy_data(data):
        policy = dict()
        if 'policy_type' not in data:
            raise AttributeError
        policy['policy_doctype'] = int(data['policy_type'])
        if 'serial' in data:
            policy['policy_series'] = data['serial']
        elif 'series' in data:
            policy['policy_series'] = data['series']
        policy['policy_number'] = data['number']
        return policy

    @staticmethod
    def __get_patient_data(data):
        patient = dict()
        patient['lastname'] = data['lastName'].upper()
        patient['firstName'] = data['firstName'].upper()
        patient['midname'] = data['patrName'].upper()
        if 'birthDate' in data:
            patient['birthdate'] = datetime.strftime(data['birthDate'], '%d.%m.%Y')
        return patient

    def search_patient(self, patient_data):
        try:
            policy = self.__get_policy_data(patient_data)
            patient = self.__get_patient_data(patient_data)
        except AttributeError:
            return dict(status=AnswerCodes(0), data=None)

        all_data = patient
        all_data.update(policy)
        try:
            result = self.search_policy(all_data)
        except ValueError, e:
            logging.error(e)
            return dict(status=AnswerCodes(0), data=None)
        if result:
            return dict(status=AnswerCodes(2), data=result)
        elif result is None:
            return dict(status=AnswerCodes(0), data=None)
        else:
            # Не нашли пациента в ТФОМС, проверяем только полис
            try:
                result = self.search_policy(policy)
            except ValueError, e:
                logging.error(e)
                return dict(status=AnswerCodes(0), data=None)
            if result:
                return dict(status=AnswerCodes(3), data=result)
            elif result is None:
                return dict(status=AnswerCodes(0), data=None)
            else:
                return dict(status=AnswerCodes(1), data=None)