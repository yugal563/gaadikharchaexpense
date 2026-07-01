FROM mcr.microsoft.com/azure-functions/python:4-python3.11

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    STAGE_NUMBER=5

COPY pipeline/stage5_filtering/requirements.txt /
RUN pip install -r /requirements.txt

COPY pipeline/stage5_filtering/host.json /home/site/wwwroot/
COPY pipeline/stage5_filtering/stage5_filtering.py /home/site/wwwroot/function_app.py
COPY services/ /home/site/wwwroot/services/
COPY pipeline/__init__.py /home/site/wwwroot/pipeline/__init__.py
COPY pipeline/schemas.py /home/site/wwwroot/pipeline/schemas.py
