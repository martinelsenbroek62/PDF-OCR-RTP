### PDF-OCR-RTP

PDF-OCR-RTP is a Python Flask app let users do amazing things with pdf file.

### Required:

* [x] Have a connection to RABBIT MQ and listen to “pdf_request” channel.
* [x] When receiving a message, pop that message out from the queue and call ESD API to get 1 dirty document. ESD API will return the dirty document information.
* [x] Use the information from #2, make a rsync connection to the server to download the file.
* [x] If #2 said: it’s a BULK scan, then read the 2D Datamatrix ECC200 Barcode on the document.
* [x] Split the PDF based on the barcode (example multipage PDF: Page #1: barcode, page#2 content, page#3 content, page#4 barcode, page#5 content) you will split 1 PDF into 2 PDFs without the barcode(2 pages and 1 page PDF).
* [x] Rsync each of the PDF back to “scannedimages” folder.
* [x] Call ESD API – Split process API and send in  priority_id, barcode, filename, source_bookmark_process_queue_id (For each document – in this example: call the API 2x)
* [x] When completed, call ESD API to mark the document processed and synched.
* [x] If #2 said: it’s a NON-BULK scan, Split the PDF into single page pdf.
* [x] Generate 2 PNG files per PDF (1 for thumbnail and 1 regular size)
* [x] Preprocess PDF (Deskew, etc.. ), OCR PDF ( we will purchase Asprise PDF SDK – they have option to do this )
* [x] Generate textfile per PDF depend on Sphinx Type .
* [x] After everything is finished, create a box folder and store everything in the folder by following the structure
* [x] Rsync the folder back to the server, into pkged folder
* [x] Call ESD API to add all of the filenames/pieces
* [x] Call ESD api to mark the document processed.

### How to deploy

1. Deploy AI code
        
    # Update pip and virtualenv

    `sudo pip install --upgrade pip`

    if no pip file like that:
    
    ```
    -bash: /usr/bin/pip: No such file or directory, then run this command: sudo ln -s /usr/local/bin/pip /usr/bin/pip
    sudo pip install --upgrade virtualenv
    ```
        
    # Run env environment

    ```
    virtualenv env
    source env/bin/activate
    ```
        
    # Install all libs which need to deploy  code

    ```
    sudo yum groupinstall 'Development Tools'
    sudo yum install python-devel mysql-devel libffi libffi-devel libxslt-devel libxml2-devel libjpeg-devel zlib-devel libXt.{i686,x86_64}
    cd libs && sudo rpm -Uvh libdmtx-0.7.2-16.el7.x86_64.rpm
    ```

    # Run file deploy.py in libs

    `python deploy.py`
        
    # After everything is finished, run this command to test the celery:

    `celery -A fbone.ai.tasks worker -c 1 --max-tasks-per-child=1 --loglevel=info --workdir=/ai/PDF-OCR-RTP/ -Q pdf_request`

    if its ok, you will see something like that: ![alt text](http://i.imgur.com/Ev91ES8.png)Ctrl + C to exit
            
2. Install tesseract for detecting page orientation, install pdftk for flating pdf file.

    2.1. Enabel epel6 repo

    `sudo vi /etc/yum.repos.d/epel.repo` and edit enabled=1 like that:

    ```
    [epel]
    name=Extra Packages for Enterprise Linux 6 - $basearch
    #baseurl=http://download.fedoraproject.org/pub/epel/6/$basearch
    mirrorlist=https://mirrors.fedoraproject.org/metalink?repo=epel-6&arch=$basearch
    failovermethod=priority
    enabled=1
    gpgcheck=1
    gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-EPEL-6
    ```

    2.2. Exclude libwebp package in amzn-main repo:

    ```
    cat /etc/yum.repos.d/amzn-main.repo
    [amzn-main]
    exclude = libwebp*
    ...
    ```

    2.3. Install tesseract and  leptonica

    ```
    sudo yum install epel-release
    sudo yum install tesseract-devel leptonica-devel
    ```

    2.4. Copy training data to perform detect page orientation

    `sudo mv /ai/PDF-OCR-RTP/libs/training_data/* /usr/share/tesseract/tessdata`

    2.5. Test with command:

    `tesseract /ai/PDF-OCR-RTP/tmp_dir/test_orientation.png - -psm 0`

     and output like that:
    
    ```
    Orientation: 2
    Orientation in degrees: 180
    Orientation confidence: 6.21
    Script: 1
    Script confidence: 10.83
    ```

    2.6. Install pdftk

    if centos 6.x:
    - Following by: http://www.serveridol.com/2015/04/01/how-i-install-pdftk-server-in-centos-6-aws-server/ to install pdftk on AMZ Linux
    else: (# for centos 7.x or latest)
    - yum localinstall https://www.linuxglobal.com/static/blog/pdftk-2.02-1.el7.x86_64.rpm

3. Check ssh and connection between Workers and Queue center(linux7.sima.io)
                 
4. Edit config for AI program.

    File configure located at: /ai/PDF-OCR-RTP/fbone/config.py
    - GET_RECORDS_URL: the ESD url
    - API_KEY: the api_key param belongs to ESD api
    - API_SIG: the api_sig param belongs to ESD api
    - PROCESSING_ORDER: the processing_order param belongs to ESD api
    - NUMBER_OF_RECORD: the number_of_record param belongs to ESD api
    - MACHINE_NAME: the machine_name belongs to ESD api
    - PRIORITY_ID: the priority_id belongs to ESD api

    - UPLOAD_SERVER: domain name of Queue server
    - UPLOAD_USER: user name have a permission to upload files on Queue server

    - TMP_DIR_BULK: the path to process in bulk situation
    - TMP_DIR_NON_BULK: the path to process in non-bulk situation

    - THREAD_NUM: number of threads run at a same time, depend on cores of server (ex: A server have 4 cores, thread_num will be 4)
    - GHOST_SCRIPT: path of ghostscript software
    - GHOST_MEMORY = 300000: give Ghostscript 0.3 MB of extra RAM
                                 
5. Install supervisor

    # install

    ```
    sudo pip install supervisor
    sudo cp /ai/PDF-OCR-RTP/libs/supervisor/supervisord.* /etc/ -R
    sudo mkdir -p /var/log/supervisor/
    ```
                     
    # Check supervisor is running after installing

    ```
    (env) [karen@ip-172-30-3-218 fbone]$ sudo netstat -anp | grep 9001
    [sudo] password for karen:
    tcp        0      0 0.0.0.0:9001                0.0.0.0:*                   LISTEN      18392/python2.7
    ```

    # Run supervisor

    `sudo /usr/local/bin/supervisord -c /etc/supervisord.conf` (or you can find a script to start/stop/restart Supervisor and put it in /etc/init.d)
                         
    # Manage supervisor

    ```
    sudo /usr/local/bin/supervisorctl
        + start ai
            after starting, check celery by command:
                (env) [karen@ip-172-30-3-218 fbone]$ ps -ef | grep celery
                karen    18897 18392  0 04:16 ?        00:00:05 /ai/PDF-OCR-RTP/env/bin/python2.7 /ai/PDF-OCR-RTP/env/bin/celery -A fbone.ai.tasks worker -c 1 --max-tasks-per-child=1 --loglevel=info --workdir=/ai/PDF-OCR-RTP -Q pdf_request
                karen    19689 18897  0 05:01 ?        00:00:00 /ai/PDF-OCR-RTP/env/bin/python2.7 /ai/PDF-OCR-RTP/env/bin/celery -A fbone.ai.tasks worker -c 1 --max-tasks-per-child=1 --loglevel=info --workdir=/ai/PDF-OCR-RTP -Q pdf_request
                karen    19747  4838  0 05:49 pts/0    00:00:00 grep --color=auto celery
                It only have 2 Celery instances run at a same time.
        + stop ai
            after stop, check celery by command:
                (env) [karen@ip-172-30-3-218 fbone]$ ps -ef | grep celery
                karen    19755  4838  0 05:52 pts/0    00:00:00 grep --color=auto celery
        + status ai
    ```

    *Note*: after you buy Asprise license, you can edit /etc/supervisord.d/celery.sh and take out the param: --max-tasks-per-child=1. It will become: 
    exec celery -A fbone.ai.tasks worker -c 1 --loglevel=info --workdir=/ai/PDF-OCR-RTP -Q pdf_request
    and the Celery no need to create new process after it processed, because in Asprise non-license mode, it allows we process maximum 100 pdf pages for one session.

### License

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
            
    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
