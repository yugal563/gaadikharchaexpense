FROM mcr.microsoft.com/azure-functions/python:4-python3.11

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    STAGE_NUMBER=6

COPY pipeline/stage6_db_service/requirements.txt /
RUN pip install -r /requirements.txt

COPY pipeline/stage6_db_service/host.json /home/site/wwwroot/
COPY pipeline/stage6_db_service/stage6_db_service.py /home/site/wwwroot/function_app.py
COPY services/ /home/site/wwwroot/services/
COPY models.py /home/site/wwwroot/
COPY pipeline/__init__.py /home/site/wwwroot/pipeline/__init__.py
