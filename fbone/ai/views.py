# -*- coding: utf-8 -*-

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_user, current_user, logout_user
from flask_restful import Api, Resource
from tasks import pdf_request, process_barcode
from kombu import BrokerConnection

ai = Blueprint('ai', __name__, url_prefix='/ai')

@ai.route('/connect', methods=['Get'])
def connect_rabbitmq():
    message = 'hello, this function is connection to RabbitMQ'
    print message
    print current_app.config['CELERY_BROKER_URL']
    conn = BrokerConnection(current_app.config['CELERY_BROKER_URL'], heartbeat=int(10))
    pdf_request.apply_async(['hello'],connection=conn)
    conn.release()

    return jsonify({'error_code': 0, 'error_desc': 'Cannot call to IAPI server, check connection again'})

# @ai.route('/read_data_matrix', methods=['Get'])
# def read_barcode():
#     file_path = '/home/datht/Desktop/example_bulkscan_barcodes.pdf'
#     process_barcode(file_path)


