# -*- coding: utf-8 -*-

from flask_script import Manager

from gevent import monkey
monkey.patch_all()
import gevent

from fbone import create_app
from fbone.extensions import db
#from iapi.utils import MALE


app = create_app()
manager = Manager(app)

@manager.command
def run():
    """Run in local machine."""
    app.run(host='0.0.0.0')

if __name__ == "__main__":
    manager.run()

