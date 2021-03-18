# -*- coding: utf-8 -*-

import os

from utils import make_dir, INSTANCE_FOLDER_PATH


class BaseConfig(object):

    PROJECT = "fbone"

    # Get app root path, also can use flask.root_path.
    # ../../config.py
    PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    DEBUG = False
    TESTING = False

    ADMINS = ['huynhdattnt@gmail.com']

    # http://flask.pocoo.org/docs/quickstart/#sessions
    SECRET_KEY = 'secret key'

    LOG_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'logs')

    # Fild upload, should override in production.
    # Limited the maximum allowed payload to 16 megabytes.
    # http://flask.pocoo.org/docs/patterns/fileuploads/#improving-uploads
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(INSTANCE_FOLDER_PATH, 'uploads')


class DefaultConfig(BaseConfig):
    PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    DEBUG = True

    SENTRY_DSN = ""

    MAIL_HOST = ""
    FROM_ADDR = ""
    TO_ADDRS = [""]
    MAIL_USERNAME = ""
    MAIL_PASSWORD = ""

    # Flask-Sqlalchemy: http://packages.python.org/Flask-SQLAlchemy/config.html
    SQLALCHEMY_ECHO = False
    # QLALCHEMY_TRACK_MODIFICATIONS adds significant overhead and will be
    # disabled by default in the future.
    SQLALCHEMY_TRACK_MODIFICATIONS = True
    # SQLITE for prototyping.
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + INSTANCE_FOLDER_PATH + '/db.sqlite'
    # MYSQL for production.
    #SQLALCHEMY_DATABASE_URI = 'mysql://username:password@server/db?charset=utf8'
    #CELERY_BROKER_URL = 'amqp://guest:guest@localhost:5672/pdf_request'
    CELERY_BROKER_URL = 'amqp://guest:guest@linux7.sima.io:5676//'
    CELERY_ACCEPT_CONTENT = ['application/text', 'application/json', 'text/plain']
    #CELERY_ACCEPT_CONTENT = ['application/text']
    
    CELERY_RESULT_BACKEND = 'amqp'
    CELERY_DEFAULT_QUEUE = 'celery'
    CELERY_ROUTES = {
        'ai.pdf_request': {'queue': 'pdf_request'},
    }

    GET_RECORDS_URL     = 'https://linux7.sima.io/elten/esd3.7.6/api.php?debug&function='
    API_KEY             = 'neuscanapi'
    API_SIG             = 'asdhu1298y3haskjdhasjdhaksh98'
    PROCESSING_ORDER    = 'ASC'
    NUMBER_OF_RECORD    = 1
    MACHINE_NAME        = 'VM'
    PRIORITY_ID         = 3

    UPLOAD_SERVER       = 'linux7.sima.io'
    UPLOAD_USER         = 'karen'
    TMP_DIR_BULK        = PROJECT_ROOT + '/tmp_dir' + '/bulk'
    TMP_DIR_NON_BULK    = PROJECT_ROOT + '/tmp_dir' + '/non_bulk'
    OOPS_DIR            = PROJECT_ROOT + '/temp/oops'

    THREAD_NUM          = 4# cores number of each server

    GHOST_SCRIPT        = PROJECT_ROOT + '/fbone/lib/ghostscript/bin/gs'
    GHOST_MEMORY        = 300000
    TIMEOUT             = 20
    COLOR_THRESHOLD     = 0.0
    PNG16M_PROCESS      = 0.5

class TestConfig(BaseConfig):
    TESTING = True
    CSRF_ENABLED = False
    WTF_CSRF_ENABLED = False

    SQLALCHEMY_ECHO = False
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
