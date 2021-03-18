#!/usr/bin/python
import os
import sys
import threading
import datetime
import logging
import os.path
from PyPDF2 import PdfFileWriter, PdfFileReader, PdfFileMerger
import traceback
from slugify import slugify
import subprocess
from PIL import Image
from asprise_ocr_api import *
import signal
import time
import random
from datetime import datetime
import shutil
import pdftotext
import re
import codecs
from xml.etree import ElementTree as et
import fnmatch

# pip install -t /project/env/lib/python2.7/dist-packages Pillow==4.0.0
# go to project and run this command: cp /ai/PDF-OCR-RTP/libs/asprise_lib/__init__.py env/lib/python2.7/dist-packages/asprise_ocr_api/
# Install gs
# Remember: install tesseract before running this tool
# env/lib/python2.7/site-packages/asprise_ocr_api/lib/libaocr_x64.so


params = sys.argv
# Setting configure
ghost_script = '/project/lib/ghost_script/bin/gs'
ghost_memory = 300000
timeout = 3
# python ocr_asprise.py file-ext=pdf output-type=TEXT-PDF source-path="/source/path" target-path="/target/path"  output-log=output_log.txt rotate=false --help

# !/usr/bin/env python

# set variable
# thread_number = 1
source_path = ''
output_log = ''
target_path = ''
output_type = None
rotate = None


def sig_handler(signum, frame):
    print "Segmentation fault occurred"
    os.abort()


signal.signal(signal.SIGSEGV, sig_handler)


class ThreadPool(object):
    '''
    Create thread pool
    Folling by: http://www.bogotobogo.com/python/Multithread/python_multithreading_Synchronization_Semaphore_Objects_Thread_Pool.php
    '''

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


def get_thread_number_by_server_cores():
    '''
    Get thread number by the number of cores CPU
    :return:
    '''
    import multiprocessing
    thread_number = multiprocessing.cpu_count() - 1 if multiprocessing.cpu_count() > 1 else multiprocessing.cpu_count()
    # thread_number = 100 # for testing
    return thread_number


def show_help_syntax():
    '''
    Show the syntax command to ocr.
    :return:
        None
    '''
    print '\n'
    print 'Following by syntax: python ocr_asprise.py file-ext=pdf output-type=TEXT-PDF source-path="/source/path" target-path="/target/path"  output-log=output_log.txt rotate=false --help'
    print '\n'
    print 'ocr_asprise.py: the name of the tool'
    print 'file-ext: file extension that you will crawl through to OCR'
    print 'output-type: there are 3 options here: TEXT (output textfile only), TEXT-PDF (output textfile and PDF), PDF  (output PDF only)'
    print 'source-path: source where the directory you will need to crawl'
    print 'target-path: where you will save the output, keep structure the same'
    print 'output-log: path to output files'
    print 'rotate: auto rotate the output true/false default false'


def get_params():
    '''
    Get all parameters from the command line
    :return:
        1   : success
        0   : Use help param
        -1  : something went wrong or lack some params
    '''
    required_params = ['file-ext', 'output-type', 'source-path', 'target-path', 'output-log']
    p_dic = {}
    if '--help' in params:
        show_help_syntax()
        return {'code': 0, 'data': None}
    else:
        print 'params is: {}'.format(params)
        for p in params:
            values = p.split('=')
            try:
                key = values[0]
                value = values[1]
                p_dic[key] = value
                show_syntax = False

                if key == 'output-log':
                    output_path = os.path.dirname(value)
                    if not os.path.exists(output_path):
                        # show_syntax = True
                        logging.info('Create new output dir: {}'.format(output_path))
                        mkdir_cm = 'mkdir -p {}'.format(output_path)
                        os.system(mkdir_cm)
                if key == 'source-path':
                    if not os.path.exists(value):
                        show_syntax = True
                if key == 'target-path':
                    if not os.path.exists(value):
                        logging.info('Create new target-path: {}'.format(value))
                        mkdir_cm = 'mkdir -p {}'.format(value)
                        os.system(mkdir_cm)
                if show_syntax:
                    print 'The path {} does not exist. Please check it again'.format(key)
                    return {'code': -1, 'data': None}

            except:
                show_help_syntax()
                pass
        if set(required_params) < set(p_dic.keys()):
            return {'code': 1, 'data': p_dic}
        else:
            return {'code': -1, 'data': None}


def get_number_of_pages(file_path):
    '''
    Get number of pages pdf
    :param file_path:
    :return:
        0: something went wrong
        number of pages: success
    '''
    num_pages = 0
    with open(file_path, 'rb') as f:
        try:
            pdf_input = PdfFileReader(f, strict=False)
            num_pages = pdf_input.getNumPages()
        except:
            logging.error('The file {} can\'t get number of pages.'.format(files_path))
            pass
    return num_pages


def convert_pdf_to_txt(path):
    '''
    Checking if a pdf is a non searchable
    Following by: https://github.com/jalan/pdftotext
    :param path: the path point to input file
    :return:
        1: is searachable
        0: non searchable
    '''
    with open(path, "rb") as f:
        pdf = pdftotext.PDF(f)
    text = "\n\n".join(pdf)
    # Read all the text into one string

    tmp_text = re.sub('[^A-Za-z ]+ ', '@', text).replace(' ', '')
    if tmp_text.strip():
        special_character_number = len(re.findall('\@', tmp_text))
        if special_character_number / float(len(tmp_text)) > 0.5:
            return {'code': 0, 'text': ''}
        return {'code': 1, 'text': text.strip()}
    return {'code': 0, 'text': ''}


def detect_orientation(image_path):
    def execute_and_rotate_image(cmd):
        from subprocess import Popen, PIPE, STDOUT
        popen = Popen(cmd, stderr=STDOUT, stdout=PIPE, shell=False)
        out = popen.communicate()[0]
        if 'Orientation in degrees:' in out:
            try:
                degrees = int(out.split('Orientation in degrees:', 1)[1].split('\n', 1)[0].strip())
            except Exception as error:
                traceback.print_exc()
                degrees = 0

            if degrees == 180:
                # Rotate all images correctly
                logging.info('The image {} will be rotate {} degree'.format(image_path, degrees))
                # Load the original image:
                img = Image.open(image_path)
                img2 = img.rotate(degrees)
                img2.save(image_path)

        popen.stdout.close()
        # return_code = popen.wait()

    execute_and_rotate_image(
        ['tesseract', image_path, '-', '-psm', '0']
    )


def write_log(log_file, search_file, status, error_message=''):
    '''
    Write the logs to log file
    :param log_file:
    :param search_file:
    :param status:
        1: success
        0: blank
        -1: failed
    :return:
        None
    '''
    timestamp = str(datetime.now())
    if status == 1:
        status = 'SUCCESS'
    elif status == 0:
        status = 'BLANK'
    else:
        status = 'ERROR'
    with open(log_file, 'a') as f:
        log = '[{}][{}][{}]: {}'.format(timestamp, status, error_message, search_file)
        f.write(log)
        f.write('\n')


def is_finish(dir, num_pages, ocr_type):
    '''
    Checking everything is finished?
    :param dir:
    :param num_pages: number pages of pdf file
    :param ocr_type:
        0:PDF,
        1:PDF-TEXT,
        2:TEXT
        -1: XML
    :return:
        -0: failed
        -1: success
    '''
    try:
        if ocr_type == -1:
            number_of_file_xml = len(fnmatch.filter(os.listdir(dir), '*.xml'))
            if number_of_file_xml == num_pages:
                return 1
            return 0
        else:
            number_of_file_pdf = len(fnmatch.filter(os.listdir(dir), '*.pdf'))
            number_of_file_txt = len(fnmatch.filter(os.listdir(dir), '*.txt'))
            if ocr_type == 1:
                if (number_of_file_pdf + number_of_file_txt) == num_pages * 2:
                    return 1
            else:
                if (number_of_file_pdf + number_of_file_txt) == num_pages:
                    return 1
        return 0

    except Exception as error:
        traceback.print_exc()
        return 0

def check_ocr_is_finish_by_file_path(file_name, dest_path, output_type):
    '''
    Check if the file has ocred or not?
    :param file_name: the name of input file
    :param dest_path:
    :param output_type:
    :return:
        True: has ocred
        False: not finised yet
    '''
    try:
        _output_type = output_type.lower().split('-')
    except:
        pass

    for o in _output_type:
        if o == 'text':
            o = 'txt'
        if not os.path.exists('{}/{}.{}'.format(dest_path, file_name, o)):
            return False
        return True

def get_orc_engine_instance():
    try:
        Ocr.input_license("ent_SINGLE_2_Seats-Neubus-OS202800000800", "93513-5B34F-32BA4-FF1E4")
        Ocr.set_up()  # one time setup
        ocrEngine = Ocr()
        ocrEngine.start_engine("eng")
        return ocrEngine
    except:
        traceback.print_exc()
        return None


def combine_xml(files):
    '''
    Merge all xml files
    :param files: list of xml file path
    :return:
        XML file
    '''
    first = None
    for filename in files:
        data = et.parse(filename).getroot()
        if first is None:
            first = data
        else:
            first.extend(data)
    if first is not None:
        return et.tostring(first)

def _process_xml(s, pool, fp, xml_out):
    '''
    Threading for processing xml when pdf file is a searchable pdf
    :param s:
    :param pool:
    :param fp: path of input pdf file
    :param xml_out: path of file xml
    :return:
        - None
    '''
    with s:
        t_name = threading.currentThread().getName()
        pool.makeActive(t_name)
        try:
            from multiprocessing.pool import ThreadPool
            _pool = ThreadPool(processes=1)
            async_result = _pool.apply_async(get_orc_engine_instance, ())
            ocrEngine = async_result.get()
            if not ocrEngine:
                logging.error('Can\'t create new OCR engine instance.')
                return 0
            xml_data = ocrEngine.recognize(fp, -1, -1, -1, -1, -1,
                                           OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_XML,
                                           PROP_IMG_PREPROCESS_TYPE='custom')
            with codecs.open(xml_out, "w", encoding="utf-8") as f:
                f.write(xml_data)
            write_log(output_log, xml_out, 1)
        except Exception as error:
            traceback.print_exc()
            write_log(output_log, xml_out, -1, str(error))
        pool.makeInactive(t_name)

def _ocr_process_by_png_file(s, pool, fp, tmp_dir, pdf_name, output_type, output_log, number_of_pages, rotate=False,
                 delete_temp=False):
    '''
    Implement ocr for threading by png files
    Following by: https://stackoverflow.com/questions/13657341/how-do-i-append-new-data-to-existing-xml-using-python-elementtree
    :param s: threading use semaphore technique
    :param pool: number of threads that run at a same time.
    :return:
        1: success
        0: failed
    '''
    try:
        _output_type = output_type.lower().split('-')
    except:
        pass
    _time = 0
    while (True):
        try:
            if _time > timeout:
                logging.error('Something went wrong with pdf file: {}'.format(pdf_name))
                return 0
            with s:
                t_name = threading.currentThread().getName()
                pool.makeActive(t_name)

                # Code here
                temp_image_path = '{}/{}_{}.png'.format(tmp_dir, pdf_name, format(int(t_name), "06"))
                searchable_pdf_path = '{}/{}_{}.pdf'.format(tmp_dir.rsplit('/', 1)[0], pdf_name,
                                                            format(int(t_name), "06"))
                searchable_txt_path = '{}/{}_{}.txt'.format(tmp_dir.rsplit('/', 1)[0], pdf_name,
                                                            format(int(t_name), "06"))
                tmp_xml_path = '{}/{}_{}.xml'.format(tmp_dir.rsplit('/', 1)[0], pdf_name, format(int(t_name), "06"))

                _time = 0
                while not os.path.exists(temp_image_path):
                    _time = _time + 1
                    if _time == timeout:
                        return 0  # timeout
                    time.sleep(_time)

                # Following by: https://tpgit.github.io/Leptonica/readfile_8c_source.html
                if os.stat(temp_image_path).st_size < 20:
                    time.sleep(1)

                print ('Ocring pdf file is starting ... File path: %s' % searchable_pdf_path)
                from multiprocessing.pool import ThreadPool
                _pool = ThreadPool(processes=1)
                async_result = _pool.apply_async(get_orc_engine_instance, ())
                ocrEngine = async_result.get()
                if not ocrEngine:
                    logging.error('Can\'t create new OCR engine instance.')
                    return 0
                xml_data = None

                if rotate:
                    detect_orientation(temp_image_path)
                    ocr_type = 0
                time.sleep(random.uniform(0.1, 1.1))

                if 'xml' in _output_type:
                    ocr_type = -1
                    xml_data = ocrEngine.recognize(temp_image_path, -1, -1, -1, -1, -1,
                                                   OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_XML,
                                                   PROP_IMG_PREPROCESS_TYPE='custom',
                                                   PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()")
                    # Create xml file here

                    try:
                        xml_data = xml_data.replace('no="0"', 'no="{}"'.format(int(t_name) - 1))
                        if int(t_name) == 1:
                            xml_data = xml_data.replace(str(temp_image_path), str(fp))
                        with codecs.open(tmp_xml_path, "w", encoding="utf-8") as f:
                            f.write(xml_data)
                        write_log(output_log, tmp_xml_path, 1)
                    except Exception as error:
                        traceback.print_exc()
                        write_log(output_log, tmp_xml_path, -1, str(error))
                    if delete_temp:
                        xml_flag = True
                        _time_fs = 0
                        while not is_finish(tmp_dir.rsplit('/', 1)[0], number_of_pages, ocr_type):
                            _time_fs = _time_fs + 1
                            if _time_fs >= timeout * 5:
                                logging.error('Time out when processing ORC')
                                xml_flag = False
                            time.sleep(_time_fs)

                        tmp_xml_list = [
                            '{}/{}_{}.xml'.format(tmp_dir.rsplit('/', 1)[0], pdf_name, format(int(i + 1), "06")) for i
                            in range(number_of_pages)]
                        final_xml_data = combine_xml(tmp_xml_list)
                        if xml_flag:
                            try:
                                final_xml_path = '{}/{}.xml'.format(tmp_dir.rsplit('/', 2)[0], pdf_name)
                                with codecs.open(final_xml_path, "w", encoding="utf-8") as f:
                                    f.write(final_xml_data)
                                write_log(output_log, final_xml_path, 1)
                            except Exception as error:
                                traceback.print_exc()
                                write_log(output_log, final_xml_data, -1, str(error))
                        else:
                            logging.ERROR('Can\'t create XML file, timeout occurred while waiting to merge xml file')
                            write_log(output_log, final_xml_data, -1, str(error))

                if 'text' in _output_type and 'pdf' in _output_type:
                    ocr_type = 1
                    ocr_data = ocrEngine.recognize(temp_image_path, -1, -1, -1, -1, -1,
                                                   OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PDF,
                                                   PROP_PDF_OUTPUT_FILE=searchable_pdf_path,
                                                   PROP_PDF_OUTPUT_RETURN_TEXT='text',
                                                   PROP_IMG_PREPROCESS_TYPE='custom',
                                                   PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()",
                                                   PROP_PDF_OUTPUT_TEXT_VISIBLE=False)

                    # Create text file here
                    try:
                        with codecs.open(searchable_txt_path, "w", encoding="utf-8") as f:
                            f.write(ocr_data)
                        write_log(output_log, searchable_txt_path, 1)
                        write_log(output_log, searchable_pdf_path, 1)
                    except Exception as error:
                        write_log(output_log, searchable_txt_path, -1, str(error))
                        write_log(output_log, searchable_pdf_path, -1, str(error))

                elif 'pdf' in _output_type:
                    ocr_type = 2
                    try:
                        ocrEngine.recognize(temp_image_path, -1, -1, -1, -1, -1,
                                            OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PDF,
                                            PROP_PDF_OUTPUT_FILE=searchable_pdf_path,
                                            PROP_PDF_OUTPUT_RETURN_TEXT='text',
                                            PROP_IMG_PREPROCESS_TYPE='custom',
                                            PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()",
                                            PROP_PDF_OUTPUT_TEXT_VISIBLE=False, )
                        # Write the result to the log file
                        write_log(output_log, searchable_pdf_path, 1)
                    except Exception as error:
                        write_log(output_log, searchable_pdf_path, -1, str(error))
                elif 'text' in _output_type:
                    ocr_type = 3
                    ocr_data = ocrEngine.recognize(temp_image_path, -1, -1, -1, -1, -1,
                                                   OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PLAINTEXT,
                                                   PROP_IMG_PREPROCESS_TYPE='custom',
                                                   PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()")
                    # Create text file here
                    try:
                        with open(searchable_txt_path, 'w') as f:
                            ocr_data = u''.join(ocr_data).encode('utf-8').strip()
                            f.write(ocr_data)
                        write_log(output_log, searchable_txt_path, 1)
                    except Exception as error:
                        write_log(output_log, searchable_pdf_path, -1, str(error))

                ocrEngine.stop_engine()

                if delete_temp:
                    _time_fs = 0
                    while not is_finish(tmp_dir.rsplit('/', 1)[0], number_of_pages, ocr_type):
                        _time_fs = _time_fs + 1
                        if _time_fs >= timeout * 5:
                            logging.error('Time out when processing ORC')
                            return 0
                        time.sleep(_time_fs)

                    src_path = tmp_dir.rsplit('/', 1)[0]
                    dest_path = tmp_dir.rsplit('/', 2)[0]
                    merge_pdf_pages_and_text_file(src_path, dest_path, pdf_name)

                    # Remove tmp forder
                    logging.info('Remove the directory: {}'.format(tmp_dir))
                    shutil.rmtree(tmp_dir.rsplit('/', 1)[0])

                pool.makeInactive(t_name)
                return 1
        except Exception as error:
            traceback.print_exc()
            # Write the result to the log file
            write_log(output_log, searchable_pdf_path, -1, str(error))
            pass
        _time = _time + 1


def merge_pdf_pages_and_text_file(src_path, dest_path, pdf_name):
    '''
    Appending PDF files | text files to new one.
    :param src_path:
    :param dest_path:
    :param pdf_name:
    :return:
    '''
    # Merge pdf pages
    merger = PdfFileMerger()
    pdf_pages = []
    for dirpath, dirnames, filenames in os.walk(src_path):
        for filename in [f for f in filenames if f.endswith(".pdf")]:
            pdf_pages.append(os.path.join(dirpath, filename))
    if pdf_pages:
        pdf_pages.sort()
        for _file in pdf_pages:
            print ('_file pdf is: {}'.format(_file))
            merger.append(PdfFileReader(file(_file, 'rb')))
        merger.write('{}/{}.pdf'.format(dest_path, pdf_name))

    # Merges txt pages
    txt_pages = []
    for dirpath, dirnames, filenames in os.walk(src_path):
        for filename in [f for f in filenames if f.endswith(".txt")]:
            txt_pages.append(os.path.join(dirpath, filename))
    if txt_pages:
        txt_pages.sort()
        for _file in txt_pages:
            content = ''
            print ('_file txt is: {}'.format(_file))
            try:
                with open(_file) as f:
                    content = str(f.readlines())
            except:
                logging.warning('Can\'t not get content of file: {}'.format(_file))
                pass
            if content:
                with open('{}/{}.txt'.format(dest_path, pdf_name), 'a') as myfile:
                    myfile.write(u''.join(content).encode('utf-8').strip())


def run_tracking_file(output_type, source_path, target_path, output_log, rotate, ocr_all):
    '''
    Run tracking file
    :param output_type:
    :param source_path:
    :param target_path:
    :param output_log:
    :param rotate:
    :param ocr_all:
    :return:
    '''
    # Get current path:
    current_path = os.path.dirname(os.path.abspath(__file__))
    # Start tracking file to monitor the OCR tool
    try:
        # Checking if the Asprise lib get stuck
        pid = os.getpid()
        file_ext = 'pdf'

        run_tracking_cm = 'python {}/tracking.py {} {} {} {} {} {} {} {}'.format(
            current_path,
            pid,
            file_ext,
            output_type,
            source_path,
            target_path,
            output_log,
            rotate,
            ocr_all,
        ).split(' ')
        # os.system(run_tracking_cm)
        from subprocess import call
        call(run_tracking_cm)
    except:
        traceback.print_exc()
        return 0
    return 1

def orc_process(s, pool, files_path, source_path, target_path, output_type, output_log, rotate=False, ocr_all=False):
    '''
    Implement orc process
    :param s: threading use semaphore technique
    :param pool: number of threads that run at a same time.
    :param files_path: path of all files in the source directory
    :param target_path: path of directory which contains all output files
    :param output_log: path of dirctory which contains the log file
    :param rotate: auto rotate the output true/false default false
    :return:
        None
    '''

    tracking_thread = threading.Thread(target=run_tracking_file, args=(output_type, source_path, target_path, output_log, rotate, ocr_all,))
    tracking_thread.daemon = True
    tracking_thread.start()

    orc_list = []
    for fp in files_path:
        print ('\n')
        print ('File path is: {}'.format(fp))
        number_of_pages = get_number_of_pages(fp)
        images_list = []
        if number_of_pages:
            file_name = os.path.basename(fp).rsplit('.pdf', 1)[0]
            dir = os.path.dirname(fp)
            sub_dir = dir.split(source_path)[1].strip('/')
            convert = convert_pdf_to_txt(fp)

            if check_ocr_is_finish_by_file_path(file_name, '/{}/{}'.format(target_path.strip('/'), sub_dir), output_type):
                continue

            if not convert['code'] or ocr_all:
                if not ocr_all:
                    # Do ORC
                    tmp_dir = '{}/{}/{}/{}'.format(target_path, sub_dir, slugify(file_name),
                                                   'tmp_dir') if sub_dir else '{}/{}/{}'.format(target_path,
                                                                                                slugify(file_name),
                                                                                                'tmp_dir')
                    logging.info('Create a new temp dir: {}'.format(tmp_dir))
                    if not os.path.exists(tmp_dir):
                        mkdir_command = 'mkdir %s -p' % tmp_dir
                        os.system(mkdir_command)
                    generate_image(fp, number_of_pages, tmp_dir, images_list)

                    for i in images_list:
                        i.start()
                    time.sleep(1)

                    for i in range(number_of_pages):
                        delete_tmp = False
                        if i == number_of_pages - 1:  # last page
                            delete_tmp = True
                            t = threading.Thread(target=_ocr_process_by_png_file, name=str(i + 1),
                                                 args=(
                                                 s, pool, fp, tmp_dir, file_name, output_type, output_log, number_of_pages,
                                                 rotate, delete_tmp))
                        else:
                            t = threading.Thread(target=_ocr_process_by_png_file, name=str(i + 1),
                                                 args=(
                                                 s, pool, fp, tmp_dir, file_name, output_type, output_log, number_of_pages,
                                                 rotate, delete_tmp))
                        orc_list.append(t)
                else:
                    dest_path = '/{}/{}'.format(target_path.strip('/'), sub_dir) if sub_dir else target_path
                    t = threading.Thread(target=_ocr_process_by_pdf_file, name=str(file_name),
                                         args=(s, pool, fp, file_name, dest_path, output_type, output_log))
                    t.start()
            else:
                # Copy this file to target folder
                try:
                    _output_type = output_type.lower().split('-')
                except:
                    pass
                _target_dir = '{}/{}'.format(target_path, sub_dir) if sub_dir else target_path
                if 'pdf' in _output_type:
                    try:
                        print 'The file: {} has orced already, it will be copied to target folder.'.format(fp)
                        print 'Create a target dir: {}'.format(_target_dir)
                        if not os.path.exists(_target_dir):
                            mkdir_command = 'mkdir %s -p' % _target_dir
                            os.system(mkdir_command)
                        cp_command = 'cp -R {} {}'.format(fp, _target_dir)
                        os.system(cp_command)
                        write_log(output_log, fp, 1)
                    except Exception as error:
                        write_log(output_log, fp, -1, str(error))
                if 'text' in _output_type:
                    # write file text
                    try:
                        text = convert['text'].strip()
                        text_path = '{}/{}.txt'.format(_target_dir, file_name)
                        with codecs.open(text_path, "w", encoding="utf-8") as f:
                            f.write(text)
                        write_log(output_log, text_path, 1)
                    except Exception as error:
                        traceback.print_exc()
                        write_log(output_log, text_path, -1, str(error))
                if 'xml' in _output_type:
                    xml_out = '{}/{}.xml'.format(_target_dir, file_name)
                    t = threading.Thread(target=_process_xml, name=str(file_name), args=(s, pool, fp, xml_out))
                    t.start()

        # Generating the template images
        logging.info('Generating the template images ...')

    for c in orc_list:
        c.start()
    return 1


def _ocr_process_by_pdf_file(s, pool, fp, pdf_name, dest_path, output_type, output_log,):
    '''
        Implement ocr for threading by pdf file
        :param s: threading use semaphore technique
        :param pool: number of threads that run at a same time.
        :return:
            1: success
            0: failed
        '''
    try:
        _output_type = output_type.lower().split('-')
    except:
        pass

    with s:
        t_name = threading.currentThread().getName()
        pool.makeActive(t_name)
        try:
            from multiprocessing.pool import ThreadPool
            _pool = ThreadPool(processes=1)
            async_result = _pool.apply_async(get_orc_engine_instance, ())
            ocrEngine = async_result.get()
            if not ocrEngine:
                logging.error('Can\'t create new OCR engine instance.')
                return 0

            if not os.path.exists(dest_path):
                os.system('mkdir -p {}'.format(dest_path))
            xml_path            = '{}/{}.xml'.format(dest_path, pdf_name)
            searchable_pdf_path = '{}/{}.pdf'.format(dest_path, pdf_name)
            searchable_txt_path = '{}/{}.txt'.format(dest_path, pdf_name)

            if 'xml' in _output_type:
                logging.info('OCRing with the xml file output')
                xml_data = ocrEngine.recognize(fp, -1, -1, -1, -1, -1,
                                               OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_XML,
                                               PROP_IMG_PREPROCESS_TYPE='custom',
                                               PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()")
                try:

                    with codecs.open(xml_path, "w", encoding="utf-8") as f:
                        f.write(xml_data)
                    write_log(output_log, xml_path, 1)
                except Exception as error:
                    traceback.print_exc()
                    write_log(output_log, xml_path, -1, str(error))
            if 'text' in _output_type and 'pdf' in _output_type:
                ocr_data = ocrEngine.recognize(fp, -1, -1, -1, -1, -1,
                                               OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PDF,
                                               PROP_PDF_OUTPUT_FILE=searchable_pdf_path,
                                               PROP_PDF_OUTPUT_RETURN_TEXT='text',
                                               PROP_IMG_PREPROCESS_TYPE='custom',
                                               PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()",
                                               PROP_PDF_OUTPUT_TEXT_VISIBLE=False)
                # Create text file here
                try:
                    with codecs.open(searchable_txt_path, "w", encoding="utf-8") as f:
                        f.write(ocr_data)
                    write_log(output_log, searchable_txt_path, 1)
                    write_log(output_log, searchable_pdf_path, 1)
                except Exception as error:
                    write_log(output_log, searchable_txt_path, -1, str(error))
                    write_log(output_log, searchable_pdf_path, -1, str(error))
            elif 'pdf' in _output_type:
                try:
                    ocrEngine.recognize(fp, -1, -1, -1, -1, -1,
                                        OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PDF,
                                        PROP_PDF_OUTPUT_FILE=searchable_pdf_path,
                                        PROP_PDF_OUTPUT_RETURN_TEXT='text',
                                        PROP_IMG_PREPROCESS_TYPE='custom',
                                        PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()",
                                        PROP_PDF_OUTPUT_TEXT_VISIBLE=False, )
                    # Write the result to the log file
                    write_log(output_log, searchable_pdf_path, 1)
                except Exception as error:
                    write_log(output_log, searchable_pdf_path, -1, str(error))
            elif 'text' in _output_type:
                ocr_data = ocrEngine.recognize(fp, -1, -1, -1, -1, -1,
                                               OCR_RECOGNIZE_TYPE_TEXT, OCR_OUTPUT_FORMAT_PLAINTEXT,
                                               PROP_IMG_PREPROCESS_TYPE='custom',
                                               PROP_IMG_PREPROCESS_CUSTOM_CMDS="scale(2);default()")
                # Create text file here
                try:
                    with codecs.open(searchable_txt_path, "w", encoding="utf-8") as f:
                        f.write(ocr_data.strip())
                    write_log(output_log, searchable_txt_path, 1)
                except Exception as error:
                    write_log(output_log, searchable_txt_path, -1, str(error))

            ocrEngine.stop_engine()
            pool.makeInactive(t_name)
            return 1

        except Exception as error:
            traceback.print_exc()
            logging.error('Something went wrong!')
        pool.makeInactive(t_name)
        return 0


def execute_not_wait(cmd):
    # print 'cmd is: {}'.format(cmd)
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
    popen.stdout.close()


def _generate_image(pdf_file, dir, s_device=None):
    '''
    Implement generate template images
    :param pdf_file: the path of pdf file
    :param dir: the directory which store iamges
    :return: None
    '''
    pdf_name = os.path.basename(pdf_file).rsplit('.pdf', 1)[0]
    print 'Pdf name is: {}'.format(pdf_name)
    print 'png images: {}'.format('-sOutputFile={}/{}_%06d.png'.format(dir, pdf_name))
    if not s_device:
        s_device = 'pnggray'
    print 'Ghost script path is: {}'.format(ghost_script)
    # Generate temp images
    # /project/fbone/fbone/fbone/lib/ghostscript/bin/gs -dSAFER -dBATCH -dNOPAUSE -sDEVICE=pnggray -dINTERPOLATE -r300 -dDownScaleFactor=2 -sOutputFile=out2%d.png 1d63bab297c5bb9f9c4a4f36e10d18_1491734332.pdf -c 30000000
    execute_not_wait([
        ghost_script, '-dSAFER', '-dBATCH', '-dNOPAUSE', '-sDEVICE={}'.format(s_device), '-dINTERPOLATE',
        '-r300', '-dPDFSETTINGS=/prepress', '-dPDFFitPage', '-dDownScaleFactor=2',
        '-sOutputFile={}/{}_%06d.png'.format(dir, pdf_name), '-dUseTrimBox=true', '-dUseCropBox=true', '-f',
        str(pdf_file),
        '-c', '{}'.format(ghost_memory),
    ])


def generate_image(pdf_file, num_pages, tmp_dir, images_list):
    '''
    Generate 2 PNG files per PDF (1 for thumbnail and 1 regular size)
    :param pdf_file:
    :param dir:
    :return:
        - 1: success
        - 0: fail
    '''
    print ('generate image for file: {} ...'.format(pdf_file))
    try:
        pages_have_color = detect_color_in_pdf(pdf_file)
        if num_pages:
            if len(pages_have_color) / float(num_pages) < 0.5:
                s_device = 'pnggray'
            else:
                s_device = 'png16m'
            t = threading.Thread(target=_generate_image, name=str('tmp_image'),
                                 args=(pdf_file, tmp_dir, s_device))
            images_list.append(t)
            # t.start()

        else:
            logging.error('Pdf file invalid, number of pages equal 0')

    except Exception as error:
        traceback.print_exc()


def is_float(s):
    '''
    Chekcing if value is a float type or not
    :param s: value
    :return:
        - True: is a float type
        - False: isn't a float type
    '''
    try:
        float(s)  # for int, long and float
    except ValueError:
        return False
    return True


def detect_color_in_pdf(pdf_file):
    '''
    Detect color in pdf file
    :param pdf_file:
    :return:
    '''
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
                    if ink_values[0] > 0 or ink_values[1] > 0 or ink_values[2] > 0:
                        pages_have_color.append(lines.index(line))
        except:
            pass
        return pages_have_color

    pages_have_color = execute_and_get_page_which_contain_color([
        ghost_script, '-q', '-o', '-', '-sDEVICE=inkcov', pdf_file
    ])
    return pages_have_color


if __name__ == '__main__':
    p_rs = get_params()

    if p_rs.get('code', -1) > 0:
        params = p_rs['data']
        # Get number of cores CPU
        thread_number = params['thread-number'] if 'thread_number' in params else get_thread_number_by_server_cores()
        print ('thread number is: {}'.format(thread_number))
        pool = ThreadPool()
        s = threading.Semaphore(thread_number)

        source_path = params['source-path']
        source_path = source_path[:-1] if source_path[-1] is '/' else source_path
        output_log  = params['output-log']
        target_path = params['target-path']
        target_path = target_path[:-1] if target_path[-1] is '/' else target_path
        output_type = params['output-type']


        rotate = params.get('rotate', False)
        if rotate and str(rotate).lower() == 'true':
            rotate = True
        else:
            rotate = False

        # If --ocrall=true the it will just use asprise to OCR all of the PDF without worry about searchable vs non-searchable
        # and no need to detect page orientation (create a png files)
        ocr_all = params.get('ocr-all', False)
        if ocr_all and str(ocr_all).lower() == 'true':
            ocr_all = True
        else:
            ocr_all = False

        # Get all files in the dir and sub-dirs
        files_path = []
        for dirpath, dirnames, filenames in os.walk(source_path):
            for filename in [f for f in filenames if f.endswith(".{}".format(str(params['file-ext']).lower()))]:
                files_path.append(os.path.join(dirpath, filename))

        print '\n'
        print '***************************** params *****************************'
        print 'files path is: {}'.format(files_path)
        print 'source_path is: {}'.format(source_path)
        print 'output log is: {}'.format(output_log)
        print 'target_path is:{}'.format(target_path)
        print 'rotate is: {}'.format(rotate)
        print 'ocr_all is: {}'.format(ocr_all)
        print '***************************** params *****************************'

        r = orc_process(s, pool, files_path, source_path, target_path, output_type, output_log, rotate, ocr_all,)
        if not r:
            logging.ERROR('Can\'t start tracking tool.')