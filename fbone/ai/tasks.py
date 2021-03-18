# -*- coding: utf-8 -*-

from ..tasks import celery
from celery import current_app
import requests
import traceback
import json
import os
from pylibdmtx.pylibdmtx import decode
from PIL import Image
import sys
import subprocess
import time
import logging
from models import ThreadPool
from PyPDF2 import PdfFileWriter, PdfFileReader
from itertools import tee, islice, chain, izip
import hashlib
from asprise_ocr_api import *
import datetime
from random import randint
from slugify import slugify
import ssl
from functools import wraps
from lxml import etree
from celery import signals
import glob

import shutil
from celery.concurrency import asynpool

asynpool.PROC_ALIVE_TIMEOUT = 1000
logging.disable(logging.FATAL)

@celery.task(name = 'ai.pdf_request', rate_limit='5/s')
def pdf_request(message):
    '''
        Listening "pdf request" channel, receive message and pot it out RabbitMQ
    '''
    ssl.wrap_socket = sslwrap(ssl.wrap_socket)
    try:
        if message == 'pdf process request':
            #time.sleep(20) # for testing

            # Call to get records in bpq api
            get_records = call_to_esd_api('get_records_in_bpq', 1)
            if get_records['code'] == 0:
                print 'Warring: No record in BPQ'
                return {} #nothing to do
            data = get_records['response']['data']
            # get_records['response']['data'][0]['Annotation'] = "apostrophe'apostrophe" # for testing
            print 'data response back is %s' %(get_records['response'])

            for d in data:
                queue_id = d.get('QueueId', None)
                path = d.get('Path', None)
                box_number = d.get('Boxnumber', None)
                priority = d.get('Priority', current_app.conf.get("PRIORITY_ID"))
                pdf_name = path.rsplit('/', 1)[1]
                if d.get('KeepBarcodeInd', 't') == 't':
                    keep_barcode_ind = True
                else:
                    keep_barcode_ind = False
                #keep_barcode_ind = False # for testing

                # Call to get bpq context to get upload_dir
                get_bpq_context_data = call_to_esd_api('get_bpq_context', 1)['response']
                upload_dir  = get_bpq_context_data.get('upload_dir', None)
                pkged       = get_bpq_context_data.get('pkged', None)
                use_sphinx  = get_bpq_context_data.get('use_sphinx', None)
                sphinx_db   = get_bpq_context_data.get('sphinx_db', None)

                if not upload_dir:
                    print 'Error: upload dir not found'
                    return {}

                src_path = upload_dir + '/{}/{}'.format(box_number, pdf_name)
                num_pages = 0
                pool = ThreadPool()
                s = threading.Semaphore(current_app.conf.get("THREAD_NUM"))

                # Clear up all files and folders inside the /tmp_dir directory
                clear_up_cm = 'rm -rf {}/* && rm -rf {}/*'.format(current_app.conf.get("TMP_DIR_BULK"), current_app.conf.get("TMP_DIR_NON_BULK"))
                os.system(clear_up_cm)

                if d.get('IsBulk', False) == 't':
                    # Handle pdf file in BULK scan situation
                    dir = current_app.conf.get("TMP_DIR_BULK") + '/' + hash_pdf_name('bulk')
                    pdf_file_path = dir + "/" + pdf_name

                    # Rsync to server and get pdf file
                    download_pdf_file(src_path, dir)

                    with open(pdf_file_path, 'rb') as f:
                        try:
                            pdf_input = PdfFileReader(f, strict = False)
                            num_pages = pdf_input.getNumPages()
                        except:
                            pass

                    scannedimages_path = upload_dir + '/' + box_number
                    pdf_name = str(os.path.basename(pdf_file_path))
                    data = {}
                    data['scannedimages_path']  = str(scannedimages_path)
                    data['queue_id']            = str(queue_id)
                    data['pdf_name']            = str(pdf_name)
                    data['keep_barcode_ind']    = 't' if keep_barcode_ind else 'f'
                    data['priority']            = str(priority)
                    with open(dir + '/data.txt', "wb") as f:
                        f.write(str(data))
                    process_barcode(pool, s, pdf_file_path, num_pages, scannedimages_path, queue_id, keep_barcode_ind, priority)
                else:
                    # Rsync to server and get pdf file
                    dir = current_app.conf.get("TMP_DIR_NON_BULK") + '/' + hash_pdf_name('non_bulk')
                    download_pdf_file(src_path, dir)

                    # Handle pdf file in NON-BULK scan situation
                    pdf_file_path = dir + "/" + pdf_name

                    with open(pdf_file_path, 'rb') as f:
                        try:
                            pdf_input = PdfFileReader(f, strict = False)
                            num_pages = pdf_input.getNumPages()
                        except:
                            pass

                    deliver_searchable_pdf  = d['DeliverSearchablePdf']
                    has_interactive         = d['HasInteractive']

                    # Generate textfile Sphinx format
                    have_sphinx = False
                    if use_sphinx and sphinx_db == 0 or sphinx_db == 1:
                        have_sphinx = True

                    xml_data = {}
                    xml_data['profile_id']      = str(d['Profile'])
                    xml_data['image_id']        = str(d['ImageID'])
                    xml_data['box_number']      = str(d['Boxnumber'])
                    xml_data['box_part']        = str(d['Boxpart'])
                    xml_data['bookmark_id']     = str(d['QueueId'])


                    if have_sphinx:
                        xml_data['have_sphinx'] = "t"
                    else:
                        xml_data['have_sphinx'] = "f"
                    if deliver_searchable_pdf == 't':
                        xml_data['have_ocr']    = "t"
                    else:
                        xml_data['have_ocr']    = "f"
                    if has_interactive:
                        xml_data['has_interactive'] = "t"
                    else:
                        xml_data['has_interactive'] = "f" # make sure "", not ''

                    xml_data['pkged']       = str(pkged)
                    pdf_name                = str(os.path.basename(pdf_file_path).rsplit('.pdf',1)[0])
                    xml_data['pdf_name']    = pdf_name
                    print 'xml_data is: {}'.format(xml_data)
                    with open(dir + '/xml_data.txt', "wb") as f:
                        f.write(str(xml_data))
                    have_ocr = False

                    if deliver_searchable_pdf == 't' and not has_interactive:
                        # Follow by ticket: http://cmos.neuone.com:8080/browse/NR-30
                        have_ocr = True
                        # Generate 2 PNG files per PDF and temp image (1 for thumbnail and 1 regular size)
                        generate_image(pdf_file_path, num_pages, dir, True)
                        # Generate searchable PDF for each of images
                        ocr_pdf(s, pool, pdf_file_path, num_pages, dir, xml_data, have_sphinx)
                    else:
                        # Generate pdfs based original pdf
                        if has_interactive:
                            flat = True
                        else:
                            flat = False
                        split_pdf_into_single_page(pdf_file_path, dir, flat)
                        if have_sphinx:
                            # Generate 2 PNG files per PDF and temp image (1 for thumbnail and 1 regular size)
                            generate_image(pdf_file_path, num_pages, dir, True)
                            extract_text_from_pdf(s, pool, pdf_name, num_pages, dir)
                        else:
                            # Generate 2 PNG files per PDF (1 for thumbnail and 1 regular size)
                            generate_image(pdf_file_path, num_pages, dir, False)
                    if have_sphinx:
                        create_sphinx_file(s, pool, num_pages, dir, pdf_name)
                    if add_pages(xml_data, num_pages):
                        xml_data['add_pages'] = "t"
                        with open(dir + '/xml_data.txt', "wb") as f:
                            f.write(str(xml_data))
                    else:
                        logging.error('Calling to add_pages api failed with xml data: {}'.format(xml_data))
                        return {}
                    sync_updatebpq(pool, pdf_file_path, xml_data, dir, num_pages, have_ocr, have_sphinx)
                    logging.info('Process non bulk with bookmark_id {} success'.format(str(d['QueueId'])))

    except Exception as error:
        traceback.print_exc()
    return {}

def call_to_esd_api(api_name, is_post_method, data_json=None):
    '''
    Call to ESD api when received message from pdf_request queue
    params:
        - api_name: name of the api
        - is_post_method:
            0: both get method and post method
            1: post method
            2: get method
    return:
        a dict with code and data response back
            code 1: successful
            code 0: error occurred
    '''
    if is_post_method:
        data = {}
        # for post method
        print 'calling to api: %s' %api_name
        if api_name == 'get_records_in_bpq':
            print 'waiting for edit ...'
            url = current_app.conf.get('GET_RECORDS_URL') + 'GetRecordsInBPQ'
            data['json'] = str({"Neusearch": {
                "api_key"          : current_app.conf.get("API_KEY"),
                "api_sig"          : current_app.conf.get("API_SIG"),
                "processing_order" : current_app.conf.get("PROCESSING_ORDER"),
                "num_of_record"    : current_app.conf.get("NUMBER_OF_RECORD"),
                "machine_name"     : current_app.conf.get("MACHINE_NAME")
                }
            }).replace('\'', '"')
        elif api_name == 'get_bpq_context':
            url = current_app.conf.get('GET_RECORDS_URL') + 'GetBPQContext'
            data['json'] = str({"Neusearch": {
                "api_key"          : current_app.conf.get("API_KEY"),
                "api_sig"          : current_app.conf.get("API_SIG"),
                "processing_order" : current_app.conf.get("PROCESSING_ORDER"),
                "num_of_record"    : current_app.conf.get("NUMBER_OF_RECORD"),
                "machine_name"     : current_app.conf.get("MACHINE_NAME")
                }
            }).replace('\'', '"')
        elif api_name == 'split_process':
            url = current_app.conf.get('GET_RECORDS_URL') + 'SplitProcess'
            data['json'] = str(data_json).replace('\'', '"')
        elif api_name == 'update_bpq_as_processed':
            url = current_app.conf.get('GET_RECORDS_URL') + 'UpdateBPQAsProcessed'
            data['json'] = str({"Neusearch": {
                "api_key"           : current_app.conf.get("API_KEY"),
                "api_sig"           : current_app.conf.get("API_SIG"),
                "bookmarkProcessQueueId": data_json.get("bookmark_process_queue_id"),
                "processed"         : data_json.get("processed"),
                #"synced"            : data_json.get('synced'),
                "machineName"      : current_app.conf.get("MACHINE_NAME")
            }}).replace('\'', '"')
        elif api_name == 'add_pages':
            url = current_app.conf.get('GET_RECORDS_URL') + 'AddPages'
            data['json'] = str({"Neusearch": {
                "api_key": current_app.conf.get("API_KEY"),
                "api_sig": current_app.conf.get("API_SIG"),
                "bookmark_process_queue_id": data_json.get("bookmark_process_queue_id"),
                "pages": data_json.get("pages"),
                "machineName": current_app.conf.get("MACHINE_NAME")
            }}).replace('\'', '"')

        headers = {"api_key": current_app.conf.get("API_KEY"), "api_sig": current_app.conf.get("API_SIG")}
        _time = 0
        while(True):
            request = requests.post(url, data=data, headers=headers, verify=False)
            print 'request status code: {}'.format(request.status_code)
            if request.status_code == 200 or request.status_code == 201:
                print 'Called to api %s successfull' %api_name
                #print request.text
                return {'code': 1, 'response': request.json()}

            _time = _time + 1
            if _time >= 3:
                break
            time.sleep(_time)
        print 'error: %s' %request.text
        return {'code': 0, 'response': request.json()}

def download_pdf_file(src_path, dest_path):
    '''
    Download pdf file by using rsync command
    - Params:
        + src_path: path of pdf file on remote server
        + dest_path: path to save pdf file (temporary folder, when we finish, this file will be deleted)
    '''
    if not os.path.exists(dest_path):
        mkdir_command = 'mkdir %s -p' %dest_path
        os.system(mkdir_command)
    rsync_command = 'rsync -avz %s@%s:%s %s' % (current_app.conf.get("UPLOAD_USER"), current_app.conf.get("UPLOAD_SERVER"), src_path, dest_path)
    print 'rsync command is: %s' %rsync_command
    _time = 0
    while(True):
        if _time > 3:
            break
        error = os.system(rsync_command)
        if not error:
            print 'Rsync file path %s successful' % src_path
            return 1
        _time = _time + 1
        time.sleep(_time)
    logging.error('Could not connect to {}. Connection timed out.'.format(current_app.conf.get("UPLOAD_SERVER")))
    return 0

def execute_not_wait(cmd):
    #print 'cmd is: {}'.format(cmd)
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
    popen.stdout.close()

def get_barcode_from_pdf_file(s, pool, pdf_file, num_pages):
    '''
    Get all of barcodes from pdf file
    :param s: number of threads
    :param pool:
    :param pdf_file: pdf file path
    :param num_pages: number of pages
    :return:
        - 0: failed
        - 1: success
    '''

    # Pre-process image
    temp_dir = os.path.dirname(pdf_file) + '/temp'
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    pdf_name = os.path.basename(pdf_file).rsplit('.pdf', 1)[0]
    execute_not_wait([
        current_app.conf.get("GHOST_SCRIPT"), '-dSAFER', '-dBATCH', '-dNOPAUSE', '-sDEVICE=pnggray', '-dINTERPOLATE',
        '-r300', '-dPDFSETTINGS=/prepress', '-dPDFFitPage', '-dDownScaleFactor=2',
        '-sOutputFile={}/{}_%06d.png'.format(temp_dir, pdf_name), '-dUseTrimBox=true', '-dUseCropBox=true', '-f',
        str(pdf_file),
        '-c', '{}'.format(current_app.conf.get("GHOST_MEMORY")),
    ])

    barcodes = {}
    for i in range(num_pages):
        temp_image = temp_dir + '/{}_{}.png'.format(pdf_name, format(i + 1, "06"))
        t = threading.Thread(target=_get_barcode_from_pdf_file, name=str(i + 1),
                             args=(s, pool, temp_image, barcodes))
        t.start()

    result = []
    _time = 0
    while (True):
        _time = _time + 1
        if len(barcodes) == num_pages:
            break
        time.sleep(_time)

    for key in sorted(barcodes):
        if barcodes[key]:
            if len(barcodes[key]) < 5 or not 'NEU_' in barcodes[key]:
                continue
            result.append('%s:%s' %(key, barcodes[key]))
    logging.info('Barcode result is: {}'.format(barcodes))
    return iter(result)

def _get_barcode_from_pdf_file(s, pool, temp_image, barcodes):
    '''
    Get barcode form each png image
    :param s: number of threads
    :param pool:
    :param temp_image: path of image
    :param barcodes: a dict which contains barcodes
    :return:
        - 0: failed
        - 1: success
    '''
    logging.debug('get barcode from pdf the image')
    try:
        with s:
            name = threading.currentThread().getName()
            pool.makeActive(name)
            _time = 0
            Image.LOAD_TRUNCATED_IMAGES = True
            while(True):
                try:
                    result = decode(Image.open(temp_image), timeout=1000)
                    break
                except:
                    pass
                _time = _time + 1
                if _time >= current_app.conf.get("TIMEOUT"):
                    logging.error('The file {} has been truncated!'.format(temp_image))
                    return 0 # timeout
                time.sleep(_time)
            if result:
                barcode = result[0].data
                barcodes[int(name)] = barcode
            else:
                barcodes[int(name)] = None
            pool.makeInactive(name)
    except Exception as error:
        traceback.print_exc()
        return 0
    return 1

def makeup_bc(alist):
    '''
    The Bubble Sort, following by: http://interactivepython.org/runestone/static/pythonds/SortSearch/TheBubbleSort.html
    :param alist:
    :return:
        None
    '''
    for passnum in range(len(alist)-1,0,-1):
        for i in range(passnum):
            if int(alist[i].split(':', 1)[0]) > int(alist[i + 1].split(':', 1)[0]):
                temp = alist[i]
                alist[i] = alist[i+1]
                alist[i+1] = temp

def is_adjacent_pages(pre, cur, nxt):
    '''
    Check if 2 barcodes are founded in adjacent pages
    :param pre:
    :param cur:
    :param nxt:
    :return:
    '''
    try:
        if int(cur.split(':', 1)[0]) + 1 == int(nxt.split(':', 1)[0]):
            return True
    except:
        pass
    try:
        if int(cur.split(':', 1)[0]) -1 == int(pre.split(':', 1)[0]):
            return True
    except:
        pass
    return False

def process_barcode(pool, s, pdf_file, num_pages, upload_dir, queue_id, keep_barcode_ind, priority, re_process=None):
    '''
    Processing barcode from pdf file
    following to http://libdmtx.sourceforge.net/display.php?text=dmtxread.1
    create a thumbnail: http://www.pythonforbeginners.com/modules-in-python/how-to-use-pillow
    install dmtx_utils: https://github.com/dmtx/dmtx-utils
    '''
    tasks = []
    try:
        if not upload_dir or not queue_id:
            logging.info('Upload dir or queue_id cannot be None')
            return 0
        if num_pages:
            first = True
            if re_process:
                print 'reprocess is: {}'.format(re_process)
                bc = []
                for p in re_process:
                    for key, value in p.iteritems():
                        bc.append('{}:{}'.format(value['page_index'], key))
                # Makeup array barcode
                makeup_bc(bc)
                bc = iter(bc)
            else:
                bc = get_barcode_from_pdf_file(s, pool, pdf_file, num_pages)
            number_of_threads = 0

            for previous, item, nxt in previous_and_next(bc):
                # print item
                # print nxt

                _tmp  = str(item).split(':', 1)
                _to   = (int(nxt.split(':', 1)[0]) - 1) if nxt else (num_pages)
                _from = int(_tmp[0]) + 1
                if re_process:
                    print 're_process is: {}'.format(re_process)
                    index = next(index for (index, d) in enumerate(re_process) if d.keys()[0] == str(_tmp[1]).rstrip())
                    if re_process[index].get(str(_tmp[1]).rstrip(), {}).get('is_finish', 'f') == 't':
                        task = {str(_tmp[1]).rstrip():
                        {
                            'page_index': _from - 1,
                            'is_finish' : 't'
                        }}
                        tasks.append(task)
                        first = False
                        number_of_threads = number_of_threads + 1
                        continue
                else:
                    if is_adjacent_pages(str(previous), str(item), str(nxt)):
                        logging.warning('Warning: barcodes are founded in adjacent pages')
                        adjacent_pages = True
                        t = threading.Thread(target=_process_barcode, name=str(_tmp[1]).rstrip(),
                                             args=(s, pool, pdf_file, _from, _to, upload_dir, queue_id, tasks, priority, keep_barcode_ind, adjacent_pages))
                        t.start()
                        number_of_threads = number_of_threads + 1
                        first = False
                        continue
                    else:
                        if first:
                            if _from != 2:
                                logging.warning('Warning: Barcode not found on first page')
                                t = threading.Thread(target=_process_barcode, name='barcode_not_found',
                                                     args=(s, pool, pdf_file, 1, _from - 2, upload_dir, queue_id, tasks, priority, False))
                                t.start()
                                number_of_threads = number_of_threads + 1
                        t = threading.Thread(target=_process_barcode, name=str(_tmp[1]).rstrip(), args=(s, pool, pdf_file, _from, _to, upload_dir, queue_id, tasks, priority, keep_barcode_ind))
                        t.start()
                        number_of_threads = number_of_threads + 1
                        first = False
                        if not nxt:
                            t.join()
            if not number_of_threads:
                logging.info('ERROR: Barcode not found on all pages')
                t = threading.Thread(target=_process_barcode, name='barcode_not_found',
                                     args=(s, pool, pdf_file, 1, num_pages, upload_dir, queue_id, tasks, priority, False))
                t.start()
                t.join()
                number_of_threads = 1
        else:
            logging.error('Pdf file invalid, number of pages equal 0')

    except Exception as error:
        traceback.print_exc()
        return {}

    # Check all tasks is finished?
    _time = 0
    print len(tasks)
    print number_of_threads
    logging.info('Wait for all the tasks to finish!')
    while(len(tasks) != number_of_threads):
        # print len(tasks)
        # print number_of_threads
        _time = _time + 1
        if _time == current_app.conf.get("TIMEOUT"):
            return 0  # timeout
        time.sleep(_time)
    data = {}
    pdf_name                    = pdf_file.rsplit('/', 1)[1]
    dir                         = pdf_file.rsplit('/', 1)[0]
    data['scannedimages_path']  = str(upload_dir)
    data['queue_id']            = str(queue_id)
    data['pdf_name']            = str(pdf_name)
    data['tasks']               = tasks
    data['keep_barcode_ind']    = 't' if keep_barcode_ind else 'f'
    data['priority']            = str(priority)
    for task in tasks:
        # task be like this:
        # {
        #     'NEU_Travis_7/23/2016_Frybo Fries': {
        #         'page_index': 1,
        #         'is_finish': 't',
        #     }
        # }
        for key, value in dict(task).iteritems():
            print 'key - value: {} - {}'.format(key, value)
            with open(dir + '/data.txt', "wb") as f:
                f.write(str(data))
            # Call to SplitProcess failed.
            if value['is_finish'] == 'f':
                return {}

    # Call ESD API to mark the document processed and synched.
    logging.info('calling to ESD API to mark the document processed and synched')
    data_json = {
        'bookmark_process_queue_id': str(queue_id),
        'processed': 'true',
        #'synced': 'false'
    }
    result = call_to_esd_api('update_bpq_as_processed', 1, data_json)
    if result.get('code', 0):
        logging.info("Call update_bpq_as_processed API success!")
        shutil.rmtree(dir)
    else:
        logging.error("Call update_bpq_as_processed API failed with data json %s" % (data_json))

def _process_barcode(s, pool, pdf_file, _from, _to, upload_dir, queue_id, tasks, priority, keep_barcode_ind=False, adjacent_pages=False):
    try:
        with s:
            logging.info('_process_barcode: Thread is starting ...')
            name = threading.currentThread().getName()
            dir = os.path.dirname(pdf_file)
            pool.makeActive(name)
            hash = hash_pdf_name(name)

            pdf_out = dir + '/{}.pdf'.format(hash)
            if keep_barcode_ind:
                _from = _from - 1

            if _from > _to:
                _from = _to
            logging.info('from and to are: {} - {}'.format(_from, _to))
            try:
                cm = 'pdfsplit -p -o %s %s-%s %s' % (pdf_out, _from, _to, pdf_file)
                os.system(cm)
            except:
                # Catch for Barcode not found on all pages situation
                pdf_out = pdf_file

            # Rsync back to scannedimages folder
            rsync_command = 'rsync -avz %s %s@%s:%s' % (pdf_out, current_app.conf.get("UPLOAD_USER"), current_app.conf.get("UPLOAD_SERVER"), upload_dir)
            print 'rsync_command is: {}'.format(rsync_command)
            os.system(rsync_command)
            # Calling to SplitProcess
            name_bk = None
            if _from == _to and adjacent_pages and not keep_barcode_ind:
                name_bk = name
                name = 'barcode_not_found' # set this for adjacent pages case

            if name == 'barcode_not_found':
                data_json = {
                    'priorityID': int(priority),
                    'barcode': '',
                    'filename': str(upload_dir.rsplit('/', 1)[1] + '/' + os.path.basename(pdf_out)),
                    'source_bookmark_process_queue_id': str(queue_id)
                }
            else:
                data_json = {
                    'priorityID': int(priority),
                    'barcode': str(name),
                    'filename': str(upload_dir.rsplit('/', 1)[1] + '/' + os.path.basename(pdf_out)),
                    'source_bookmark_process_queue_id': str(queue_id)
                }

            logging.info('payload of split process api: {}'.format(data_json))

            result = call_to_esd_api('split_process', 1, data_json)
            if not keep_barcode_ind:
                if name != 'barcode_not_found':
                    task = {name: {
                        'page_index': _from - 1,
                        'is_finish' : 'f'
                    }}
                else:
                    # Barcode not found for this thread
                    task = {name: {
                        'page_index': 1,
                        'is_finish': 'f'
                    }}
            else:
                if name != 'barcode_not_found':
                    task = {name: {
                        'page_index': _from,
                        'is_finish': 'f'
                    }}
                else:
                    # Barcode not found for this thread
                    task = {name: {
                        'page_index': 1,
                        'is_finish': 'f'
                    }}

            if result.get('code', 0):
                task[name]['is_finish'] = 't'
                tasks.append(task)
                if name_bk:
                    pool.makeInactive(name_bk)
                else:
                    pool.makeInactive(name)
                return 1

            tasks.append(task)
            if name_bk:
                pool.makeInactive(name_bk)
            else:
                pool.makeInactive(name)
            return 0

    except Exception as error:
        traceback.print_exc()
        tasks.append({name: 0})
        return 0

def split_pdf_into_single_page(pdf_file, dir, flat=False):
    '''
    Split the PDF into single page pdf.
    Follow by the ticket: http://cmos.neuone.com:8080/browse/NR-30
    :param pdf_file:
    :return:
        - 1: success
        - 0: something is wrong
    '''
    try:
        flat_file = None
        if flat:
            import pypdftk
            try:
                flat_file = pdf_file.rsplit('.',1)[0] + '_' + 'flat.pdf'
                pypdftk.fill_form(pdf_file, out_file=flat_file, flatten=True)
            except:
                logging.ERROR('Cannot flat the pdf file: {}'.format(pdf_file))
                pass

        logging.info('Split pdf into single pages.')
        pdf_name = os.path.basename(pdf_file).rsplit('.pdf',1)[0]
        if flat_file:
            pdf_file = flat_file
        with open(pdf_file, 'rb') as f:
            pdf_input = PdfFileReader(f, strict=False)
            for i in xrange(pdf_input.numPages):
                output = PdfFileWriter()
                output.addPage(pdf_input.getPage(i))
                with open('{}/{}_{}.pdf'.format(dir, pdf_name, format(i + 1, "06")), "wb") as outputStream:
                    output.write(outputStream)
            if flat_file:
                os.remove(flat_file)
        return 1
    except Exception as error:
        traceback.print_exc()
        return 0

def generate_image(pdf_file, num_pages, dir, need_pre_process_image=True):
    '''
    Generate 2 PNG files per PDF (1 for thumbnail and 1 regular size)
    :param pdf_file:
    :param dir:
    :return:
        - 1: success
        - 0: failed
    '''
    try:
        recreate_hight_image = False
        pages_have_color = detect_color_in_pdf(pdf_file)
        if num_pages:
            png_dir = dir + '/' + 'png'
            if not os.path.exists(png_dir):
                os.makedirs(png_dir)

            if len(pages_have_color) / float(num_pages) < current_app.conf.get("PNG16M_PROCESS"):
                s_device = 'pnggray'
                recreate_hight_image = True
            else:
                s_device = 'png16m'
            t = threading.Thread(target=_generate_image, name=str('hight_image'),
                                     args=(pdf_file, png_dir, s_device))
            t.start()
            if need_pre_process_image:
                temp_dir = dir + '/' + 'temp'
                if not os.path.exists(temp_dir):
                    os.makedirs(temp_dir)
                t = threading.Thread(target=_generate_image, name=str('temp_image'),
                                     args=(pdf_file, temp_dir, s_device))
                t.start()
        else:
            logging.error('Pdf file invalid, number of pages equal 0')

        # Generate thumbs images and generate hight image again if it have color inside
        thumbs_dir = dir + '/' + 'thumbs'
        if not os.path.exists(thumbs_dir):
            os.makedirs(thumbs_dir)
        logging.info('Creating low resolution images ...')
        mxt = current_app.conf.get("THREAD_NUM") * 2
        s = threading.Semaphore(mxt)
        pool = ThreadPool()
        for i in range(num_pages):
            if recreate_hight_image and i in pages_have_color:
                t = threading.Thread(target=_create_low_resolution_image, name=str(i + 1),
                                    args=(s, pool, pdf_file, dir, True))
            else:
                t = threading.Thread(target=_create_low_resolution_image, name=str(i + 1),
                                     args=(s, pool, pdf_file, dir))
            t.start()
            if (i + 1) % mxt == 0:
                t.join()

    except Exception as error:
        traceback.print_exc()


def is_float(s):
    try:
        float(s) # for int, long and float
    except ValueError:
        return False
    return True

def detect_color_in_pdf(pdf_file):
    def execute_and_get_page_which_contain_color(cmd):
        pages_have_color = []
        try:
            # print 'cmd is: {}'.format(cmd)
            popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
            output, error = popen.communicate()
            popen.stdout.close()
            lines = output.strip().split('\n')

            for line in lines:
                if 'CMYK OK' in line:
                    ink_values = [float(value) for value in line.split(' ') if value and is_float(value)]
                    if ink_values[0] > current_app.conf.get("COLOR_THRESHOLD") or\
                       ink_values[1] > current_app.conf.get("COLOR_THRESHOLD") or\
                       ink_values[2] > current_app.conf.get("COLOR_THRESHOLD"):
                        pages_have_color.append(lines.index(line))
        except:
            pass
        return pages_have_color
    pages_have_color = execute_and_get_page_which_contain_color([
        current_app.conf.get("GHOST_SCRIPT"), '-q', '-o', '-', '-sDEVICE=inkcov', pdf_file
    ])
    return pages_have_color

def _generate_image(pdf_file, dir, s_device=None):
    '''
    Implement generate images
    :param pdf_file: the path of pdf file
    :param dir: the directory which store iamges
    :return: None
    '''
    t_name = threading.currentThread().getName()
    pdf_name = os.path.basename(pdf_file).rsplit('.pdf', 1)[0]
    if not s_device:
        s_device = 'pnggray'
    if t_name == 'temp_image':
        # Generate temp images
        # /project/fbone/fbone/fbone/lib/ghostscript/bin/gs -dSAFER -dBATCH -dNOPAUSE -sDEVICE=pnggray -dINTERPOLATE -r300 -dDownScaleFactor=2 -sOutputFile=out2%d.png 1d63bab297c5bb9f9c4a4f36e10d18_1491734332.pdf -c 30000000
        execute_not_wait([
            current_app.conf.get("GHOST_SCRIPT"), '-dSAFER', '-dBATCH', '-dNOPAUSE', '-sDEVICE={}'.format(s_device), '-dINTERPOLATE',
            '-r300', '-dPDFSETTINGS=/prepress', '-dPDFFitPage', '-dDownScaleFactor=2',
            '-sOutputFile={}/{}_%06d.png'.format(dir, pdf_name), '-dUseTrimBox=true', '-dUseCropBox=true', '-f', str(pdf_file),
            '-c', '{}'.format(current_app.conf.get("GHOST_MEMORY")),
        ])
    else:
        # Generate hight images
        # /project/fbone/fbone/fbone/lib/ghostscript/bin/gs -dSAFER -dBATCH -dNOPAUSE -sDEVICE=png16m -r200 -dDownScaleFactor=2 -sOutputFile=out1%d.png /home/datht/Desktop/1122.pdf -c 30000000 setvmthreshold -f
        # /project/fbone/fbone/fbone/lib/ghostscript/bin/gs -dSAFER -dBATCH -dNOPAUSE -sDEVICE=pnggray -r200 -dDownSca==leFactor=2 -sOutputFile=out1%d.png 1d63bab297c5bb9f9c4a4f36e10d18_1491734332.pdf -c 30000000 setvmthreshold -f
        execute_not_wait([
            current_app.conf.get("GHOST_SCRIPT"),'-dSAFER', '-dBATCH', '-dNOPAUSE', '-sDEVICE={}'.format(s_device),
            '-r200', '-dPDFSETTINGS=/prepress','-dDownScaleFactor=2',
            '-sOutputFile={}/{}_%06d.png'.format(dir, pdf_name), '-f', str(pdf_file),
            '-c', '{}'.format(current_app.conf.get("GHOST_MEMORY")),
        ])

def detect_orientation(image_path, dir):
    def execute_and_rotate_image(cmd):
        from subprocess import Popen, PIPE, STDOUT
        popen = Popen(cmd, stderr=STDOUT,stdout=PIPE, shell=False)
        out = popen.communicate()[0]
        if 'Orientation in degrees:' in out:
            try:
                degrees = int(out.split('Orientation in degrees:',1)[1].split('\n', 1)[0].strip())
            except Exception as error:
                traceback.print_exc()
                degrees = 0

            if degrees == 180:
                # Rotate all images correctly
                logging.info('The image {} will be rotate {} degree'.format(image_path, degrees))
                images = []
                image_name  = image_path.rsplit('/', 1)[1]
                png_image   = dir + '/{}/{}'.format('png', image_name)
                thumb_image = dir + '/{}/{}'.format('thumbs', image_name)

                #bug in tesseract 3.04 - showing wrong degrees, comment out the auto rotation for now
                # Load the original image:
                #images.extend((image_path, png_image, thumb_image))
                #for image in images:
                #    _time = 0
                #    while not os.path.exists(image):
                #        _time = _time + 1
                #        if _time >= current_app.conf.get("TIMEOUT"):
                #            return 0  # timeout
                #        time.sleep(_time)

                #    img = Image.open(image)
                #    img2 = img.rotate(degrees)
                #    img2.save(image)

        popen.stdout.close()
        #return_code = popen.wait()

    execute_and_rotate_image(
        ['tesseract', image_path, '-', '-psm', '0']
    )

def ocr_pdf(s, pool, pdf_file, num_pages, dir, xml_data, have_sphinx, reocr_pages=None):
    '''
    # Generate 2 PNG files per PDF (1 for thumbnail and 1 regular size)
    # Generate searchable PDF for each of images
    # And generate textfile Sphinx format
    :param pdf_file:
    :param dir:
    :return:
    '''
    try:
        if num_pages:
            pdf_name = os.path.basename(pdf_file).rsplit('.pdf', 1)[0]
            have_ocr = True
            if reocr_pages:
                # Run OCR again if the error has occurred
                for i, val in enumerate(reocr_pages):
                    while (len([name for name in os.listdir(dir) if
                                os.path.isfile(os.path.join(dir, name))]) <= val - current_app.conf.get("THREAD_NUM") and i >= current_app.conf.get("THREAD_NUM")):  # include png folder, temp folder, and pdf file
                        time.sleep(0.3)
                    t = threading.Thread(target=_ocr_pdf_or_extract_text_only, name=str(val),
                                         args=(s, pool, pdf_name, dir, have_ocr, have_sphinx))
                    t.daemon = True
                    t.start()
            else:
                for i in range(num_pages):
                    while (len([name for name in os.listdir(dir) if os.path.isfile(os.path.join(dir, name))]) <= i + 1 - current_app.conf.get("THREAD_NUM") and i >= current_app.conf.get("THREAD_NUM")): #include png folder, temp folder, and pdf file
                        time.sleep(0.3)
                    t = threading.Thread(target=_ocr_pdf_or_extract_text_only, name=str(i + 1),
                                         args=(s, pool, pdf_name, dir, have_ocr, have_sphinx))
                    t.daemon = True
                    t.start()

            # Generate xml file
            generate_xml(dir, xml_data, num_pages)

    except Exception as error:
        traceback.print_exc()
    return 1

def get_width(pdf_path):
    '''
    Get width of pdf file
    http://cmos.neuone.com:8080/browse/NR-42
    :param pdf_path:
    :return:
        page size of pdf file
    '''
    try:
        if not os.path.exists(pdf_path):
            logging.error("The file {} does not exist!".format(pdf_path))
            return 0
        input1 = PdfFileReader(open(pdf_path, 'rb'))
        r = input1.getPage(0).mediaBox
        print '------------------------> r is: {}'.format(r)
        return float(r.getWidth())
    except Exception as error:
        traceback.print_exc()
        return 0

def _ocr_pdf_or_extract_text_only(s, pool, pdf_name, dir, have_ocr, have_sphinx):
    '''
        Orc processing - Generate searchable pdf file by png file
        :param s: using for semaphore threads
        :param pool: using for semaphore threads
        :param pdf_name: name of pdf file
        :param dir:
        :param have_ocr: if have ocr processing
        :return:
            - 0: failed
            - 1: success
        '''
    try:
        with s:
            t_name = threading.currentThread().getName()
            pool.makeActive(t_name)
            temp_image_path     = '{}/temp/{}_{}.png'.format(dir, pdf_name, format(int(t_name), "06"))
            searchable_pdf_path = '{}/{}_{}.pdf'.format(dir, pdf_name, format(int(t_name), "06"))
            temp_text_path      = '{}/temp/{}_{}.text'.format(dir, pdf_name, format(int(t_name), "06"))

            # # Get width from pdf file
            # pdf_path = '{}/{}.pdf'.format(dir, pdf_name)
            # width = get_width(pdf_path)
            # print '------------------------------------> width is: {}'.format(width)
            # if width > 1800:
            #     logging.info('Oops, this image is too large to display!')
            #     oops_image_path     = current_app.conf.get("OOPS_DIR") + "/dummy.png"
            #     png_image_path      = '{}/png/{}_{}.png'.format(dir, pdf_name, format(int(t_name), "06"))
            #     thumbs_image_path   = '{}/thumbs/{}_{}.png'.format(dir, pdf_name, format(int(t_name), "06"))
            #     _time = 0
            #     while (True):
            #         if os.path.exists(png_image_path) and os.path.exists(thumbs_image_path):
            #             break
            #         else:
            #             time.sleep(_time)
            #         if _time >= current_app.conf.get("TIMEOUT"):
            #             logging.error('The process has been cancelled.')
            #             return 0  # timeout
            #         _time = _time + 1
            #     cp_cm = "cp -r {} {} && cp -r {} {}".format(oops_image_path, png_image_path, oops_image_path, thumbs_image_path)
            #     os.system(cp_cm)
            # Check and wait until a file exists to read it
            _time = 0
            while not os.path.exists(temp_image_path):
                _time = _time + 1
                if _time == current_app.conf.get("TIMEOUT"):
                    return 0  # timeout
                time.sleep(_time)
            # Following by: https://tpgit.github.io/Leptonica/readfile_8c_source.html
            if os.stat(temp_image_path).st_size < 12:
                time.sleep(1)

            logging.info('Ocring pdf file is starting ... File path: %s' % searchable_pdf_path)
            # Ocring searchable pdf by temp image

            detect_orientation(temp_image_path, dir)
            Ocr.input_license("ent_SINGLE_2_Seats-Neubus-OS202800000800", "93513-5B34F-32BA4-FF1E4")
            Ocr.set_up()  # one time setup
            ocrEngine = Ocr()
            ocrEngine.start_engine("eng")
            s = None

            if have_ocr:
                s = ocrEngine.recognize(temp_image_path, -1, -1, -1, -1, -1,
                                        OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PDF,
                                        PROP_PDF_OUTPUT_FILE=searchable_pdf_path, PROP_PDF_OUTPUT_RETURN_TEXT='text',
                                        PROP_IMG_PREPROCESS_TYPE="custom", PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()",
                                        PROP_PDF_OUTPUT_TEXT_VISIBLE=False)
            else:
                s = ocrEngine.recognize(temp_image_path, -1, -1, -1, -1, -1,
                                        OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PLAINTEXT,
                                        PROP_IMG_PREPROCESS_TYPE="custom", PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()")

            # Write text to temp file
            if have_sphinx:
                s_makeup = u''.join((s)).encode('utf-8').strip()
                with open(temp_text_path, 'w') as f:
                    f.write(str(s_makeup))
            ocrEngine.stop_engine()

    except Exception as error:
        traceback.print_exc()
        return 0
    return 1

def _create_low_resolution_image(s, pool, pdf_file, dir, recreate_hight_image=None):
    '''
    Create low resolution images and hight resolution image if it have color inside by using Ghostscript.
    :param s: using for semaphore threads
    :param pool: using for semaphore threads
    :param pdf_file:
    :param dir:
    :return:
        - 0: failed
        - 1: success
    '''
    def execute(cmd):
        popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
        popen.stdout.close()
        return_code = popen.wait()
    try:
        with s:
            t_name = threading.currentThread().getName()
            pool.makeActive(t_name)
            pdf_name = os.path.basename(pdf_file).rsplit('.pdf', 1)[0]

            image_path = '{}/png/{}_{}.png'.format(dir, pdf_name, format(int(t_name), "06"))

            _time = 0
            while not os.path.exists(image_path):
                _time = _time + 1
                if _time == current_app.conf.get("TIMEOUT"):
                    return 0  # timeout
                time.sleep(_time)

            while(True):
                try:
                    with Image.open(image_path) as img:
                        width, height = img.size
                        break
                except:
                    #logging.warning("Error: can\'t read data {}, retry again.".format(image_path))
                    pass

            # Generate low resolution image based on hight resolution image
            #/project/fbone/fbone/fbone/lib/ghostscript/bin/gs -dSAFER -dBATCH -dNOPAUSE -r120 -sDEVICE=pngmono -dTextAlphaBits=1 -g844x1090 -dPDFFitPage -dTextAlphaBits=1 -o out1.png page1.pdf
            execute([
                current_app.conf.get("GHOST_SCRIPT"), '-dSAFER', '-dNOPAUSE',
                '-sDEVICE=pngmono', '-r120', '-dTextAlphaBits=1', '-g{}x{}'.format(width, height), '-dPDFFitPage',
                '-dFirstPage={}'.format(t_name), '-dLastPage={}'.format(t_name),
                '-o', '{}/{}_{}.png'.format(dir + '/thumbs', pdf_name, format(int(t_name), "06")), '-f', pdf_file,
                '-c', '{}'.format(int(current_app.conf.get("GHOST_MEMORY") / current_app.conf.get("THREAD_NUM"))),
            ])

            # Recreate hight resolution image if it have color inside
            if recreate_hight_image:
                s_device = 'png16m'
                execute_not_wait([
                    current_app.conf.get("GHOST_SCRIPT"), '-dSAFER', '-dBATCH', '-dNOPAUSE',
                    '-sDEVICE={}'.format(s_device), '-dFirstPage={}'.format(t_name), '-dLastPage={}'.format(t_name),
                    '-r200', '-dPDFSETTINGS=/prepress', '-dDownScaleFactor=2',
                    '-o', image_path, '-f', str(pdf_file),
                    '-c', '{}'.format(current_app.conf.get("GHOST_MEMORY") / current_app.conf.get("THREAD_NUM")),
                ])

            pool.makeInactive(t_name)
    except Exception as error:
        traceback.print_exc()
        return 0
    return 1

def add_pages(xml_data, num_pages):
    logging.info('Calling add_pages API ...')
    # Call to AddPages API
    pdf_name = xml_data['pdf_name']
    sub_path = '{}/{}/'.format(
        xml_data['box_number'],
        xml_data['box_part']
    )
    pages = []
    for i in range(num_pages):
        pages.append({
            'path': sub_path + '{}_{}.pdf'.format(pdf_name, format(int(i + 1), "06")),
            'version': str(i + 1)
        })
    data_json = {
        'bookmark_process_queue_id': str(xml_data['bookmark_id']),
        'pages': pages,
    }
    logging.info('Calling to add_pages api with payload: {}'.format(data_json))
    result = call_to_esd_api('add_pages', 1, data_json)
    if result.get('code', 0):
        logging.info("Call add_pages API success!")
        return 1
    return 0

def sync_updatebpq(pool, pdf_file, xml_data, dir, num_pages, have_ocr, have_sphinx):
    '''
    Rsync all files after processing (pngs, thumbs, original pdf file, pdfs + xml if have ocr process) to server
    and call to update_bpq_as_processed API
    :param pool: using for semaphore threads
    :param pdf_file: path of pdf file
    :param xml_data: data for generating xml file
    :param dir:
    :param num_pages: number pages of pdf file
    :param have_ocr: if have ocr process
    :return:
        None
    '''
    # Check all things is ok?
    logging.info('Checking files has been generated ...')
    _time = 0
    while not is_finish(dir, num_pages, have_ocr, have_sphinx):
        _time = _time + 1
        if _time >= current_app.conf.get("TIMEOUT"):
            logging.error('Time out when processing ORC')
            return {}
        time.sleep(_time)

    sub_path = '{}/{}/'.format(
        xml_data['box_number'],
        xml_data['box_part'],
    )
    dest_path = xml_data['pkged'] + '/' + sub_path

    # Create new folder if it doesn't exist on server
    s_mkdir_command = 'ssh {}@{} "mkdir -p {}"'.format(current_app.conf.get('UPLOAD_USER'), current_app.conf.get('UPLOAD_SERVER'), dest_path)
    os.system(s_mkdir_command)

    # Change the Oops iamge
    change_opp_image(dir, pdf_file)

    # Rsysn all files on server
    rsync_command = 'rsync -avz --exclude {} --exclude {} {} {}'.format(
        'temp/',
        #os.path.basename(pdf_name),
        'xml_data.txt',
        dir + '/*',
        '{}@{}:{}'.format(current_app.conf.get("UPLOAD_USER"), current_app.conf.get("UPLOAD_SERVER"), dest_path)
    )
    logging.info ('rsync command is: {}'.format(rsync_command))

    _time = 0
    sync_success = False
    while (True):
        if _time > 3:
            break
        error = os.system(rsync_command)
        if not error:
            sync_success = True
            break
        _time = _time + 1
        time.sleep(_time)
    # Call to update_bpq_as_processed API
    if sync_success:
        logging.info('Sync files to {} success.'.format(current_app.conf.get("UPLOAD_SERVER")))
        data_json = {
            'bookmark_process_queue_id': str(xml_data['bookmark_id']),
            'processed': 'true',
            #'synced': 'false'
        }
        result = call_to_esd_api('update_bpq_as_processed', 1, data_json)
        if result.get('code', 0):
            logging.info("Call update_bpq_as_processed API success!")
            shutil.rmtree(dir) #for testing
        else:
            logging.error("Call update_bpq_as_processed API failed with data json %s" % (data_json))
            #it will process again
    else:
        logging.error('Couldn\'t sync files to {}: Conection timed out!'.format(current_app.conf.get("UPLOAD_SERVER")))


def generate_xml(dir, xml_data, num_pages):
    '''
    Generating XML file after ocring pdf file
    :param dir:
    :param xml_data: data for generating xml file
    :param num_pages: number pages of pdf file
    :return:
        - None
    '''
    now = datetime.datetime.now()
    # Create the root element
    file_info = etree.Element('FileInfo', process_date="{}/{}/{}".format(now.day, now.month, now.year), profile_id=xml_data['profile_id'])
    # Make a new document tree
    doc = etree.ElementTree(file_info)
    # Add the subelements
    imageElement = etree.SubElement(file_info, 'Image', id=xml_data['image_id'])
    bookmarkElement = etree.SubElement(imageElement, 'Bookmark', ID=xml_data['bookmark_id'])
    for i in range(1, num_pages + 1):
        pieceElement = etree.SubElement(bookmarkElement, 'piece',
                                        path="{}/{}/{}_{}.pdf".format(
                                            xml_data['box_number'],
                                            xml_data['box_part'],
                                            xml_data['pdf_name'],
                                            format(int(i), "06"),
                                        ))
    with open('{}/{}.xml'.format(dir, xml_data['box_part']), 'w') as f:
        doc.write(f, xml_declaration=True, encoding='utf-8', pretty_print=True)

def is_finish(dir, num_pages, have_ocr, have_sphinx):
    '''
    Checking everything is finished?
    :param dir:
    :param num_pages: number pages of pdf file
    :param have_ocr: if have ocr process
    :return:
        -0: failed
        -1: success
    '''
    try:
        thumbs_dir = dir + '/thumbs'
        png_dir = dir + '/png'
        sph_dir = dir + '/xml'
        if have_ocr and have_sphinx:
            if (len([name for name in os.listdir(dir) if os.path.isfile(os.path.join(dir, name))]) == num_pages + 3) and (
                len([name for name in os.listdir(thumbs_dir) if os.path.isfile(os.path.join(thumbs_dir, name))]) == num_pages) and (
                len([name for name in os.listdir(png_dir) if os.path.isfile(os.path.join(png_dir, name))]) == num_pages) and (
                len([name for name in os.listdir(sph_dir) if os.path.isfile(os.path.join(sph_dir, name))]) == num_pages):
                return 1
        elif have_ocr and not have_sphinx:
            if (len([name for name in os.listdir(dir) if os.path.isfile(os.path.join(dir, name))]) == num_pages + 3) and (
                len([name for name in os.listdir(thumbs_dir) if os.path.isfile(os.path.join(thumbs_dir, name))]) == num_pages) and (
                len([name for name in os.listdir(png_dir) if os.path.isfile(os.path.join(png_dir, name))]) == num_pages):
                return 1
        elif not have_ocr and have_sphinx:
            # Don't have xml file
            if (len([name for name in os.listdir(dir) if os.path.isfile(os.path.join(dir, name))]) == num_pages + 2) and (
                len([name for name in os.listdir(thumbs_dir) if os.path.isfile(os.path.join(thumbs_dir, name))]) == num_pages) and (
                len([name for name in os.listdir(png_dir) if os.path.isfile(os.path.join(png_dir, name))]) == num_pages) and (
                len([name for name in os.listdir(sph_dir) if os.path.isfile(os.path.join(sph_dir, name))]) == num_pages):
                return 1
        else:
            # Don't have xml file
            if (len([name for name in os.listdir(dir) if os.path.isfile(os.path.join(dir, name))]) == num_pages + 2) and (
                len([name for name in os.listdir(thumbs_dir) if os.path.isfile(os.path.join(thumbs_dir, name))]) == num_pages) and (
                len([name for name in os.listdir(png_dir) if os.path.isfile(os.path.join(png_dir, name))]) == num_pages):
                return 1
        return 0
    except Exception as error:
        traceback.print_exc()
        return 0

def extract_text_from_pdf(s, pool, pdf_name, num_pages, dir, re_extract=None):
    '''
    Extract text from pdf if we don't need ocr process
    :param s: using for semaphore threads
    :param pool: using for semaphore threads
    :param pdf_file: path of pdf file
    :param num_pages: number pages of pdf file
    :param dir:
    :return:
        - None
    '''
    try:
        if num_pages:
            have_ocr = False
            have_sphinx = True
            temp_folder = dir + '/{}'.format('temp')
            if not os.path.exists(temp_folder):
                mkdir_command = 'mkdir %s -p' % temp_folder
                os.system(mkdir_command)
            if re_extract:
                # Run extract text again if the error has occurred
                for i, val in enumerate(re_extract):
                    t = threading.Thread(target=_ocr_pdf_or_extract_text_only, name=str(val),
                                         args=(s, pool, pdf_name, dir, have_ocr, have_sphinx))
                    t.daemon = True
                    t.start()
            else:
                for i in range(num_pages):
                    t = threading.Thread(target=_ocr_pdf_or_extract_text_only, name=str(i + 1),
                                         args=(s, pool, pdf_name, dir, have_ocr, have_sphinx))
                    t.daemon = True
                    t.start()

    except Exception as error:
        traceback.print_exc()

def create_sphinx_file(s, pool, num_pages, dir, pdf_name):
    try:
        xml_folder = dir + '/{}'.format('xml')
        if not os.path.exists(xml_folder):
            mkdir_command = 'mkdir %s -p' % xml_folder
            os.system(mkdir_command)
        mxt = current_app.conf.get("THREAD_NUM") * 2
        for i in range(num_pages):
            t = threading.Thread(target=_create_sphinx_file, name=str(i + 1),
                                 args=(s, pool, xml_folder, pdf_name))
            t.daemon = True
            t.start()
            if (i + 1) % mxt == 0:
                t.join()
    except Exception as error:
        traceback.print_exc()
        return 0

def _create_sphinx_file(s, pool, xml_folder, pdf_name):
    try:
        with s:
            dir = xml_folder.rsplit('/', 1)[0]
            t_name = threading.currentThread().getName()
            pool.makeActive(t_name)
            temp_text_path  = '{}/temp/{}_{}.text'.format(dir, pdf_name, format(int(t_name), "06"))
            sph_path        = '{}/xml/{}_{}.sph'.format(dir, pdf_name, format(int(t_name), "06"))

            #check file here,
            _time = 0
            while not os.path.exists(temp_text_path):
                _time = _time + 1
                if _time == current_app.conf.get("TIMEOUT"):
                    return 0  # timeout
                time.sleep(_time)

            # Read text file from temporary text file
            with open(temp_text_path, 'rb') as f:
                text = f.read()
            template = '''<h1></h1><h2></h2><h3></h3><h4>%s</h4>'''
            text_makeup = text.replace('\n', ' ')
            with open(sph_path, 'w') as f:
                f.write(template %(text_makeup))
    except Exception as error:
        traceback.print_exc()

def previous_and_next(some_iterable):
    # Following to: http://stackoverflow.com/questions/1011938/python-previous-and-next-values-inside-a-loop
    prevs, items, nexts = tee(some_iterable, 3)
    prevs = chain([None], prevs)
    nexts = chain(islice(nexts, 1, None), [None])
    return izip(prevs, items, nexts)

def hash_pdf_name(barcode):
    '''
    hashing the name of pdf file (without barcode) after splitting and merging
    input:
        - video_name: the path of video
    returns the hash string
    '''
    hash = hashlib.md5()
    hash.update(barcode + str(datetime.datetime.now()))
    return hash.hexdigest() + '_' + str(randint(1000000000, 9999999999))

def sslwrap(func):
    '''
    Following to http://stackoverflow.com/questions/14102416/python-requests-requests-exceptions-sslerror-errno-8-ssl-c504-eof-occurred/14146031
    :param func:
    :return:
    '''
    @wraps(func)
    def bar(*args, **kw):
        kw['ssl_version'] = ssl.PROTOCOL_TLSv1
        return func(*args, **kw)
    return bar

def change_opp_image(dir, original_pdf_path):
    '''
    Change the Oops image When the PDF is larger that 1800 width
    Following by ticket: http://cmos.neuone.com:8080/browse/NR-42
    :param dir:
    :param original_pdf_path:
    :return:
        1: success
        0: failed
    '''
    # Get width from pdf file
    pdf_list = glob.glob('{}/*.pdf'.format(dir))
    for pdf_path in pdf_list:
        if pdf_path != original_pdf_path:
            width = get_width(pdf_path)
            if width > 1800:
                logging.info('Oops, this image is too large to display!')
                oops_image_path     = current_app.conf.get("OOPS_DIR") + "/dummy.png"
                try:
                    file_name_without_ext = os.path.basename(pdf_path).split('.')[0]
                except:
                    return 0
                png_image_path      = '{}/png/{}.png'.format(dir, file_name_without_ext)
                thumbs_image_path   = '{}/thumbs/{}.png'.format(dir, file_name_without_ext)
                _time = 0
                while (True):
                    if os.path.exists(png_image_path) and os.path.exists(thumbs_image_path):
                        break
                    else:
                        time.sleep(_time)
                    if _time >= current_app.conf.get("TIMEOUT"):
                        logging.error('The process has been cancelled.')
                        return 0  # timeout
                    _time = _time + 1
                cp_cm = "cp -r {} {} && cp -r {} {}".format(oops_image_path, png_image_path, oops_image_path, thumbs_image_path)
                os.system(cp_cm)
                return 1

@signals.worker_process_init.connect
def worker_process_init(**kwargs):
    '''
    If ocr process have been failed (signal 6, 11), this function will run ocr again.
    :param kwargs:
    :return:
        - None
    '''
    logging.disable(logging.NOTSET)
    logging.info('Worker is starting ...')
    try:
        pool = ThreadPool()
        s = threading.Semaphore(current_app.conf.get("THREAD_NUM"))

        # is_bulk = false
        non_bulk_dir = current_app.conf.get("TMP_DIR_NON_BULK")
        dirs = os.walk(non_bulk_dir)
        for item in dirs:
            #read data_xml from this folder
            if len(item[1]):
                sub_folders = item[1] #item[1][0]
                for sub_folder in sub_folders:
                    xml_data_path = non_bulk_dir + '/{}/{}'.format(sub_folder, 'xml_data.txt')
                    temp_path = non_bulk_dir + '/{}/{}'.format(sub_folder, 'temp')
                    xml_data = None
                    if os.path.exists(xml_data_path):
                        with open(xml_data_path, 'rb') as f:
                            xml_data = json.loads(f.read().replace('\'', '"'))

                    if xml_data:
                        pdf_file = non_bulk_dir + '/{}/{}.pdf'.format(sub_folder, xml_data['pdf_name'])
                        num_pages = 0
                        with open(pdf_file, 'rb') as f:
                            pdf_input = PdfFileReader(f, strict=False)
                            num_pages = pdf_input.getNumPages()
                        dir = non_bulk_dir + '/{}'.format(sub_folder)

                        have_ocr = xml_data.get('have_ocr', 'f')
                        if have_ocr == 'f':
                            have_ocr = False
                        else:
                            have_ocr = True

                        have_sphinx = xml_data.get('have_sphinx', 'f')
                        if have_sphinx == 'f':
                            have_sphinx = False
                        else:
                            have_sphinx = True

                        _add_pages = xml_data.get('add_pages', 'f')
                        if _add_pages == 'f':
                            _add_pages = False
                        else:
                            _add_pages = True

                        if os.path.exists(temp_path): # have_sphinx: false or true, have_ocr: false or true
                            # Orcing pdf file again

                            if num_pages:
                                for i in range(num_pages):
                                    if have_ocr:
                                        searchable_pdf = non_bulk_dir + '/{}/{}_{}.pdf'.format(sub_folder,
                                                                                               xml_data['pdf_name'],
                                                                                               format(i + 1, "06"))
                                        if os.path.exists(searchable_pdf):
                                            continue
                                        ocr_pdf(s, pool, pdf_file, num_pages, dir, xml_data, have_sphinx, reocr_pages=range(i + 1, num_pages + 1))
                                        if have_sphinx:
                                            create_sphinx_file(s, pool, num_pages, dir, xml_data['pdf_name'])
                                    else:
                                        text_file = non_bulk_dir + '/{}/{}/{}_{}.text'.format(sub_folder, 'temp',
                                                                                            xml_data['pdf_name'],
                                                                                            format(i + 1, "06"))
                                        if os.path.exists(text_file):
                                            continue

                                        extract_text_from_pdf(s, pool, xml_data['pdf_name'], num_pages, dir, re_extract=range(i + 1, num_pages + 1))
                                        create_sphinx_file(s, pool, num_pages, dir, xml_data['pdf_name'])
                                    # sync_updatebpq(pool, pdf_file, xml_data, dir, num_pages, have_ocr,
                                    #                                  have_sphinx)
                                    break
                        else: #have_sphinx: false, have_ocr: false
                            have_ocr    = False
                            have_sphinx = False
                        if not _add_pages:
                            if add_pages(xml_data, num_pages):
                                xml_data['add_pages'] = "t"
                                with open(dir + '/xml_data.txt', "wb") as f:
                                    f.write(str(xml_data))
                            else:
                                logging.error('Calling to add_pages api failed with xml data: {}'.format(xml_data))
                                return {}
                        sync_updatebpq(pool, pdf_file, xml_data, dir, num_pages, have_ocr,
                                               have_sphinx)
                        logging.info('Process non bulk with bookmark_id {} success'.format(str(xml_data.get('bookmark_id', ''))))

            break

        bulk_dir = current_app.conf.get("TMP_DIR_BULK")
        dirs = os.walk(bulk_dir)
        for item in dirs:
            # read data_xml from this folder
            if len(item[1]):
                sub_folders = item[1]  # item[1][0]
                for sub_folder in sub_folders:
                    data_path = bulk_dir + '/{}/{}'.format(sub_folder, 'data.txt')
                    data = None
                    if os.path.exists(data_path):
                        with open(data_path, 'rb') as f:
                            temp = f.read().replace('\'', '"')
                            data = json.loads(temp)
                    if data:

                        if data.get('keep_barcode_ind', 't') == 't':
                            keep_barcode_ind = True
                        else:
                            keep_barcode_ind = False

                        pdf_file = bulk_dir + '/{}/{}'.format(sub_folder, data['pdf_name'])
                        num_pages = 0
                        with open(pdf_file, 'rb') as f:
                            pdf_input = PdfFileReader(f, strict=False)
                            num_pages = pdf_input.getNumPages()
                        process_barcode(pool, s, pdf_file, num_pages, data.get('scannedimages_path', None), data.get('queue_id', None), keep_barcode_ind, data.get('priority', current_app.conf.get("PRIORITY_ID")), data.get('tasks'))

    except Exception as error:
        traceback.print_exc()
        return 0
    return 1
