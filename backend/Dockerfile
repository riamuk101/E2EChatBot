FROM python:3.11-slim

WORKDIR /app
COPY . /app/

RUN mkdir /datasets && chown -R root:root /datasets

# sys packages
RUN apt-get update && apt-get install -y \
    build-essential libpq-dev curl openssh-server \
 && rm -rf /var/lib/apt/lists/*

# sshd
RUN mkdir -p /var/run/sshd \
 && echo 'root:ti' | chpasswd \
 && sed -i 's/PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config \
 && sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config \
 && sed -i 's/^#PermitRootLogin .*/PermitRootLogin yes/' /etc/ssh/sshd_config \
 && sed -i 's/^#PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# python deps
RUN pip install --no-cache-dir -r requirements.txt


RUN python -m playwright install && python -m playwright install-deps

ENV HOST=http://host.docker.internal

ENV PYTHONPATH=/app:/app/backend

EXPOSE 8000 22

# JSON form keeps signals clean; no --reload in CI images
CMD ["bash","-lc","service ssh start && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
