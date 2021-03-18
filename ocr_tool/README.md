ORC Tool

ORC Tool is a Python script which implement ORC technology

Submitted by: Karen

Time spent: 2 weeks

### How to deploy

1. # Install the GhostScript
        wget https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs921/ghostscript-9.21.tar.gz
        cd ghostscript-9.21
        ./configure --prefix=/ai/PDF-OCR-RTP/ocr_tool/libs/ghostscript
        make && make install
        
2. # Install tesseract for detecting page orientation
        2.1. Enabel epel6 repo
            sudo vi /etc/yum.repos.d/epel.repo
            and edit enabled=1 like that:
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
            cat /etc/yum.repos.d/amzn-main.repo
            [amzn-main]
            exclude = libwebp*
            ...
         2.3. Install tesseract and leptonica
            sudo yum install epel-release
            sudo yum install tesseract-devel leptonica-devel
         2.4. Copy training data to perform detect page orientation
            sudo mv /ai/PDF-OCR-RTP/libs/training_data/* /usr/share/tesseract/tessdata
         2.5. Test with command:
             tesseract /ai/PDF-OCR-RTP/tmp_dir/test_orientation.png - -psm 0
             and output like that:
             ```
            Orientation: 2
            Orientation in degrees: 180
            Orientation confidence: 6.21
            Script: 1
            Script confidence: 10.83
            ```
3. # Update pip and virtualenv
        sudo pip install --upgrade pip
        (if no pip file like that: -bash: /usr/bin/pip: No such file or directory, then run this command: sudo ln -s /usr/local/bin/pip /usr/bin/pip)
        sudo pip install --upgrade virtualenv
    
4. # Install all required packages for OCR tool
            cd /ai/PDF-OCR-RTP/orc_tool && pip install -r requirements.txt
   # Install pdftotext lib
            sudo yum install gcc-c++ pkgconfig poppler-cpp-devel python-devel redhat-rpm-config
            cd /ai/PDF-OCR-RTP/orc_tool && pip install -r requirements.txt
     If you get an error with pdftotext lib (cannot found this lib ...), plz do this:
            export PYTHONPATH=/project/env/lib64/python2.7/dist-packages/
            pip install pdftotext     
5. # Run env environment
        virtualenv env
        source env/bin/activate
    
6. # Run the orc command
        python ocr_asprise.py file-ext=pdf output-type=PDF source-path="/path/to/input/files/" target-path="/path/to/output/files"  output-log="/path/to/the/log/file.txt" rotate=false ocr-all=false
        
        
### Setting configure variables for OCR tool
File configure located at: /ai/PDF-OCR-RTP/ocr_tool/ocr_asprise.py
1.  ghost_script: path to ghost script execute, something like that: '/ai/PDF-OCR-RTP/ocr_tool/libs/ghost_script/bin/gs'
2.  ghost_memory=300000: give Ghostscript 0.3 MB of extra RAM
3.  timeout: number of retries when do the ocr process, default is 3


### More details about the parameters
1.  ocr_asprise.py is the name of the tool
2.  file-ext: file extension that you will crawl through to OCR
3.  output-type: there are 3 options here: TEXT (output textfile only), TEXT-PDF (output textfile and PDF), PDF  (output PDF only)
4.  source-path: source where the directory you will need to crawl.. in this example you will find all of the .pdf extension in this folder and subfolder, then ocr and generate text and pdf file
5.  target-path: where you will save the output, keep structure the same
6.  output-log: you will list each file with timestamp in the front with the following info:
    [timestamp][SUCCESS][] /source/path/asdasdsa/adasdas1.pdf
    [timestamp][BLANK][] /source/path/asdasdsa/adasdas2.pdf
    [timestamp][FAILED][ERROR message] /source/path/asdasdsa/adasdas3.pdf
7.  rotate: auto rotate the output true/false default false
8.  ocr-all: it will just use asprise to OCR all of the PDF without worry about searchable vs non-searchable
9.  help: show all of the parameters
 
 
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
