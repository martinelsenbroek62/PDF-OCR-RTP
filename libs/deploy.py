# -*- coding: utf-8 -*-
import os
import sys
from subprocess import check_output
import time

#install requirements
path_to_requirements = '/ai/PDF-OCR-RTP/requirements.txt'
req_cm = 'pip install -r {}'.format(path_to_requirements)
os.system(req_cm)
os.system('pip install pdfsplit==0.4.2')
print 'install requirements success'

out = check_output(["pip", "--version"])
#out will be like: pip 6.0.8 from /ai/PDF-OCR-RTP/env/local/lib/python2.7/dist-packages (python 2.7)
path = out.split('from ')[1].rsplit(' (',1)[0] #expected this value equal to : /ai/PDF-OCR-RTP/env/local/lib/python2.7/dist-packages or /ai/PDF-OCR-RTP/env/local/lib/python2.7/site-packages

#edit lib asprise, commment last line: #from ocr_app import OcrApp, run_ocr_app
src = '/ai/PDF-OCR-RTP/libs/asprise_lib/__init__.py'
dest = '{}/asprise_ocr_api/'.format(path)
cp_cm = 'cp {} {}'.format(src, dest)
os.system(cp_cm)

#cp asprise lib
asprise_lib_path = '/ai/PDF-OCR-RTP/libs/asprise_lib/libaocr_x64.so'
asprise_lib_dest_path = '{}/{}'.format(path, 'asprise_ocr_api/lib')
mkdir_cm = 'mkdir {}'.format(asprise_lib_dest_path)
os.system(mkdir_cm)
cp_cm = 'cp {} {}'.format(asprise_lib_path,asprise_lib_dest_path)
os.system(cp_cm)

#edit lib celery
src = '/ai/PDF-OCR-RTP/libs/celery/consumer.py'
dest = '{}/celery/worker/consumer/'.format(path)
cp_cm = 'cp {} {}'.format(src, dest)
os.system(cp_cm)
