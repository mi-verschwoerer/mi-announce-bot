FROM python

WORKDIR /app

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY mi-bot.py .

CMD ["python", "mi-bot.py"]
