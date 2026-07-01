FROM mcr.microsoft.com/azure-functions/python:4-python3.11

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    STAGE_NUMBER=1

COPY pipeline/stage1_validation/requirements.txt /
RUN pip install -r /requirements.txt

COPY pipeline/stage1_validation/host.json /home/site/wwwroot/
COPY pipeline/stage1_validation/stage1_validation.py /home/site/wwwroot/function_app.py
COPY services/ /home/site/wwwroot/services/
COPY pipeline/__init__.py /home/site/wwwroot/pipeline/__init__.py
