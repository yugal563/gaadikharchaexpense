FROM mcr.microsoft.com/azure-functions/python:4-python3.11

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    STAGE_NUMBER=2

COPY pipeline/stage2_preprocessing/requirements.txt /
RUN pip install -r /requirements.txt

COPY pipeline/stage2_preprocessing/host.json /home/site/wwwroot/
COPY pipeline/stage2_preprocessing/stage2_preprocessing.py /home/site/wwwroot/function_app.py
COPY services/ /home/site/wwwroot/services/
COPY pipeline/__init__.py /home/site/wwwroot/pipeline/__init__.py
