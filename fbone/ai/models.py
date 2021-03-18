import threading
import time
import logging

class ThreadPool(object):
    def __init__(self):
        super(ThreadPool, self).__init__()
        self.active = []
        self.lock = threading.Lock()
    def makeActive(self, name):
        with self.lock:
            self.active.append(name)
            logging.debug('Running: %s', self.active)
    def makeInactive(self, name):
        with self.lock:
            try:
                self.active.remove(name)
            except:
                logging.warning('{} not in list'.format(name))
                pass
            logging.debug('Running: %s', self.active)