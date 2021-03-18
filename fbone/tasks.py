# -*- coding: utf-8 -*-

from celery import Celery
from flask import Flask, request, jsonify

from .config import DefaultConfig
#from .extensions import db, mdb, mail, cache, sentinel

def create_app(config=None, app_name=None, blueprints=None):
    """Create a Flask app."""

    if app_name is None:
        app_name = DefaultConfig.PROJECT

    app = Flask(app_name, instance_relative_config=True)
    configure_app(app, config)
    #configure_extensions(app)

    return app

def configure_app(app, config=None):
    """Different ways of configurations."""

    # http://flask.pocoo.org/docs/api/#configuration
    app.config.from_object(DefaultConfig)

    # http://flask.pocoo.org/docs/config/#instance-folders
    app.config.from_pyfile('production.cfg', silent=True)

    if config:
        app.config.from_object(config)

def get_configure_app(app, config):
    return app.config.get(config)
        
# def configure_extensions(app):
#     # flask-sqlalchemy
#     db.init_app(app)

#     # Mongokit
#     mdb.init_app(app)

#     # flask-mail
#     mail.init_app(app)

#     # flask-cache
#     cache.init_app(app)

#     # Redis-Sentinel
#     sentinel.init_app(app)


def create_celery_app(app=None):
    app = app or create_app()
    celery = Celery(__name__, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)

    celery.Task = ContextTask
    return celery

celery = create_celery_app()
