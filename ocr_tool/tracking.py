#!/usr/bin/python
import os
import sys
import psutil
import time
import glob

params = sys.argv

def check_pid_exists(pid):
    '''
    Checking to see if a pid corresponds to a valid process
    :param pid:
    :return:
        True: is existing
        False: is killed
    '''
    if psutil.pid_exists(pid):
        return True
    return False

def is_finish(output_type, source_path, dest_path):
    '''
    Checking to see if OCR tool is finished?
    :param output_type: there are 7 options here: PDF, PDF-TEXT, PDF-XML, PDF-TEXT-XML, TEXT, TEXT-XML, XML
    :param source_path: the input path
    :param dest_path: the target path
    :return:
        - True: is finised
        - False: not finished yet

    '''
    output_type = output_type.lower().split('-')

    number_of_input_file = 0
    for dirpath, dirnames, filenames in os.walk(source_path):
        for filename in [f for f in filenames if f.endswith(".pdf")]:
            number_of_input_file += 1

    for o in output_type:
        if o == 'text':
            o = 'txt'
        number_of_output_file = 0
        for dirpath, dirnames, filenames in os.walk(dest_path):
            for filename in [f for f in filenames if f.endswith(".{}".format(o))]:
                number_of_output_file += 1

        if number_of_output_file != number_of_input_file:
            return False
    return True


if __name__ == '__main__':
    try:
        pid             = int(params[1])
        file_ext        = str(params[2])
        output_type     = str(params[3])
        source_path     = str(params[4])
        target_path     = str(params[5])
        output_log      = str(params[6])
        rotate          = str(params[7])
        try:
            ocr_all     = str(params[8])
        except:
            ocr_all     = False
        print ('\n')
        print ('####################################params#################################')

        print ('file_ext: {}'.format(file_ext))
        print ('output_type: {}'.format(output_type))
        print ('source_path: {}'.format(source_path))
        print ('target_path: {}'.format(target_path))
        print ('output_log: {}'.format(output_log))
        print ('rotate: {}'.format(rotate))
        print ('ocr_all: {}'.format(ocr_all))
        print ('\n')

        while(True):
            time.sleep(10)
            if not check_pid_exists(pid):
                # Checking all files are completed
                if not is_finish(output_type, source_path, target_path):
                    print ('core dump detected, the OCR tool will be started again')
                    ocr_file = current_path = os.path.dirname(os.path.abspath(__file__)) + '/ocr_asprise.py'
                    run_cm = 'python {} file-ext={} output-type={} source-path="{}" target-path="{}" output-log={} rotate={} ocr-all={}'.format(
                        ocr_file,
                        file_ext,
                        output_type,
                        source_path,
                        target_path,
                        output_log,
                        rotate,
                        ocr_all,
                    )
                    os.system(run_cm)
                break
    except:
        print ('Something went wrong with params')



