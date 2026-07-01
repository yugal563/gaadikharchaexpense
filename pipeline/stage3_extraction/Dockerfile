FROM mcr.microsoft.com/azure-functions/python:4-python3.11

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

COPY pipeline/stage3_extraction/requirements.txt /
RUN pip install -r /requirements.txt

COPY pipeline/stage3_extraction/host.json /home/site/wwwroot/
COPY pipeline/stage3_extraction/schemas.py /home/site/wwwroot/schemas.py
COPY pipeline/stage3_extraction/stage3_extraction.py /home/site/wwwroot/function_app.py
COPY services/ /home/site/wwwroot/services/
