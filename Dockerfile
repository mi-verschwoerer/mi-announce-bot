FROM python

WORKDIR /app

COPY requirements.txt ./

RUN apt-get install -y cowsay fortune

RUN pip install -r requirements.txt

COPY mi-bot.py .

CMD ["python", "mi-bot.py"]
