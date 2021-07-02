FROM python

WORKDIR /app

#Add /usr/games
ENV PATH /usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games

COPY requirements.txt ./

RUN apt update

RUN apt install -y cowsay fortune

#Minification step: Delete repository indexes (undos apt update)
RUN rm -rf /var/lib/apt/lists/*

RUN pip install -r requirements.txt

COPY mi-bot.py .

CMD ["python", "mi-bot.py"]
